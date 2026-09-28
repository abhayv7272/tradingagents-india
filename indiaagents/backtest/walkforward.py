"""Rolling/expanding walk-forward evaluation with embargoed boundaries."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import pandas as pd

from indiaagents.strategy import StrategyConfig
from indiaagents.strategy.features import normalize_ohlcv
from .costs import IndiaCostConfig
from .execution import BacktestConfig, BacktestResult, EventDrivenBacktester
from .metrics import AcceptanceConfig, acceptance_gate, calculate_metrics


@dataclass(frozen=True)
class WalkForwardConfig:
    train_sessions: int = 504
    validation_sessions: int = 126
    test_sessions: int = 126
    step_sessions: int = 126
    embargo_sessions: int = 5
    expanding: bool = True
    minimum_windows: int = 3


@dataclass(frozen=True)
class WalkForwardWindow:
    number: int
    train_start: str
    train_end: str
    validation_start: str
    validation_end: str
    test_start: str
    test_end: str
    embargo_sessions: int
    parameter_hash: str


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    window_metrics: list[dict]
    aggregate: BacktestResult
    metrics: dict
    acceptance: dict
    methodology: dict

    def to_dict(self, include_curve: bool = False) -> dict:
        return {
            "windows": [asdict(x) for x in self.windows], "window_metrics": self.window_metrics,
            "metrics": self.metrics, "acceptance": self.acceptance,
            "methodology": self.methodology,
            "aggregate": self.aggregate.to_dict(include_curve=include_curve),
        }


def walk_forward_splits(index: pd.DatetimeIndex,
                        config: WalkForwardConfig | None = None) -> list[tuple[slice, slice, slice]]:
    cfg = config or WalkForwardConfig()
    n = len(index)
    out: list[tuple[slice, slice, slice]] = []
    train_end = cfg.train_sessions
    while True:
        train_start = 0 if cfg.expanding else max(0, train_end - cfg.train_sessions)
        val_start = train_end + cfg.embargo_sessions
        val_end = val_start + cfg.validation_sessions
        test_start = val_end + cfg.embargo_sessions
        test_end = test_start + cfg.test_sessions
        if test_end > n:
            break
        out.append((slice(train_start, train_end), slice(val_start, val_end), slice(test_start, test_end)))
        train_end += cfg.step_sessions
    return out


def _parameter_hash(strategy: StrategyConfig, costs: IndiaCostConfig,
                    backtest: BacktestConfig) -> str:
    payload = json.dumps({"strategy": asdict(strategy), "costs": asdict(costs),
                          "backtest": asdict(backtest)}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def run_walk_forward(stock: pd.DataFrame, *, nifty: pd.DataFrame | None = None,
                     sector: pd.DataFrame | None = None, peer: pd.DataFrame | None = None,
                     sector_symbol: str | None = None, sector_name: str | None = None,
                     strategy_config: StrategyConfig | None = None,
                     backtest_config: BacktestConfig | None = None,
                     cost_config: IndiaCostConfig | None = None,
                     walk_config: WalkForwardConfig | None = None,
                     acceptance_config: AcceptanceConfig | None = None,
                     stock_count: int = 1,
                     data_limitations: list[str] | None = None) -> WalkForwardResult:
    d = normalize_ohlcv(stock)
    sc = (strategy_config or StrategyConfig()).validated()
    bc = backtest_config or BacktestConfig()
    cc = cost_config or IndiaCostConfig()
    wc = walk_config or WalkForwardConfig()
    splits = walk_forward_splits(d.index, wc)
    if not splits:
        raise ValueError(
            f"Insufficient history ({len(d)} sessions) for train={wc.train_sessions}, "
            f"validation={wc.validation_sessions}, test={wc.test_sessions}, embargo={wc.embargo_sessions}"
        )
    phash = _parameter_hash(sc, cc, bc)
    windows: list[WalkForwardWindow] = []
    results: list[BacktestResult] = []
    wm: list[dict] = []
    for number, (tr, va, te) in enumerate(splits, 1):
        train_idx, val_idx, test_idx = d.index[tr], d.index[va], d.index[te]
        window = WalkForwardWindow(
            number, train_idx[0].date().isoformat(), train_idx[-1].date().isoformat(),
            val_idx[0].date().isoformat(), val_idx[-1].date().isoformat(),
            test_idx[0].date().isoformat(), test_idx[-1].date().isoformat(),
            wc.embargo_sessions, phash,
        )
        # Fixed v1 parameters are frozen before every test.  Validation is retained
        # as an explicit boundary; no test metric feeds parameter selection.
        bt = EventDrivenBacktester(sc, bc, cc)
        result = bt.run(
            d.loc[:test_idx[-1]], nifty=nifty, sector=sector, peer=peer,
            sector_symbol=sector_symbol, sector_name=sector_name,
            signal_start=test_idx[0], signal_end=test_idx[-1],
            data_limitations=data_limitations,
        )
        windows.append(window); results.append(result)
        metric = calculate_metrics(result, nifty, bootstrap_samples=300)
        wm.append({"window": number, "test_start": window.test_start,
                   "test_end": window.test_end, **metric})

    # Chain disjoint unseen windows into one OOS equity path.
    capital = bc.initial_capital
    curves = []
    all_trades, all_fills, all_events = [], [], []
    for result in results:
        if len(result.equity_curve):
            scaled = result.equity_curve.copy()
            scaled["equity"] = scaled["equity"] / result.initial_capital * capital
            capital = float(scaled["equity"].iloc[-1])
            curves.append(scaled)
        all_trades.extend(result.trades); all_fills.extend(result.fills); all_events.extend(result.events)
    curve = pd.concat(curves).sort_index() if curves else pd.DataFrame(columns=["equity", "exposed", "close"])
    aggregate = BacktestResult(
        bc.initial_capital, capital, all_trades, all_fills, all_events, curve,
        bc, cc, list(data_limitations or []),
    )
    metrics = calculate_metrics(aggregate, nifty)
    gate = acceptance_gate(metrics, len(windows), stock_count=stock_count, config=acceptance_config)
    methodology = {
        "mode": "expanding" if wc.expanding else "rolling",
        "parameter_selection": "none; fixed interpretable v1 parameters",
        "test_reporting": "unseen test windows only",
        "embargo_sessions": wc.embargo_sessions,
        "purging": "No forward labels are used. Embargo still separates train/validation/test boundaries.",
        "execution": "signal after close; earliest fill next tradable session; adverse same-bar policy",
        "parameter_hash": phash,
    }
    return WalkForwardResult(windows, wm, aggregate, metrics, gate, methodology)
