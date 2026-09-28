"""
🔌 MULTI-SOURCE DATA LAYER — parser/cross-check/fallback tests (no LLM, no network for unit tests)

Run:  python tests/test_sources.py
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS = []
NETWORK_WARN = []


def test(fn):
    RESULTS.append(fn)
    return fn


def net_test(fn):
    """Network-dependent test: connection issues -> WARN (not FAIL)."""
    def wrapper():
        try:
            return fn()
        except (ConnectionError, TimeoutError, OSError) as e:
            NETWORK_WARN.append((fn.__name__, str(e)[:80]))
            return "SKIP-NET"
    RESULTS.append(wrapper)
    wrapper.__name__ = fn.__name__
    return wrapper


# ======================================================================
# Fixtures (realistic HTML/JSON snippets — parsers offline testable)
# ======================================================================

SCREENER_FIXTURE = """<!DOCTYPE html><html><body>
<div class="company-ratios">
  <ul id="top-ratios">
    <li class="flex flex-space-between" data-source="default">
      <span class="name">Market Cap</span>
      <span class="nowrap value">₹ <span class="number">16,20,656</span> Cr.</span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">Current Price</span>
      <span class="nowrap value">₹ <span class="number">1,198</span></span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">High / Low</span>
      <span class="nowrap value">₹ <span class="number">1,612</span> / <span class="number">1,196</span></span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">Stock P/E</span>
      <span class="nowrap value"><span class="number">21.7</span></span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">Book Value</span>
      <span class="nowrap value">₹ <span class="number">668</span></span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">Dividend Yield</span>
      <span class="nowrap value"><span class="number">0.38</span> %</span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">ROCE</span>
      <span class="nowrap value"><span class="number">10.25</span> %</span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">ROE</span>
      <span class="nowrap value"><span class="number">8.91</span> %</span>
    </li>
    <li class="flex flex-space-between" data-source="default">
      <span class="name">Face Value</span>
      <span class="nowrap value">₹ <span class="number">10.00</span></span>
    </li>
  </ul>
</div>
<div class="company-profile"><p>Reliance Industries is engaged in refining, petrochemicals, oil and gas and retail businesses.</p></div>
</body></html>"""

NSE_FIXTURE = {
    "priceInfo": {
        "lastPrice": 2040.30, "previousClose": 2035.10, "vwap": 2038.55,
        "intraDayHighLow": {"max": 2051.00, "min": 2028.15},
        "week52High": 2118.80, "week52Low": 1490.00,
    },
    "tradeInfo": {"totalTradedVolume": 8123456},
    "metadata": {"lastUpdateTime": "28-SEP-2026 15:30:00"},
}

AV_QUOTE_FIXTURE = {
    "Global Quote": {
        "01. symbol": "RELIANCE.BSE", "05. price": "2041.0000",
        "03. high": "2050.0000", "04. low": "2027.0000",
        "06. volume": "8123456", "08. previous close": "2035.1000",
    }
}

AV_HISTORY_FIXTURE = {
    "Meta Data": {"1. Information": "Daily Prices"},
    "Time Series (Daily)": {
        "2026-09-25": {"1. open": "2030.0", "2. high": "2048.0", "3. low": "2025.0",
                       "4. close": "2040.5", "5. volume": "8000000"},
        "2026-09-26": {"1. open": "2041.0", "2. high": "2051.0", "3. low": "2033.0",
                       "4. close": "2044.2", "5. volume": "7500000"},
        "2026-09-24": {"1. open": "2025.0", "2. high": "2032.0", "3. low": "2020.0",
                       "4. close": "2029.1", "5. volume": "6900000"},
    },
}


# ======================================================================
# A. Unit parsing (pure, offline)
# ======================================================================

@test
def sources_module_imports():
    from indiaagents.data import sources
    for fn in ("get_screener_fundamentals", "get_nse_quote", "get_alpha_vantage_quote",
               "get_alpha_vantage_history", "cross_check_price", "parse_screener_html",
               "parse_nse_quote", "parse_av_quote", "parse_av_history", "screener_text_block"):
        assert callable(getattr(sources, fn)), f"missing: {fn}"


@test
def screener_parser_fixture():
    from indiaagents.data.sources import parse_screener_html
    out = parse_screener_html(SCREENER_FIXTURE)
    r = out["ratios"]
    assert r.get("market cap") == "₹ 16,20,656 Cr.", r
    assert r.get("stock p/e") == "21.7", r
    assert r.get("high / low") == "₹ 1,612 / 1,196", r  # dono numbers ek saath
    assert r.get("roce") == "10.25 %", r
    assert "Reliance Industries" in out["about"]


@test
def screener_parser_normalized_numeric_keys():
    from indiaagents.data.sources import _SCREENER_KEYS, _num
    assert _num("₹ 1,234.50 Cr") == 1234.50
    assert _num("1,600 / 1,100") == 1600.0
    assert _num("") is None and _num("abc") is None
    assert "stock p/e" in _SCREENER_KEYS and "roce" in _SCREENER_KEYS


@test
def screener_parser_garbage_html():
    from indiaagents.data.sources import parse_screener_html
    out = parse_screener_html("<html><body>nothing here</body></html>")
    assert out["ratios"] == {} and out["about"] == ""


@test
def screener_text_block_renders():
    from indiaagents.data.sources import screener_text_block, parse_screener_html
    parsed = parse_screener_html(SCREENER_FIXTURE)
    sc = {"ratios": parsed["ratios"], "about": parsed["about"],
          "url": "https://www.screener.in/company/TEST/"}
    block = screener_text_block(sc)
    assert "SCREENER.IN" in block and "Market Cap: ₹ 16,20,656 Cr." in block
    assert "Stock P/E: 21.7" in block and "screener.in/company/TEST" in block
    assert screener_text_block(None) == ""


@test
def nse_quote_parser_fixture():
    from indiaagents.data.sources import parse_nse_quote
    q = parse_nse_quote(NSE_FIXTURE)
    assert q["last"] == 2040.30 and q["prev_close"] == 2035.10
    assert q["day_high"] == 2051.00 and q["week_52_high"] == 2118.80
    assert q["volume"] == 8123456 and "15:30" in (q["updated"] or "")


@test
def nse_quote_parser_bad_inputs():
    from indiaagents.data.sources import parse_nse_quote
    assert parse_nse_quote({}) is None
    assert parse_nse_quote({"priceInfo": {}}) is None
    assert parse_nse_quote(None) is None


@test
def av_quote_parser_fixture():
    from indiaagents.data.sources import parse_av_quote
    q = parse_av_quote(AV_QUOTE_FIXTURE)
    assert q["price"] == 2041.0 and q["prev_close"] == 2035.1
    assert q["day_low"] == 2027.0 and q["volume"] == 8123456


@test
def av_quote_parser_note_only():
    from indiaagents.data.sources import parse_av_quote
    # rate-limit / bad-symbol responses me "Note"/empty hota hai
    assert parse_av_quote({"Note": "API call volume reached"}) is None
    assert parse_av_quote({"Global Quote": {}}) is None


@test
def av_history_parser_fixture_sorted_df():
    from indiaagents.data.sources import parse_av_history
    df = parse_av_history(AV_HISTORY_FIXTURE)
    assert df is not None and len(df) == 3
    assert list(df.index) == sorted(df.index), "dates ascending honi chahiye"
    assert float(df.iloc[-1]["Close"]) == 2044.2
    assert {"Open", "High", "Low", "Close", "Volume"} <= set(df.columns)
    assert parse_av_history({"Note": "limit"}) is None


# ======================================================================
# B. Cross-check logic
# ======================================================================

@test
def cross_check_ok_consensus():
    from indiaagents.data.sources import cross_check_price
    n, note = cross_check_price(2040.30, [("NSE", 2040.30), ("AlphaVantage", 2041.0)])
    assert n == 2 and "OK" in note and "NSE" in note and "AlphaVantage" in note


@test
def cross_check_mismatch_flagged():
    from indiaagents.data.sources import cross_check_price
    n, note = cross_check_price(2040.30, [("NSE", 2100.0)])  # +2.9%
    assert n == 1 and "MISMATCH" in note


@test
def cross_check_empty_inputs():
    from indiaagents.data.sources import cross_check_price
    assert cross_check_price(2040.0, []) == (0, "")
    assert cross_check_price(None, [("NSE", 100.0)]) == (0, "")
    assert cross_check_price(2040.0, [("NSE", None)]) == (0, "")


# ======================================================================
# C. Graceful degradation (network effectively blocked)
# ======================================================================

@test
def screener_fetch_graceful_none_on_http_fail():
    from indiaagents.data import sources
    with patch.object(sources, "_cached_get", side_effect=ValueError("HTTP 403")):
        assert sources.get_screener_fundamentals("XYZ.NS", "XYZ Corp") is None


@test
def nse_quote_skips_bse_and_fails_graceful():
    from indiaagents.data import sources
    assert sources.get_nse_quote("XYZ.BO") is None  # BSE symbol → try hi nahi
    with patch.object(sources.requests.Session, "get", side_effect=OSError("blocked")):
        assert sources.get_nse_quote("XYZ.NS") is None


@test
def av_without_key_returns_none():
    from indiaagents.data import sources
    with patch.dict(sources.os.environ, {}, clear=False):
        sources.os.environ.pop("ALPHA_VANTAGE_API_KEY", None)
        assert sources.get_alpha_vantage_quote("RELIANCE.NS") is None
        assert sources.get_alpha_vantage_history("RELIANCE.NS") is None


# ======================================================================
# D. market.py fallback wiring (mock yfinance; alpha-vantage injected)
# ======================================================================

def _synthetic_df(n: int):
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame({
        "Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000.0,
    }, index=idx)


@test
def market_fallback_when_yahoo_short():
    from indiaagents.data import market, sources

    long_df = _synthetic_df(400)
    short_df = _synthetic_df(120)  # BETA-jaisa case: yahoo sirf 120 rows deta hai

    fake = MagicMock()
    fake.history.return_value = short_df.copy()
    fake.info = {}
    with patch.object(market.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_alpha_vantage_history", return_value=long_df.copy()), \
         patch.object(sources, "get_nse_quote", return_value={"last": 100.5, "prev_close": 99.8}), \
         patch.object(sources, "get_alpha_vantage_quote", return_value=None):
        mkt = market.get_market_data("XYZ.NS", None)
    assert mkt["data_source"] == "alphavantage", f"fallback nahi laga: {mkt['data_source']}"
    assert len(mkt["df"]) >= 399, f"AV df use nahi hua: {len(mkt['df'])}"
    assert "ALPHAVANTAGE" in mkt["indicator_block"].upper()
    assert "NSE" in mkt["price_sources"]
    assert "cross-check" in mkt["data_quality"].lower() or mkt["data_quality"] == ""


@test
def market_no_fallback_when_yahoo_long():
    from indiaagents.data import market, sources

    good_df = _synthetic_df(320)  # 320 rows ≥ 260 → yahoo hi rakho
    fake = MagicMock()
    fake.history.return_value = good_df.copy()
    fake.info = {}
    with patch.object(market.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_alpha_vantage_history", return_value=_synthetic_df(400)) as av_spy, \
         patch.object(sources, "get_nse_quote", return_value=None), \
         patch.object(sources, "get_alpha_vantage_quote", return_value=None):
        mkt = market.get_market_data("XYZ.NS", None)
    assert mkt["data_source"] == "yahoo"
    assert len(mkt["df"]) == 320
    av_spy.assert_not_called(), "yahoo healthy hai to AV call hi nahi hona chahiye"


@test
def market_cross_check_note_attached():
    from indiaagents.data import market, sources
    fake = MagicMock()
    fake.history.return_value = _synthetic_df(300)
    fake.info = {}
    with patch.object(market.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_alpha_vantage_history", return_value=None), \
         patch.object(sources, "get_nse_quote", return_value={"last": 102.0}), \
         patch.object(sources, "get_alpha_vantage_quote", return_value={"price": 101.5}):
        mkt = market.get_market_data("XYZ.NS", None)
    assert "NSE" in mkt["data_quality"] and "AlphaVantage" in mkt["data_quality"]
    assert "OK" in mkt["data_quality"]  # ~2% se kam diff


# ======================================================================
# E. fundamentals.py screener wiring (mock yfinance + injected screener dict)
# ======================================================================

@test
def fundamentals_screener_block_appended():
    from indiaagents.data import fundamentals, sources
    fake = MagicMock()
    fake.income_stmt = pd.DataFrame()
    fake.balance_sheet = pd.DataFrame()
    fake.cashflow = pd.DataFrame()
    fake.info = {"shortName": "Reliance", "trailingPE": 24.51}
    sc = {"ratios": {"market cap": "₹ 16,20,656 Cr.", "stock p/e": "21.7", "roce": "10.25 %"},
          "about": "Refining & retail.", "url": "https://www.screener.in/company/RELIANCE/",
          "pe": 21.7, "roce": 10.25, "market_cap_cr": 1620656.0}
    with patch.object(fundamentals.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_screener_fundamentals", return_value=sc):
        out = fundamentals.get_fundamentals_data("RELIANCE.NS", None)
    assert "SCREENER.IN" in out["fundamentals_block"]
    assert "ROCE" in out["fundamentals_block"].upper()
    assert out["screener"] is not None
    assert "P/E cross-check" in out["screener_note"] or "CONFLICT" in out["screener_note"]


@test
def fundamentals_screener_fail_graceful():
    from indiaagents.data import fundamentals, sources
    fake = MagicMock()
    fake.income_stmt = pd.DataFrame()
    fake.balance_sheet = pd.DataFrame()
    fake.cashflow = pd.DataFrame()
    fake.info = {}
    with patch.object(fundamentals.yf, "Ticker", return_value=fake), \
         patch.object(sources, "get_screener_fundamentals", side_effect=Exception("boom")):
        out = fundamentals.get_fundamentals_data("XYZ.NS", None)  # crash nahi hona chahiye
    assert "SCREENER.IN" not in out["fundamentals_block"]
    assert out["screener"] is None and out["screener_note"] == ""


# ======================================================================
# F. Static / packaging checks
# ======================================================================

@test
def requirements_has_bs4():
    reqs = Path(__file__).resolve().parent.parent.joinpath("requirements.txt").read_text()
    assert "beautifulsoup4" in reqs, "requirements.txt me beautifulsoup4 add karo"


@test
def env_example_has_av_key():
    env = Path(__file__).resolve().parent.parent.joinpath(".env.example").read_text()
    assert "ALPHA_VANTAGE_API_KEY" in env


@test
def report_renders_data_sources_line():
    from indiaagents.report import build_markdown
    r = {"name": "X", "ticker": "X.NS", "exchange": "NSE", "trade_date": "2026-09-28",
         "price": 100.0, "snapshot": {}, "analyst_reports": {}, "debate": "", "draft_verdict": "",
         "battle_critiques": "", "final_research": "", "trader_plan": "", "risk_views": "",
         "decision": {"decision": "HOLD", "rating": "Hold", "confidence": 50}, "memory": "",
         "quant": None, "next_results": None, "news_block": "", "macro_news_block": "",
         "social_block": "", "indicator_block": "", "fundamentals_block": "",
         "market_context_block": "", "fred_block": "", "models": {}, "stats": {},
         "settings": {"report_language": "hinglish", "battle_mode": "off"}, "mock": False,
         "progress_events": [],
         "data_sources": {"text": "Yahoo ✓ | Screener.in ✓ | NSE quote ✓",
                          "price_sources": ["yfinance", "NSE"], "data_quality": "OK", "screener_note": ""}}
    md = build_markdown(r)
    assert "**🔌 Data sources:** Yahoo ✓ | Screener.in ✓ | NSE quote ✓" in md
    assert "· OK" in md  # data-quality note appended with separator


# ======================================================================
# G. Live network (optional — warn-on-fail, yahan se cloud pe bhi chalega)
# ======================================================================

@net_test
def screener_live_reliance():
    from indiaagents.data.sources import get_screener_fundamentals
    sc = get_screener_fundamentals("RELIANCE.NS", "Reliance Industries")
    assert sc is not None, "screener.in fetch fail (cloud pe allowlist/403 check karo)"
    assert sc["ratios"].get("market cap"), sc["ratios"]
    assert sc.get("pe") and sc.get("roce"), f"numeric keys missing: {sorted(sc)}"


@net_test
def nse_live_reliance():
    # NOTE: NSE API datacenter IPs ko 403 deta hai (sandbox/cloud). Parser-correctness
    # fixture tests me covered hai; ye sirf reachability hai — block ho to WARN.
    from indiaagents.data.sources import get_nse_quote
    q = get_nse_quote("RELIANCE.NS")
    if q is None:
        raise ConnectionError("NSE 403-blocked from this IP (datacenter) — normal, graceful None")
    assert q["last"] > 0


# ======================================================================

def main():
    print("=" * 72)
    print("🔌 MULTI-SOURCE DATA LAYER — TEST SUITE")
    print("=" * 72)
    passed = failed = skipped = 0
    failures = []
    t0 = time.time()
    for fn in RESULTS:
        name = fn.__name__
        try:
            out = fn()
            if out == "SKIP-NET":
                print(f"  ⚠️ NET-SKIP {name}")
                skipped += 1
            else:
                print(f"  ✅ PASS   {name}")
                passed += 1
        except Exception:
            print(f"  ❌ FAIL   {name}")
            failures.append((name, traceback.format_exc()))
            failed += 1
    dt = time.time() - t0
    print("-" * 72)
    print(f"RESULT: {passed} passed · {failed} failed · {skipped} network-skipped · "
          f"{passed + failed + skipped} total · {dt:.1f}s")
    if NETWORK_WARN:
        print("Network warnings:", [n for n, _ in NETWORK_WARN])
    if failures:
        print("\n" + "=" * 72)
        print("FAILURE DETAILS:")
        print("=" * 72)
        for name, tb in failures:
            print(f"\n--- {name} ---\n{tb[-1200:]}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
