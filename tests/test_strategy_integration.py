"""Offline schema, source-abstraction and reporting compatibility tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch
import pandas as pd

from indiaagents.data.adapters import YahooOHLCVSource
from indiaagents.pipeline import _lock_deterministic_decision
from indiaagents.report import build_html, build_markdown
from indiaagents.strategy import PortfolioInputs


def deterministic_dict() -> dict:
    return {
        "as_of": "2026-01-01", "action": "WAIT", "legacy_action": "HOLD",
        "setup_name": "Weekly-trend breakout", "signal_state": "WAITING",
        "trigger": "Daily close above ₹105 with volume >=1.5x", "trigger_price": 105,
        "entry_zone": {"low": 105.5, "high": 106.5, "kind": "entry", "touches": 1,
                       "last_touch": None, "source": "trigger"},
        "confirmations": ["weekly trend"], "missing_confirmations": ["volume"],
        "invalidation": "close below support", "initial_stop": 99.0,
        "stop_reason": "confirmed pivot minus ATR", "target_1": 114.0, "target_2": 121.5,
        "reward_risk": 2.3, "quantity": 7, "allocation_rupees": 745.5,
        "allocation_pct": 0.75, "max_loss_rupees": 52.5,
        "max_portfolio_loss_pct": 0.053, "trailing_rule": "highest close minus 2 ATR",
        "early_exit_rules": ["failed breakout"], "time_stop_sessions": 30,
        "support_zones": [{"low": 98, "high": 100, "kind": "support", "touches": 2,
                           "last_touch": "2025-12-01", "source": "confirmed_pivot"}],
        "resistance_zones": [{"low": 114, "high": 115, "kind": "resistance", "touches": 2,
                              "last_touch": "2025-12-10", "source": "confirmed_pivot"}],
        "relative_strength": {"sector": {"status": "unavailable"}},
        "weekly": {"trend_state": "positive"}, "daily": {"atr14": 3.0},
        "deterministic_reasons": ["setup incomplete"],
        "limitations": ["survivorship bias unresolved"],
        "evidence": {"status": "NO VALIDATED EDGE", "validated_edge": False,
                     "trades": 12, "walk_forward_windows": 2},
        "config_version": "deterministic-v1",
    }


def base_result() -> dict:
    return {
        "ticker": "TEST.NS", "name": "Test", "exchange": "NSE", "trade_date": "2026-01-01",
        "price": 100.0, "snapshot": {"sector": "Technology", "industry": "IT", "rsi": 50,
            "ret_1m": 1, "ret_1y": 5, "from_52w_high": -10, "from_52w_low": 20},
        "decision": {"decision": "HOLD", "detailed_action": "WAIT", "rating": "Wait",
                     "confidence": 80, "entry_zone": "₹105.50–₹106.50", "target": "T1/T2",
                     "stop_loss": "₹99", "position_size_pct": 0, "timeframe": "positional",
                     "rationale": "code", "key_risks": [], "battle_notes": "locked",
                     "trade_validation": {"rr": 2.3}},
        "ai_decision": {"decision": "BUY", "confidence": 99, "rationale": "AI prose",
                        "key_risks": ["event"], "battle_notes": "AI note"},
        "deterministic": deterministic_dict(), "backtest": None,
        "analyst_reports": {}, "debate": "", "draft_verdict": "", "battle_critiques": "",
        "final_research": "", "trader_plan": "", "risk_views": "", "memory": "",
        "quant": {}, "data_quality": {"score": 70, "level": "MEDIUM", "issues": []},
        "data_sources": {"text": "fixture", "data_quality": ""}, "next_results": None,
        "market_context_block": "", "indicator_block": "", "fundamentals_block": "",
        "news_block": "", "macro_news_block": "", "fred_block": "", "social_block": "",
        "stats": {}, "mock": True,
    }


def test_deterministic_lock_overrides_llm_economics_but_preserves_commentary_metadata() -> None:
    ai = {"decision": "BUY", "confidence": 99, "entry_zone": "random", "target": "moon",
          "stop_loss": "none", "position_size_pct": 90, "rationale": "AI", "battle_notes": "AI"}
    out = _lock_deterministic_decision(ai, deterministic_dict(), PortfolioInputs().validated())
    assert out["decision"] == "HOLD" and out["detailed_action"] == "WAIT"
    assert out["entry_zone"] == "₹105.50–₹106.50"
    assert out["stop_loss"] == "₹99.00" and out["quantity"] == 7
    assert out["ai_proposed_decision"] == "BUY" and out["ai_confidence"] == 99
    assert "DETERMINISTIC LOCK" in out["battle_notes"]


def test_reports_make_deterministic_action_primary_and_backtest_absence_explicit() -> None:
    result = base_result()
    md = build_markdown(result)
    html = build_html(result)
    for text in ("Deterministic Code Authority", "WAIT", "BACKTEST NOT AVAILABLE",
                 "NO VALIDATED EDGE", "LLM", "Support zones"):
        assert text in md
    assert "Current Deterministic Setup" in html
    assert "Historical Evidence" in html
    assert "Separate AI Commentary" in html
    assert "AI prose confidence is not used as strategy confidence" in html


def test_yahoo_adapter_discloses_adjusted_vintage_and_survivorship_limits() -> None:
    idx = pd.bdate_range("2025-01-01", periods=5)
    raw = pd.DataFrame({"Open": 100, "High": 101, "Low": 99,
                        "Close": 100, "Volume": 1000}, index=idx)
    fake = MagicMock()
    fake.history.return_value = raw
    with patch("indiaagents.data.adapters.yf.Ticker", return_value=fake):
        out = YahooOHLCVSource().fetch("TEST.NS", "2025-01-01", "2025-01-10", adjusted=True)
    assert out.provenance.adjusted is True
    joined = " ".join(out.provenance.limitations).lower()
    assert "current adjusted-history vintage" in joined
    assert "survivorship" in joined and "delistings" in joined
    fake.history.assert_called_once()
