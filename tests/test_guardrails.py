"""Offline tests for deterministic evidence and execution guardrails."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indiaagents.data.fundamentals import get_fundamentals_data
from indiaagents.validation import (
    apply_quality_guard,
    apply_trade_guard,
    assess_data_quality,
)


def _decision(**updates):
    d = {
        "decision": "BUY", "rating": "Buy", "confidence": 80,
        "position_size_pct": 20, "entry_zone": "₹100-₹102",
        "target": "₹120", "stop_loss": "₹95", "battle_notes": "base",
    }
    d.update(updates)
    return d


def test_trade_guard_verifies_rr_and_caps_capital_at_risk():
    d = apply_trade_guard(_decision(), 101)
    assert d["decision"] == "BUY"
    assert d["trade_validation"]["verified"] is True
    assert d["trade_validation"]["rr"] == 3.17
    # 5.94% stop distance and 1% capital risk => max 16% allocation.
    assert d["position_size_pct"] == 16
    assert "capital-at-risk cap" in d["battle_notes"]


def test_trade_guard_rejects_bad_rr_and_level_direction():
    poor = apply_trade_guard(_decision(target="₹108", stop_loss="₹95"), 101)
    assert poor["decision"] == "HOLD" and poor["position_size_pct"] == 0
    assert poor["confidence"] <= 45
    inverted = apply_trade_guard(_decision(target="₹90", stop_loss="₹110"), 101)
    assert inverted["decision"] == "HOLD"


def test_trade_guard_caps_unverified_plan_and_locks_sell_allocation():
    vague = apply_trade_guard(_decision(entry_zone="near current", target="8-12% upside",
                                        stop_loss="6% below", position_size_pct=15), 100)
    assert vague["decision"] == "BUY"
    assert vague["position_size_pct"] == 5 and vague["confidence"] == 60
    assert vague["trade_validation"]["verified"] is False
    sell = apply_trade_guard(_decision(decision="SELL", rating="Reduce"), 100)
    assert sell["position_size_pct"] == 0


def _quality_inputs(rows=300, sources=("yfinance", "NSE"), mismatch=""):
    df = pd.DataFrame({"Close": range(rows)})
    market = {
        "df": df, "snapshot": {"date": "2026-09-28"},
        "price_sources": list(sources), "data_quality": mismatch,
    }
    fundamentals = {
        "key": {k: 1 for k in ("revenue", "net_income", "market_cap", "pe", "pb", "roe", "fcf")},
        "screener": {"pe": 10},
    }
    news = {"items": [{}] * 6}
    macro_news = {"items": [{}]}
    social = {"source": "reddit-search", "count": 2}
    market_context = {"nifty": {"last": 1}}
    fred = {"fred_block": "GLOBAL MACRO: all four series present"}
    return dict(trade_date="2026-09-28", market=market, fundamentals=fundamentals,
                news=news, macro_news=macro_news, social=social,
                market_context=market_context, fred=fred)


def test_quality_score_high_and_hard_block_paths():
    high = assess_data_quality(**_quality_inputs())
    assert high["score"] == 100 and high["level"] == "HIGH" and not high["hard_block"]

    low_args = _quality_inputs(rows=50, sources=("yfinance",), mismatch="MISMATCH >2%")
    low_args["market"]["snapshot"]["date"] = "2026-08-01"
    low_args["fundamentals"] = {"key": {}, "screener": None}
    low_args["news"] = {"items": []}
    low_args["macro_news"] = {"items": []}
    low_args["social"] = {"source": "unavailable", "count": 0}
    low_args["market_context"] = {"nifty": None}
    low_args["fred"] = {"fred_block": "<unavailable>"}
    low = assess_data_quality(**low_args)
    assert low["hard_block"] and low["level"] == "CRITICAL"
    guarded = apply_quality_guard(_decision(), low)
    assert guarded["decision"] == "HOLD" and guarded["position_size_pct"] == 0
    assert guarded["confidence"] <= 35


def test_historical_fundamentals_suppress_current_ratios_and_screener():
    fake = MagicMock()
    fake.income_stmt = pd.DataFrame(
        {pd.Timestamp("2024-03-31"): [100.0, 10.0]},
        index=["Total Revenue", "Net Income"],
    )
    fake.balance_sheet = pd.DataFrame()
    fake.cashflow = pd.DataFrame()
    fake.info = {
        "shortName": "Leak Corp", "marketCap": 999999999,
        "trailingPE": 99, "priceToBook": 9, "sharesOutstanding": 1e8,
    }
    with patch("indiaagents.data.fundamentals.yf.Ticker", return_value=fake), \
         patch("indiaagents.data.sources.get_screener_fundamentals") as screener:
        out = get_fundamentals_data("LEAK.NS", "2025-01-01")
    assert out["key"]["market_cap"] is None and out["key"]["pe"] is None
    assert "Current quote ratios and Screener snapshot are SUPPRESSED" in out["fundamentals_block"]
    screener.assert_not_called()
