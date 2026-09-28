"""Offline event-driven execution, cost and walk-forward tests."""
from __future__ import annotations

from itertools import pairwise

import pandas as pd

from indiaagents.backtest import (
    BacktestConfig,
    EventDrivenBacktester,
    IndiaCostConfig,
    acceptance_gate,
    walk_forward_splits,
)
from indiaagents.backtest.costs import execution_price, transaction_cost
from indiaagents.strategy import (
    DetailedAction,
    DeterministicPlan,
    PortfolioInputs,
    PriceZone,
    SignalState,
    StrategyEvidence,
)


def bars(overrides: dict[int, tuple[float, float, float, float]] | None = None,
         rows: int = 10) -> pd.DataFrame:
    idx = pd.bdate_range("2026-01-01", periods=rows)
    data = pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1_000_000.0}, index=idx)
    for i, values in (overrides or {}).items():
        data.iloc[i, :4] = values
    return data


def plan(active: bool, holding: bool = False, *, t1: float = 105, t2: float = 110,
         stop: float = 95, quantity: int = 10, atr: float = 2,
         time_stop: int = 30) -> DeterministicPlan:
    action = DetailedAction.HOLD if holding else (DetailedAction.ENTER if active else DetailedAction.WAIT)
    return DeterministicPlan(
        as_of="2026-01-01", action=action,
        legacy_action="BUY" if active and not holding else "HOLD",
        setup_name="Fixture setup", signal_state=SignalState.ACTIVE if active else SignalState.WAITING,
        trigger="fixture close trigger", trigger_price=100,
        entry_zone=PriceZone(100, 102, "entry"), confirmations=["fixture"],
        missing_confirmations=[], invalidation="below 95", initial_stop=stop,
        stop_reason="fixture structure", target_1=t1, target_2=t2,
        reward_risk=(t2 - 102) / (102 - stop), quantity=quantity,
        allocation_rupees=quantity * 102, allocation_pct=10,
        max_loss_rupees=quantity * (102 - stop), max_portfolio_loss_pct=0.07,
        trailing_rule="highest close minus 2 ATR", early_exit_rules=[],
        time_stop_sessions=time_stop, relative_strength={}, weekly={"trend_state": "positive"},
        daily={"atr14": atr}, deterministic_reasons=[], limitations=[],
        evidence=StrategyEvidence(status="fixture", validated_edge=True),
    )


def provider_for(signal_date: pd.Timestamp, **kwargs):
    def provider(dt: pd.Timestamp, portfolio: PortfolioInputs) -> DeterministicPlan:
        return plan(dt == signal_date and not portfolio.existing_holding,
                    holding=portfolio.existing_holding, **kwargs)
    return provider


def run_fixture(data: pd.DataFrame, provider, policy: str = "adverse"):
    config = BacktestConfig(initial_capital=100_000, minimum_warmup=3,
                            same_bar_policy=policy, force_liquidate_at_end=True)
    return EventDrivenBacktester(backtest_config=config).run(
        data, signal_start=data.index[3], signal_provider=provider,
    )


def test_signal_after_close_executes_next_session_not_same_bar() -> None:
    data = bars()
    result = run_fixture(data, provider_for(data.index[3], t1=200, t2=300))
    buy = next(f for f in result.fills if f.side == "BUY")
    assert buy.date == data.index[4].date().isoformat()
    assert buy.reason == "NEXT_SESSION_ENTRY"


def test_gap_through_stop_fills_at_adverse_open() -> None:
    data = bars({5: (90, 92, 88, 89)})
    result = run_fixture(data, provider_for(data.index[3], t1=200, t2=300))
    trade = result.trades[0]
    sell = next(f for f in result.fills if f.side == "SELL")
    assert trade.gap_loss and trade.stop_hit
    assert trade.exit_reason == "GAP_THROUGH_STOP"
    assert sell.raw_price == 90  # never grants the stale ₹95 stop fill


def test_same_bar_stop_and_target_uses_adverse_ordering() -> None:
    data = bars({5: (100, 112, 94, 104)})
    result = run_fixture(data, provider_for(data.index[3], atr=10))
    trade = result.trades[0]
    assert trade.exit_reason == "STOP_LOSS"
    assert not any(f.reason.startswith("TARGET") for f in result.fills)


def test_partial_t1_then_t2_records_each_fill() -> None:
    data = bars({5: (101, 106, 100.5, 104), 6: (106, 112, 101, 110)})
    result = run_fixture(data, provider_for(data.index[3]))
    reasons = [f.reason for f in result.fills]
    assert "TARGET_1_PARTIAL" in reasons and "TARGET_2" in reasons
    t1 = next(f for f in result.fills if f.reason == "TARGET_1_PARTIAL")
    assert 0 < t1.quantity < 10
    assert result.trades[0].average_exit_price > 105


def test_trailing_stop_uses_prior_close_update() -> None:
    data = bars({4: (100, 105, 99, 104), 5: (104, 111, 101, 110),
                 6: (108, 109, 105, 106)})
    result = run_fixture(data, provider_for(data.index[3], t1=200, t2=300, atr=2))
    assert result.trades[0].exit_reason == "TRAILING_STOP"
    sell = next(f for f in result.fills if f.reason == "TRAILING_STOP")
    assert sell.raw_price == 106  # highest prior close 110 - 2*ATR


def test_time_stop_executes_at_next_session_open_and_cash_reconciles() -> None:
    data = bars({4: (100, 101, 99, 100), 5: (101, 102, 99, 101),
                 6: (103, 104, 102, 103)})
    result = run_fixture(
        data, provider_for(data.index[3], t1=200, t2=300, atr=10, time_stop=2)
    )
    trade = result.trades[0]
    assert trade.exit_reason == "TIME_STOP"
    assert trade.exit_date == data.index[6].date().isoformat()
    assert abs(result.final_equity - (result.initial_capital + sum(t.net_pnl for t in result.trades))) < 1e-6


def test_execution_sizing_includes_entry_slippage_in_risk_budget() -> None:
    data = bars({4: (100, 101, 99.5, 100)})
    cfg = BacktestConfig(initial_capital=100_000, max_risk_pct=1,
                         max_single_stock_pct=100, minimum_warmup=3)
    result = EventDrivenBacktester(backtest_config=cfg).run(
        data, signal_start=data.index[3],
        signal_provider=provider_for(data.index[3], stop=99, quantity=1000,
                                     t1=200, t2=300, atr=10),
    )
    buy = next(f for f in result.fills if f.side == "BUY")
    assert (buy.price - 99) * buy.quantity <= 1000


def test_transaction_costs_and_slippage_are_directional_and_net() -> None:
    cfg = IndiaCostConfig(slippage_bps=5, impact_bps=2)
    buy, buy_slip = execution_price(100, "BUY", cfg)
    sell, sell_slip = execution_price(100, "SELL", cfg)
    assert buy > 100 > sell and abs(buy_slip - sell_slip) < 1e-12
    buy_cost = transaction_cost(buy, 10, "BUY", cfg, buy_slip * 10)
    sell_cost = transaction_cost(sell, 10, "SELL", cfg, sell_slip * 10)
    assert buy_cost.stamp > 0 and sell_cost.stamp == 0
    assert buy_cost.stt > 0 and sell_cost.stt > 0
    assert buy_cost.economic_cost > buy_cost.cash_charges


def test_walk_forward_boundaries_do_not_overlap_and_honor_embargo() -> None:
    idx = pd.bdate_range("2018-01-01", periods=1200)
    from indiaagents.backtest import WalkForwardConfig
    cfg = WalkForwardConfig(train_sessions=500, validation_sessions=100,
                            test_sessions=100, step_sessions=100, embargo_sessions=7)
    splits = walk_forward_splits(idx, cfg)
    assert len(splits) >= 3
    for train, val, test in splits:
        assert train.stop + 7 == val.start
        assert val.stop + 7 == test.start
        assert train.stop <= val.start < val.stop <= test.start < test.stop
    for a, b in pairwise(splits):
        assert a[2].stop <= b[2].start


def test_walk_forward_rejects_overlapping_unseen_windows() -> None:
    import pytest

    from indiaagents.backtest import WalkForwardConfig
    idx = pd.bdate_range("2018-01-01", periods=1200)
    cfg = WalkForwardConfig(train_sessions=500, validation_sessions=100,
                            test_sessions=120, step_sessions=60, embargo_sessions=5)
    with pytest.raises(ValueError, match="overlapping unseen windows"):
        walk_forward_splits(idx, cfg)


def test_drawdown_is_reported_as_positive_loss_magnitude() -> None:
    from indiaagents.backtest.execution import BacktestResult
    from indiaagents.backtest.metrics import calculate_metrics
    curve = pd.DataFrame(
        {"equity": [100_000, 90_000, 95_000], "exposed": [False, True, True],
         "close": [100, 90, 95]},
        index=pd.bdate_range("2026-01-01", periods=3),
    )
    result = BacktestResult(100_000, 95_000, [], [], [], curve,
                            BacktestConfig(), IndiaCostConfig())
    assert calculate_metrics(result)["max_drawdown_pct"] == 10.0


def test_acceptance_gate_requires_sample_windows_edge_and_diversity() -> None:
    metrics = {
        "trades": 60, "expectancy_r": 0.2, "profit_factor": 1.3,
        "max_drawdown_pct": -12,
        "regime_performance": {"positive": {"trades": 30}, "neutral": {"trades": 30}},
    }
    passed = acceptance_gate(
        metrics, 3, stock_count=3,
        stock_trade_counts={"A": 20, "B": 20, "C": 20},
    )
    assert passed["validated_edge"] and passed["status"] == "VALIDATED EDGE"
    single = acceptance_gate(metrics, 3, stock_count=1)
    assert not single["validated_edge"]
    assert not single["checks"]["stock_diversity"]
    concentrated = acceptance_gate(
        metrics, 3, stock_count=3,
        stock_trade_counts={"A": 50, "B": 5, "C": 5},
    )
    assert not concentrated["checks"]["stock_concentration"]
    weak = dict(metrics, trades=49, expectancy_r=-0.01, profit_factor=1.19)
    failed = acceptance_gate(weak, 2, stock_count=3)
    assert failed["status"] == "NO VALIDATED EDGE"
    assert {"minimum_oos_trades", "minimum_test_windows", "positive_net_expectancy", "profit_factor"} <= {
        x.replace(" ", "_") for x in failed["failed_reasons"]
    }
