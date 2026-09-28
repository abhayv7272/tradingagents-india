"""Offline regression tests for bugs found in the September 2026 deep audit."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indiaagents.config import Settings
from indiaagents.data import macro, news
from indiaagents.data.fundamentals import _asof_statement, _first_valid
from indiaagents.data.market import resolve_ticker
from indiaagents.data.quant import REGIME_BANDS, ml_score
from indiaagents.report import _md


def _ohlcv(rows: int = 320) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, rows)))
    return pd.DataFrame(
        {
            "Open": close * 0.998,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": rng.integers(100_000, 1_000_000, rows),
        },
        index=pd.date_range("2024-01-01", periods=rows, freq="B"),
    )


def test_bundled_model_loads_with_pinned_sklearn() -> None:
    score = ml_score(_ohlcv())
    assert score is not None
    assert 0 <= score["score"] <= 100


def test_position_bands_are_total_portfolio_safe() -> None:
    assert REGIME_BANDS["confirmed_uptrend"][:2] == (10, 20)
    assert max(hi for _, hi, _ in REGIME_BANDS.values()) <= 20
    assert REGIME_BANDS["confirmed_downtrend"][:2] == (0, 0)


def test_settings_validate_untrusted_environment_values() -> None:
    s = Settings(battle_mode="wat", debate_rounds=999, risk_rounds=-2,
                 report_language="klingon", selected_analysts=("bogus",)).validate()
    assert s.battle_mode == "auto"
    assert s.debate_rounds == 3 and s.risk_rounds == 1
    assert s.report_language == "hinglish"
    assert s.selected_analysts == ("market", "fundamentals")


def test_known_ticker_resolves_during_yahoo_outage() -> None:
    with patch("indiaagents.data.market._validate", return_value=None):
        assert resolve_ticker("SBIN")["ticker"] == "SBIN.NS"
        assert resolve_ticker("RELIANCE.BO")["exchange"] == "BSE"


def test_historical_macro_news_uses_asof_window() -> None:
    calls = []

    def fake_fetch(query, when="7d", limit=10, after=None, before=None):
        calls.append((after, before))
        return []

    with patch.object(news, "_fetch_rss", side_effect=fake_fetch):
        news.get_india_macro_news(limit=3, trade_date="2025-01-15")
    assert calls
    assert all(pair == ("2025-01-05", "2025-01-16") for pair in calls)


def test_fred_historical_request_is_bounded() -> None:
    response = MagicMock(status_code=200)
    response.json.return_value = {"observations": [{"date": "2025-01-14", "value": "1"}]}
    with patch.dict("os.environ", {"FRED_API_KEY": "test"}), \
         patch.object(macro.requests, "get", return_value=response) as get:
        macro.get_fred_global_macro("2025-01-15")
    assert get.call_count == len(macro.FRED_SERIES)
    assert all(c.kwargs["params"]["observation_end"] == "2025-01-15"
               for c in get.call_args_list)


def test_fundamental_helpers_drop_future_period_and_nan() -> None:
    stmt = pd.DataFrame(
        {pd.Timestamp("2024-03-31"): [1], pd.Timestamp("2026-03-31"): [2]},
        index=["Revenue"],
    )
    out = _asof_statement(stmt, "2025-01-01")
    assert list(out.columns) == [pd.Timestamp("2024-03-31")]
    assert _first_valid(float("nan"), None, 7.0) == 7.0


def test_markdown_renderer_neutralizes_unsafe_url_schemes() -> None:
    rendered = _md("[click](javascript:alert(1)) <script>alert(2)</script>")
    assert "javascript:" not in rendered
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
