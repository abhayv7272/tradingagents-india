from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

from indiaagents.data import fundamentals, macro, market, news, social, sources
from indiaagents.data.health import SourceResult, health


def _history(n: int = 320, end: str = "2026-09-28") -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=n)
    close = pd.Series(range(n), index=index, dtype=float) / 10 + 100
    return pd.DataFrame({
        "Open": close - 0.2,
        "High": close + 1,
        "Low": close - 1,
        "Close": close,
        "Volume": 1_000_000.0,
    }, index=index)


def test_market_transport_exception_reaches_alpha_fallback() -> None:
    fake = MagicMock()
    fake.history.side_effect = requests.exceptions.SSLError("blocked")
    fake.info = {}
    alpha = _history()
    with patch.object(market.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_alpha_vantage_history", return_value=alpha):
        result = market.get_market_data("XYZ.NS", "2026-09-28")
    assert result["data_source"] == "alphavantage"
    states = {(item["source"], item["category"]): item["status"]
              for item in result["source_health"]}
    assert states[("yahoo", "ohlcv-primary")] == "network-blocked"
    assert states[("alpha-vantage", "selected-ohlcv")] == "available"


def test_market_all_provider_failure_is_safe_and_explicit() -> None:
    fake = MagicMock()
    fake.history.side_effect = requests.exceptions.SSLError("blocked")
    with patch.object(market.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_alpha_vantage_history", return_value=None), \
         pytest.raises(ValueError, match=r"yahoo=network-blocked.*alpha-vantage=empty"):
        market.get_market_data("XYZ.NS", "2026-09-28")


def test_fundamentals_all_yahoo_properties_are_independently_graceful() -> None:
    class BrokenTicker:
        @property
        def income_stmt(self):
            raise requests.exceptions.SSLError("blocked")

        @property
        def balance_sheet(self):
            raise requests.exceptions.SSLError("blocked")

        @property
        def cashflow(self):
            raise requests.exceptions.SSLError("blocked")

        @property
        def info(self):
            raise requests.exceptions.SSLError("blocked")

    with patch.object(fundamentals.yf, "Ticker", return_value=BrokenTicker()), \
         patch.object(sources, "get_screener_fundamentals", return_value=None):
        result = fundamentals.get_fundamentals_data("XYZ.NS", "2026-09-28")
    assert "FUNDAMENTAL DATA" in result["fundamentals_block"]
    yahoo = [item for item in result["source_health"] if item["source"] == "yahoo"]
    assert len(yahoo) == 4
    assert {item["status"] for item in yahoo} == {"network-blocked"}


def test_alpha_rate_limit_and_missing_key_are_distinct() -> None:
    with patch.dict(sources.os.environ, {}, clear=False):
        sources.os.environ.pop("ALPHA_VANTAGE_API_KEY", None)
        missing = sources.get_alpha_vantage_quote("XYZ.NS", with_health=True)
    assert missing.health.status == "unconfigured"

    with patch.dict(sources.os.environ, {"ALPHA_VANTAGE_API_KEY": "not-printed"}), \
         patch.object(sources, "_cached_get",
                      return_value=b'{"Note":"API call frequency exceeded"}'):
        limited = sources.get_alpha_vantage_history("XYZ.NS", with_health=True)
    assert limited.health.status == "rate-limited"
    assert "not-printed" not in limited.health.detail


def test_screener_http_rate_limit_not_reported_as_empty() -> None:
    with patch.object(sources, "_cached_get", side_effect=sources.HTTPFetchError(429)):
        result = sources.get_screener_fundamentals("XYZ.NS", with_health=True)
    assert result.value is None
    assert result.health.status == "rate-limited"


def _rss(items: list[tuple[str, str]]) -> bytes:
    body = "".join(
        f"<item><title>{title}</title><source>Fixture</source>"
        f"<pubDate>{published}</pubDate><link>https://example.test</link></item>"
        for title, published in items
    )
    return f"<rss><channel>{body}</channel></rss>".encode()


def test_google_news_historical_window_drops_future_and_unknown_dates() -> None:
    fixture = _rss([
        ("In window", "Mon, 28 Sep 2026 10:00:00 GMT"),
        ("IST next-day leak", "Mon, 28 Sep 2026 20:00:00 GMT"),
        ("Future leak", "Wed, 30 Sep 2026 10:00:00 GMT"),
        ("No date", "invalid"),
    ])
    with patch.object(news, "_cached_get", return_value=fixture):
        result = news.get_company_news("XYZ Limited", "XYZ.NS", 10, "2026-09-28")
    assert [item["title"] for item in result["items"]] == ["In window"]
    assert result["source_health"][0]["status"] == "available"


def test_google_news_network_and_parse_failures_are_distinct() -> None:
    with patch.object(news, "_cached_get", side_effect=requests.exceptions.SSLError("blocked")):
        blocked = news._fetch_rss("x")
    assert blocked.source_health.status == "network-blocked"
    with patch.object(news, "_cached_get", return_value=b"not xml"):
        malformed = news._fetch_rss("x")
    assert malformed.source_health.status == "parse-failed"


def test_social_historical_filter_rejects_posts_after_analysis_date() -> None:
    atom = """<feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>XYZ stock before</title><updated>2026-09-28T10:00:00Z</updated>
        <link href="https://reddit.test/1"/></entry>
      <entry><title>XYZ stock future</title><updated>2026-09-30T10:00:00Z</updated>
        <link href="https://reddit.test/2"/></entry>
    </feed>"""

    def fake_fetch(url: str):
        if "reddit.com" in url:
            return atom
        return ""

    with patch.object(social, "_fetch", side_effect=fake_fetch):
        result = social.get_social_chatter("XYZ Limited", "XYZ.NS", "2026-09-28")
    assert result["count"] == 1
    assert "before" in result["social_block"]
    assert "future" not in result["social_block"]


def test_fred_unconfigured_and_rate_limited_are_structured() -> None:
    with patch.dict(macro.os.environ, {}, clear=False):
        macro.os.environ.pop("FRED_API_KEY", None)
        missing = macro.get_fred_global_macro("2026-09-28")
    assert missing["source_health"][0]["status"] == "unconfigured"

    response = MagicMock(status_code=429)
    with patch.dict(macro.os.environ, {"FRED_API_KEY": "secret"}), \
         patch.object(macro.requests, "get", return_value=response):
        limited = macro.get_fred_global_macro("2026-09-28")
    assert limited["source_health"][0]["status"] == "rate-limited"
    assert all("secret" not in item["detail"] for item in limited["source_health"])


def test_market_context_reuses_nifty_snapshot_without_duplicate_fetch() -> None:
    value = {"last": 100.0, "d1": 1.0, "m1": 2.0,
             "from_high": -1.0, "from_low": 20.0}

    def fake(symbol: str, trade_date: str | None = None):
        del trade_date
        return SourceResult(value, health(
            "yahoo", f"market-context:{symbol}", "available", rows=252,
            as_of="2026-09-28",
        ))

    with patch.object(macro, "_snap_result", side_effect=fake) as snap:
        result = macro.get_market_context("2026-09-28")
    assert snap.call_count == 6
    assert result["nifty"] == value
    assert result["source_health"][0]["status"] == "available"


def test_http_cache_reports_hits_and_never_serves_expired_as_fresh(tmp_path) -> None:
    response = MagicMock(status_code=200, content=b"fixture")
    with patch.object(sources, "CACHE_DIR", tmp_path), \
         patch.object(sources.requests, "get", return_value=response) as get:
        first = sources._cached_get("https://example.test/data", ttl_hours=1)
        second = sources._cached_get("https://example.test/data", ttl_hours=1)
    assert bytes(first) == bytes(second) == b"fixture"
    assert first.cached is False and second.cached is True
    assert get.call_count == 1

    cache_file = next(tmp_path.glob("*.cache"))
    cache_file.touch()
    with patch.object(sources, "CACHE_DIR", tmp_path), \
         patch.object(sources.time, "time", return_value=cache_file.stat().st_mtime + 7200), \
         patch.object(sources.requests, "get",
                      side_effect=requests.exceptions.SSLError("blocked")), \
         pytest.raises(requests.exceptions.SSLError):
        sources._cached_get("https://example.test/data", ttl_hours=1)


def test_parser_rejects_impossible_alpha_ohlc_and_nse_nan() -> None:
    bad_history = {"Time Series (Daily)": {
        "2026-09-28": {"1. open": "100", "2. high": "90", "3. low": "95",
                       "4. close": "98", "5. volume": "10"},
    }}
    assert sources.parse_av_history(bad_history) is None
    assert sources.parse_nse_quote({"priceInfo": {"lastPrice": "nan"}}) is None


def test_daily_bar_normalization_preserves_india_session_date() -> None:
    from indiaagents.strategy.features import normalize_ohlcv

    frame = _history(2)
    frame.index = frame.index.tz_localize("Asia/Kolkata")
    normalized = normalize_ohlcv(frame)
    assert list(normalized.index.date) == list(frame.index.date)
    assert normalized.index.tz is None


def test_rss_parser_keeps_timezone_aware_publication_time() -> None:
    parsed = news.parse_google_news_rss(_rss([
        ("Headline", "Mon, 28 Sep 2026 10:00:00 GMT"),
    ]))
    assert parsed[0]["date"] == datetime(2026, 9, 28, 10, tzinfo=UTC)
