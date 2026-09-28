"""Offline deterministic feature/strategy tests (no network, no LLM)."""
from __future__ import annotations

from dataclasses import replace
import numpy as np
import pandas as pd

from indiaagents.strategy import (
    DeterministicStrategyEngine, PortfolioInputs, StrategyConfig, StrategyEvidence,
)
from indiaagents.strategy.features import completed_weekly_ohlcv, daily_features, weekly_features
from indiaagents.strategy.levels import build_level_context, confirmed_pivots
from indiaagents.strategy.relative_strength import relative_strength, sector_index_for


def trend_data(rows: int = 320, breakout: bool = False) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=rows)
    base = np.linspace(100, 150, rows)
    wave = np.sin(np.arange(rows) / 7) * 1.2
    close = base + wave
    volume = np.full(rows, 1_000_000.0)
    if breakout:
        close[-1] = max(close[-56:-1]) * 1.08
        volume[-1] = 2_000_000
    return pd.DataFrame({
        "Open": close * 0.997, "High": close * 1.006, "Low": close * 0.991,
        "Close": close, "Volume": volume,
    }, index=idx)


def test_weekly_resampling_excludes_partial_future_week() -> None:
    idx = pd.bdate_range("2026-01-05", periods=10)  # Mon 5th through Fri 16th
    close = np.arange(10, dtype=float) + 100
    df = pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                       "Close": close, "Volume": 1000}, index=idx)
    as_of = pd.Timestamp("2026-01-14")  # Wednesday
    weekly = completed_weekly_ohlcv(df, as_of)
    assert list(weekly.index) == [pd.Timestamp("2026-01-09")]
    assert weekly.iloc[-1]["Close"] == 104
    mutated = df.copy()
    mutated.loc[pd.Timestamp("2026-01-15"):, "Close"] = 9999
    pd.testing.assert_frame_equal(weekly_features(df, as_of), weekly_features(mutated, as_of))


def test_confirmed_pivot_is_unavailable_before_right_bar_closes() -> None:
    idx = pd.bdate_range("2026-01-01", periods=8)
    high = [10, 11, 12, 15, 12, 11, 10, 9]
    low = [8, 9, 10, 11, 10, 9, 8, 7]
    df = pd.DataFrame({"Open": 10, "High": high, "Low": low,
                       "Close": 10, "Volume": 1000}, index=idx)
    pivots = confirmed_pivots(df, left=2, right=2)
    peak = [p for p in pivots if p.pivot_date == idx[3] and p.kind == "high"][0]
    assert peak.confirmation_date == idx[5]
    before = build_level_context(df, idx[4], left=2, right=2, pivots=pivots)
    after = build_level_context(df, idx[5], left=2, right=2, pivots=pivots)
    assert all(p.pivot_date != idx[3] for p in before["pivots"])
    assert any(p.pivot_date == idx[3] for p in after["pivots"])


def test_breakout_levels_are_shifted_and_point_in_time() -> None:
    df = trend_data(80)
    f = daily_features(df)
    expected = float(df["High"].iloc[-56:-1].max())
    assert f.iloc[-1]["prior_high55"] == expected
    mutated = df.copy()
    mutated.iloc[-1, mutated.columns.get_loc("High")] = 1_000_000
    assert daily_features(mutated).iloc[-1]["prior_high55"] == expected


def test_relative_strength_periods_slope_and_unavailable_sector() -> None:
    idx = pd.bdate_range("2025-01-01", periods=150)
    stock = pd.DataFrame({"Open": 100, "High": 101, "Low": 99,
                          "Close": np.linspace(100, 160, 150), "Volume": 1000}, index=idx)
    nifty = stock.copy()
    nifty["Close"] = np.linspace(100, 120, 150)
    out = relative_strength(stock, nifty)
    assert out["nifty"]["1m_pct"] > 0
    assert out["nifty"]["3m_pct"] > 0
    assert out["nifty"]["6m_pct"] > 0
    assert out["nifty"]["trend"] == "positive"
    assert out["sector"]["status"] == "unavailable"
    assert sector_index_for("TCS.NS") == "^CNXIT"
    assert sector_index_for("UNKNOWN.NS", "unknown sector") is None


def test_active_breakout_has_deterministic_levels_directions_and_sizing() -> None:
    stock = trend_data(320, breakout=True)
    nifty = trend_data(320)
    # Make benchmark materially weaker, ensuring positive RS.
    cols = ["Open", "High", "Low", "Close"]
    nifty.loc[:, cols] = nifty[cols].mul(np.linspace(1, 0.8, len(nifty)), axis=0)
    engine = DeterministicStrategyEngine(StrategyConfig(require_validated_edge=False))
    plan = engine.analyze(
        stock, nifty=nifty, portfolio=PortfolioInputs(portfolio_capital=100_000),
        evidence=StrategyEvidence(status="test gate", validated_edge=True),
    )
    assert plan.signal_state.value == "ACTIVE"
    assert plan.setup_name == "Weekly-trend breakout"
    assert plan.action.value == "ENTER"
    assert plan.entry_zone is not None and plan.initial_stop is not None
    assert plan.initial_stop < plan.entry_zone.low <= plan.entry_zone.high
    assert plan.target_1 > plan.entry_zone.high and plan.target_2 > plan.target_1
    expected_rr = (plan.target_2 - plan.entry_zone.high) / (plan.entry_zone.high - plan.initial_stop)
    assert abs(plan.reward_risk - expected_rr) < 0.02
    assert isinstance(plan.quantity, int) and plan.quantity > 0
    assert plan.max_portfolio_loss_pct <= 1.0
    assert "volume" in plan.trigger.lower()


def test_acceptance_absence_blocks_fresh_entry_but_not_signal_measurement() -> None:
    stock = trend_data(320, breakout=True)
    nifty = trend_data(320)
    cols = ["Open", "High", "Low", "Close"]
    nifty.loc[:, cols] = nifty[cols].mul(np.linspace(1, 0.8, len(nifty)), axis=0)
    plan = DeterministicStrategyEngine().analyze(stock, nifty=nifty)
    assert plan.signal_state.value == "ACTIVE"
    assert plan.action.value == "WAIT"
    assert plan.evidence.status == "BACKTEST NOT AVAILABLE"


def test_fresh_wait_vs_existing_hold_and_stale_review() -> None:
    stock = trend_data(320, breakout=False)
    nifty = trend_data(320)
    engine = DeterministicStrategyEngine()
    fresh = engine.analyze(stock, nifty=nifty, portfolio=PortfolioInputs(existing_holding=False))
    holder = engine.analyze(stock, nifty=nifty,
                            portfolio=PortfolioInputs(existing_holding=True, current_quantity=10))
    assert fresh.action.value == "WAIT"
    assert holder.action.value in {"HOLD", "TRIM", "EXIT"}
    stale = engine.analyze(stock, as_of=stock.index[-1] + pd.Timedelta(days=10), nifty=nifty)
    assert stale.action.value == "REVIEW"


def test_imminent_known_results_event_forces_review() -> None:
    stock = trend_data(320, breakout=True)
    nifty = trend_data(320)
    event = (stock.index[-1] + pd.Timedelta(days=3)).date().isoformat()
    plan = DeterministicStrategyEngine().analyze(stock, nifty=nifty, event_date=event)
    assert plan.action.value == "REVIEW"
    assert any("results/event" in x for x in plan.limitations)


def test_repeated_output_is_byte_for_byte_deterministic() -> None:
    stock = trend_data(320, breakout=True)
    nifty = trend_data(320)
    engine = DeterministicStrategyEngine()
    a = engine.analyze(stock, nifty=nifty).to_dict()
    b = engine.analyze(stock.copy(), nifty=nifty.copy()).to_dict()
    assert a == b
