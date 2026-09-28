"""Event-driven, next-session, bar-by-bar long-only execution simulator."""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace

import pandas as pd

from indiaagents.strategy import (
    DeterministicPlan,
    DeterministicStrategyEngine,
    PortfolioInputs,
    SignalState,
    StrategyConfig,
    StrategyEvidence,
)
from indiaagents.strategy.features import normalize_ohlcv

from .costs import IndiaCostConfig, execution_price, transaction_cost


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    max_risk_pct: float = 1.0
    max_single_stock_pct: float = 20.0
    risk_profile: str = "balanced"
    horizon: str = "positional"
    same_bar_policy: str = "adverse"  # adverse | target_first
    partial_exit_pct: float = 50.0
    entry_order_valid_sessions: int = 1
    minimum_warmup: int = 220
    force_liquidate_at_end: bool = True
    setup_names: tuple[str, ...] = ()  # empty = all deterministic setups


@dataclass
class Fill:
    date: str
    side: str
    quantity: int
    raw_price: float
    price: float
    reason: str
    charges: float
    slippage_impact: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    setup: str
    regime: str
    sector: str | None
    quantity: int
    entry_price: float
    average_exit_price: float
    initial_stop: float
    target_1: float | None
    target_2: float | None
    gross_pnl: float
    net_pnl: float
    return_pct: float
    r_multiple: float
    holding_sessions: int
    exit_reason: str
    stop_hit: bool
    gap_loss: bool
    costs: float
    fills: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    initial_capital: float
    final_equity: float
    trades: list[Trade]
    fills: list[Fill]
    events: list[dict]
    equity_curve: pd.DataFrame
    config: BacktestConfig
    cost_config: IndiaCostConfig
    data_limitations: list[str] = field(default_factory=list)

    def to_dict(self, include_curve: bool = False) -> dict:
        out = {
            "initial_capital": self.initial_capital, "final_equity": self.final_equity,
            "trades": [x.to_dict() for x in self.trades],
            "fills": [x.to_dict() for x in self.fills], "events": self.events,
            "config": asdict(self.config), "cost_config": self.cost_config.to_dict(),
            "data_limitations": self.data_limitations,
        }
        if include_curve:
            out["equity_curve"] = self.equity_curve.reset_index().to_dict("records")
        return out


@dataclass
class _Position:
    original_qty: int
    remaining_qty: int
    entry_date: pd.Timestamp
    entry_index: int
    entry_price: float
    raw_entry_price: float
    entry_cash: float
    entry_charges: float
    stop: float
    trail: float | None
    target1: float | None
    target2: float | None
    t1_done: bool
    highest_close: float
    initial_risk: float
    setup: str
    regime: str
    sector: str | None
    fills: list[Fill]
    exit_cash: float = 0.0
    exit_gross: float = 0.0
    exit_qty: int = 0
    total_cost: float = 0.0
    gap_loss: bool = False
    stop_hit: bool = False
    last_exit_reason: str = ""


SignalProvider = Callable[[pd.Timestamp, PortfolioInputs], DeterministicPlan]


class EventDrivenBacktester:
    def __init__(self, strategy_config: StrategyConfig | None = None,
                 backtest_config: BacktestConfig | None = None,
                 cost_config: IndiaCostConfig | None = None):
        base = (strategy_config or StrategyConfig()).validated()
        # Acceptance is evaluated after unseen windows.  Turning it off here does
        # not grant an edge; it only allows occurrences to be measured.
        self.engine = DeterministicStrategyEngine(replace(base, require_validated_edge=False))
        self.config = backtest_config or BacktestConfig()
        self.costs = cost_config or IndiaCostConfig()

    def run(self, stock: pd.DataFrame, *, nifty: pd.DataFrame | None = None,
            sector: pd.DataFrame | None = None, peer: pd.DataFrame | None = None,
            sector_symbol: str | None = None, sector_name: str | None = None,
            signal_start: str | pd.Timestamp | None = None,
            signal_end: str | pd.Timestamp | None = None,
            signal_provider: SignalProvider | None = None,
            data_limitations: list[str] | None = None) -> BacktestResult:
        d = normalize_ohlcv(stock)
        if len(d) < max(3, self.config.minimum_warmup):
            raise ValueError(f"Backtest needs at least {self.config.minimum_warmup} valid sessions")
        prepared = None if signal_provider else self.engine.prepare(d, nifty, sector, peer, sector_symbol)
        start = pd.Timestamp(signal_start) if signal_start is not None else d.index[self.config.minimum_warmup]
        end = pd.Timestamp(signal_end) if signal_end is not None else d.index[-1]
        cash = float(self.config.initial_capital)
        position: _Position | None = None
        pending_entry: tuple[DeterministicPlan, int] | None = None
        pending_exit: tuple[str, float] | None = None  # reason, fraction
        fills: list[Fill] = []
        trades: list[Trade] = []
        events: list[dict] = []
        curve_rows: list[dict] = []

        def equity(mark: float) -> float:
            return cash + (position.remaining_qty * mark if position else 0.0)

        for i, (dt, bar) in enumerate(d.iterrows()):
            if dt < start or dt > end:
                continue
            # Any order generated after the previous close may execute now.
            if pending_exit and position:
                reason, fraction = pending_exit
                quantity = position.remaining_qty if fraction >= 1 else max(1, math.floor(position.remaining_qty * fraction))
                cash, position, closed = self._sell(dt, float(bar["Open"]), quantity, reason,
                                                    cash, position, i, fills)
                if closed:
                    trades.append(closed)
                pending_exit = None
            if pending_entry and position is None:
                plan, age = pending_entry
                raw = None
                if plan.entry_zone and float(bar["Open"]) > plan.entry_zone.high:
                    events.append({"date": dt.date().isoformat(), "event": "ENTRY_CANCELLED_GAP_ABOVE_ZONE"})
                elif plan.entry_zone and float(bar["Open"]) >= plan.entry_zone.low:
                    raw = float(bar["Open"])
                elif plan.entry_zone and float(bar["High"]) >= plan.entry_zone.low:
                    raw = float(plan.entry_zone.low)
                if raw is not None and plan.initial_stop is not None and raw > plan.initial_stop:
                    risk_budget = equity(float(bar["Open"])) * self.config.max_risk_pct / 100
                    expected_fill, _ = execution_price(raw, "BUY", self.costs)
                    # Include configured entry slippage/impact in both risk and
                    # allocation sizing; otherwise the simulated position can
                    # exceed the user's budget before its first bar.
                    qty = min(
                        plan.quantity,
                        math.floor(risk_budget / (expected_fill - plan.initial_stop)),
                    )
                    max_alloc_qty = math.floor(
                        equity(float(bar["Open"])) * self.config.max_single_stock_pct
                        / 100 / expected_fill
                    )
                    qty = min(qty, max_alloc_qty)
                    if qty > 0:
                        cash, position, fill = self._buy(dt, raw, qty, plan, cash, i, sector_name)
                        fills.append(fill)
                    else:
                        events.append({"date": dt.date().isoformat(), "event": "ENTRY_REJECTED_ZERO_SIZE"})
                elif raw is not None:
                    events.append({"date": dt.date().isoformat(), "event": "ENTRY_CANCELLED_INVALIDATED_AT_OPEN"})
                pending_entry = None if age + 1 >= self.config.entry_order_valid_sessions else (plan, age + 1)

            # Conservative intrabar event ordering.  The stop effective at today's
            # open was fixed after a prior close; today's close/ATR cannot alter it.
            if position:
                stop = max(position.stop, position.trail or 0.0)
                open_px, low, high = float(bar["Open"]), float(bar["Low"]), float(bar["High"])
                stop_touch = low <= stop
                t1_touch = not position.t1_done and position.target1 is not None and high >= position.target1
                t2_touch = position.target2 is not None and high >= position.target2
                if open_px <= stop:
                    position.gap_loss = True
                    position.stop_hit = True
                    cash, position, closed = self._sell(dt, open_px, position.remaining_qty,
                                                        "GAP_THROUGH_STOP", cash, position, i, fills)
                    if closed:
                        trades.append(closed)
                elif stop_touch and (self.config.same_bar_policy == "adverse" or not (t1_touch or t2_touch)):
                    position.stop_hit = True
                    stop_reason = ("TRAILING_STOP" if position.trail is not None
                                   and position.trail > position.stop else "STOP_LOSS")
                    cash, position, closed = self._sell(dt, stop, position.remaining_qty,
                                                        stop_reason, cash, position, i, fills)
                    if closed:
                        trades.append(closed)
                elif position:
                    if t1_touch:
                        q = max(1, math.floor(position.original_qty * self.config.partial_exit_pct / 100))
                        q = min(q, position.remaining_qty)
                        cash, position, closed = self._sell(dt, float(position.target1), q,
                                                            "TARGET_1_PARTIAL", cash, position, i, fills)
                        if closed:
                            trades.append(closed)
                        elif position:
                            position.t1_done = True
                    if position and t2_touch:
                        cash, position, closed = self._sell(dt, float(position.target2), position.remaining_qty,
                                                            "TARGET_2", cash, position, i, fills)
                        if closed:
                            trades.append(closed)

            # Mark after intrabar fills.
            mark_equity = equity(float(bar["Close"]))
            curve_rows.append({"date": dt, "equity": mark_equity,
                               "exposed": bool(position), "close": float(bar["Close"])})

            # Signals are generated after close and cannot fill this candle.
            portfolio = PortfolioInputs(
                existing_holding=bool(position),
                average_buy_price=position.entry_price if position else None,
                current_quantity=position.remaining_qty if position else 0,
                portfolio_capital=max(0.0, mark_equity), max_risk_pct=self.config.max_risk_pct,
                max_single_stock_pct=self.config.max_single_stock_pct,
                horizon=self.config.horizon, risk_profile=self.config.risk_profile,
            )
            plan = (signal_provider(dt, portfolio) if signal_provider else self.engine.on_date(
                prepared, as_of=dt, portfolio=portfolio, evidence=StrategyEvidence(
                    status="MEASUREMENT MODE — acceptance evaluated after OOS aggregation",
                    validated_edge=True,
                ), data_limitations=[],
            ))
            if position:
                # End-of-day trailing update, effective next bar only.
                position.highest_close = max(position.highest_close, float(bar["Close"]))
                atr = plan.daily.get("atr14")
                if atr is not None:
                    next_trail = position.highest_close - self.engine.config.trailing_atr * float(atr)
                    position.trail = max(position.trail or position.stop, next_trail)
                if position.t1_done:
                    position.trail = max(position.trail or position.stop, position.entry_price)
                held = i - position.entry_index + 1
                if plan.action.value == "EXIT":
                    pending_exit = ("TREND_OR_RS_EXIT", 1.0)
                elif plan.action.value == "TRIM":
                    pending_exit = ("DETERMINISTIC_TRIM", 0.5)
                elif held >= plan.time_stop_sessions:
                    pending_exit = ("TIME_STOP", 1.0)
            elif (plan.signal_state == SignalState.ACTIVE and plan.initial_stop is not None
                  and plan.quantity > 0
                  and (not self.config.setup_names or plan.setup_name in self.config.setup_names)):
                pending_entry = (plan, 0)

        if position and self.config.force_liquidate_at_end:
            dt = min(end, d.index[-1])
            bar = d.loc[:dt].iloc[-1]
            idx = int(d.index.get_loc(d.loc[:dt].index[-1]))
            cash, position, closed = self._sell(dt, float(bar["Close"]), position.remaining_qty,
                                                "TEST_WINDOW_END", cash, position, idx, fills)
            if closed:
                trades.append(closed)
            if curve_rows:
                curve_rows[-1]["equity"] = cash
                curve_rows[-1]["exposed"] = False
        curve = pd.DataFrame(curve_rows).set_index("date") if curve_rows else pd.DataFrame(
            columns=["equity", "exposed", "close"]
        )
        final = float(curve["equity"].iloc[-1]) if len(curve) else cash
        return BacktestResult(self.config.initial_capital, final, trades, fills, events, curve,
                              self.config, self.costs, list(data_limitations or []))

    def _buy(self, dt: pd.Timestamp, raw: float, qty: int, plan: DeterministicPlan,
             cash: float, index: int, sector: str | None) -> tuple[float, _Position, Fill]:
        price, slip_share = execution_price(raw, "BUY", self.costs)
        cb = transaction_cost(price, qty, "BUY", self.costs, slip_share * qty)
        fill = Fill(dt.date().isoformat(), "BUY", qty, raw, round(price, 6),
                    "NEXT_SESSION_ENTRY", cb.cash_charges, cb.slippage_impact)
        outlay = price * qty + cb.cash_charges
        regime = str(plan.weekly.get("trend_state") or "unavailable")
        position = _Position(
            qty, qty, dt, index, price, raw, outlay, cb.cash_charges,
            float(plan.initial_stop), None, plan.target_1, plan.target_2, False,
            raw, (price - float(plan.initial_stop)) * qty, plan.setup_name, regime,
            sector, [fill], total_cost=cb.economic_cost,
        )
        return cash - outlay, position, fill

    def _sell(self, dt: pd.Timestamp, raw: float, qty: int, reason: str, cash: float,
              position: _Position, index: int, all_fills: list[Fill]) -> tuple[float, _Position | None, Trade | None]:
        qty = min(max(0, int(qty)), position.remaining_qty)
        price, slip_share = execution_price(raw, "SELL", self.costs)
        cb = transaction_cost(price, qty, "SELL", self.costs, slip_share * qty)
        fill = Fill(dt.date().isoformat(), "SELL", qty, raw, round(price, 6), reason,
                    cb.cash_charges, cb.slippage_impact)
        all_fills.append(fill)
        position.fills.append(fill)
        proceeds = price * qty - cb.cash_charges
        cash += proceeds
        position.exit_cash += proceeds
        position.exit_gross += raw * qty
        position.exit_qty += qty
        position.remaining_qty -= qty
        position.total_cost += cb.economic_cost
        position.last_exit_reason = reason
        if position.remaining_qty > 0:
            return cash, position, None
        avg_exit = position.exit_gross / position.exit_qty if position.exit_qty else 0.0
        gross = (avg_exit - position.raw_entry_price) * position.original_qty
        net = position.exit_cash - position.entry_cash
        ret = net / position.entry_cash * 100 if position.entry_cash else 0.0
        r = net / position.initial_risk if position.initial_risk > 0 else 0.0
        trade = Trade(
            position.entry_date.date().isoformat(), dt.date().isoformat(), position.setup,
            position.regime, position.sector, position.original_qty, round(position.entry_price, 6),
            round(avg_exit, 6), position.stop, position.target1, position.target2,
            round(gross, 6), round(net, 6), round(ret, 6), round(r, 6),
            max(1, index - position.entry_index + 1), reason, position.stop_hit,
            position.gap_loss, round(position.total_cost, 6),
            [x.to_dict() for x in position.fills],
        )
        return cash, None, trade
