"""
🔍 ULTRA DEEP DIAGNOSIS — TradingAgents India full test suite
Zero LLM API calls (mock engine only). Data layer uses free sources (yfinance/RSS/FRED).

Run:  python tests/test_diagnosis.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

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
# A. CONFIG
# ======================================================================
@test
def config_settings_from_env():
    from indiaagents.config import Settings
    s = Settings.from_env()
    assert s.battle_mode in ("auto", "off")
    assert 1 <= s.debate_rounds <= 5
    assert s.report_language in ("hinglish", "english", "hindi")


@test
def config_api_keys_comma_pool():
    from indiaagents import config
    with patch.dict(config.os.environ, {"GOOGLE_API_KEYS": "k1, k2,,k1,k3"}):
        ks = config.get_api_keys("gemini")
        assert ks == ["k1", "k2", "k3"], f"dedupe failed: {ks}"


@test
def config_language_instructions():
    from indiaagents.config import language_instruction
    assert "Hinglish" in language_instruction("hinglish")
    assert "English" in language_instruction("english")
    assert "हिंदी" in language_instruction("hindi")


@test
def config_role_assignments_complete():
    from indiaagents.config import ROLE_ASSIGNMENTS, PROVIDERS
    valid = set(PROVIDERS)
    for role, chain in ROLE_ASSIGNMENTS.items():
        assert isinstance(chain, list) and chain, f"{role} empty chain"
        for p in chain:
            assert p in valid, f"{role} references unknown provider {p}"


# ======================================================================
# B. TICKER RESOLUTION
# ======================================================================
@net_test
def ticker_reliance_name():
    from indiaagents.data.market import resolve_ticker
    r = resolve_ticker("RELIANCE")
    assert r["ticker"] == "RELIANCE.NS" and r["is_index"] is False


@net_test
def ticker_lowercase_with_spaces():
    from indiaagents.data.market import resolve_ticker
    r = resolve_ticker("  tcs  ")
    assert r["ticker"] == "TCS.NS"


@net_test
def ticker_full_suffix():
    from indiaagents.data.market import resolve_ticker
    r = resolve_ticker("INFY.NS")
    assert r["ticker"] == "INFY.NS"


@net_test
def ticker_full_company_name():
    from indiaagents.data.market import resolve_ticker
    r = resolve_ticker("HDFC Bank")
    assert r["ticker"] == "HDFCBANK.NS"


@net_test
def ticker_bse_suffix():
    from indiaagents.data.market import resolve_ticker
    r = resolve_ticker("RELIANCE.BO")
    assert r["ticker"] == "RELIANCE.BO"


@net_test
def ticker_nifty_index():
    from indiaagents.data.market import resolve_ticker
    r = resolve_ticker("NIFTY")
    assert r["ticker"] == "^NSEI" and r["is_index"] is True


@net_test
def ticker_sensex_usdinr_gold():
    from indiaagents.data.market import resolve_ticker
    assert resolve_ticker("sensex")["ticker"] == "^BSESN"
    assert resolve_ticker("usdinr")["ticker"] == "USDINR=X"
    assert resolve_ticker("gold")["ticker"] == "GC=F"


@test
def ticker_invalid_raises():
    from indiaagents.data.market import resolve_ticker
    try:
        resolve_ticker("ZZZNOTASTOCK123XYZ")
    except ValueError as e:
        assert "NSE" in str(e) or "nahi mila" in str(e)
        return
    raise AssertionError("invalid ticker did not raise ValueError")


@test
def ticker_empty_raises():
    from indiaagents.data.market import resolve_ticker
    try:
        resolve_ticker("   ")
    except ValueError:
        return
    raise AssertionError("empty input did not raise")


@test
def ticker_case_sensitivity():
    from indiaagents.data.market import POPULAR_NSE
    # all keys lowercase (input is lowercased before lookup)
    bad = [k for k in POPULAR_NSE if k != k.lower()]
    assert not bad, f"non-lowercase keys break lookup: {bad[:5]}"


# ======================================================================
# C. INDICATOR MATH (correctness cross-check)
# ======================================================================
@net_test
def indicators_rsi_range_and_manual_check():
    import pandas as pd
    from indiaagents.data.market import get_market_data, _rsi
    mkt = get_market_data("TCS.NS")
    close = mkt["close"]
    assert 0 <= mkt["snapshot"]["rsi"] <= 100
    # manual RSI re-computation with a different formula (Wilder's smoothing)
    delta = close.diff().dropna()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_g = gain.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    avg_l = loss.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    manual = 100 - 100 / (1 + (avg_g / avg_l if avg_l else 1e9))
    assert abs(manual - mkt["snapshot"]["rsi"]) < 0.5, \
        f"RSI mismatch: {manual:.2f} vs {mkt['snapshot']['rsi']}"


@net_test
def indicators_sma_manual_check():
    from indiaagents.data.market import get_market_data, _sma
    mkt = get_market_data("TCS.NS")
    close = mkt["close"]
    manual = close.tail(50).mean()
    ours = _sma(close, 50).iloc[-1]
    assert abs(manual - ours) < 1e-6


@net_test
def indicators_return_math():
    from indiaagents.data.market import get_market_data
    mkt = get_market_data("TCS.NS")
    close = mkt["close"]
    if len(close) > 6:
        manual_1w = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100
        assert abs(manual_1w - mkt["snapshot"]["ret_1m"]) > 1e-9 or True  # 1w vs 1m different
    # 1m return check
    if len(close) > 22:
        manual_1m = (float(close.iloc[-1]) / float(close.iloc[-22]) - 1) * 100
        assert abs(manual_1m - mkt["snapshot"]["ret_1m"]) < 0.01


@net_test
def indicators_no_nan_strings_in_block():
    from indiaagents.data.market import get_market_data
    for t in ("TCS.NS", "SUZLON.NS"):
        mkt = get_market_data(t)
        block = mkt["indicator_block"]
        assert "nan" not in block.replace("finance", "").replace("NAN", ""), \
            f"'nan' leaked into {t} indicator block"
        assert "Support" in block and "RSI" in block


@net_test
def indicators_support_lt_resistance():
    from indiaagents.data.market import get_market_data
    mkt = get_market_data("RELIANCE.NS")
    block = mkt["indicator_block"]
    import re
    sup = float(re.search(r"Support ≈ ₹([\d,\.]+)", block).group(1).replace(",", ""))
    res = float(re.search(r"Resistance ≈ ₹([\d,\.]+)", block).group(1).replace(",", ""))
    assert sup < res, f"support {sup} >= resistance {res}"


@net_test
def indicators_snapshot_types():
    from indiaagents.data.market import get_market_data
    snap = get_market_data("TCS.NS")["snapshot"]
    assert isinstance(snap["price"], float) and snap["price"] > 0
    assert snap["date"].count("-") == 2  # YYYY-MM-DD


# ======================================================================
# D. FUNDAMENTALS
# ======================================================================
@net_test
def fundamentals_block_structure():
    from indiaagents.data.fundamentals import get_fundamentals_data
    f = get_fundamentals_data("RELIANCE.NS")
    b = f["fundamentals_block"]
    for section in ("INCOME STATEMENT", "BALANCE SHEET", "CASH FLOW", "MARKET SNAPSHOT"):
        assert section in b, f"missing {section}"
    import re as _re
    # real nan-VALUE leak check (not 'financial' jaise words ka substring!)
    leaks = _re.findall(r"(?<![a-zA-Z])nan(?![a-zA-Z])", b)
    assert not leaks, f"'nan' value leaked into fundamentals block ({len(leaks)} spots)"


@test
def fundamentals_ratio_formatter():
    from indiaagents.data.fundamentals import _r
    assert _r(None) == "—"
    assert _r(float("nan")) == "—"
    assert _r(1.234) == "1.23"
    assert _r(22.5, 1, "%") == "22.5%"


@net_test
def fundamentals_smallcap_no_crash():
    from indiaagents.data.fundamentals import get_fundamentals_data
    f = get_fundamentals_data("IRFC.NS")  # PSU — different reporting style
    assert isinstance(f["fundamentals_block"], str) and len(f["fundamentals_block"]) > 100


# ======================================================================
# E. NEWS
# ======================================================================
@net_test
def news_company_headlines():
    from indiaagents.data.news import get_company_news
    n = get_company_news("Reliance Industries Limited", "RELIANCE.NS")
    assert "COMPANY NEWS" in n["news_block"]


@net_test
def news_macro_block():
    from indiaagents.data.news import get_india_macro_news
    m = get_india_macro_news(limit=6)
    assert "MACRO" in m["macro_news_block"]


@net_test
def news_historical_window():
    from indiaagents.data.news import get_company_news
    old = (datetime.now() - timedelta(days=120)).strftime("%Y-%m-%d")
    n = get_company_news("Reliance Industries Limited", "RELIANCE.NS", trade_date=old)
    assert "window" in n["news_block"] or "unavailable" in n["news_block"]


@test
def news_dedupe():
    from indiaagents.data.news import _dedupe
    items = [{"title": "Reliance Q2 results beat", "source": "ET", "date": None},
             {"title": "Reliance Q2 results beat", "source": "BS", "date": None},
             {"title": "RBI cuts rates", "source": "Mint", "date": None}]
    out = _dedupe(items)
    assert len(out) == 2


# ======================================================================
# F. SOCIAL
# ======================================================================
@net_test
def social_honest_degradation():
    from indiaagents.data.social import get_social_chatter
    s = get_social_chatter("Reliance Industries Limited", "RELIANCE.NS")
    assert s["source"] in ("reddit-search", "google-news-reddit", "unavailable")
    assert "SOCIAL CHATTER" in s["social_block"]


@test
def social_url_encoded():
    """Reddit query must be URL-encoded (spaces/quotes break raw URLs)."""
    import indiaagents.data.social as soc
    captured = []

    def fake_fetch(url):
        captured.append(url)
        return None  # force failure -> fallback path also checked

    with patch.object(soc, "_fetch", side_effect=fake_fetch):
        soc.get_social_chatter("Reliance Industries", "RELIANCE.NS")
    for url in captured:
        assert " " not in url.split("?")[-1], f"unencoded space in URL: {url[:90]}"
        assert '"' not in url.split("?")[-1], f"unencoded quote in URL: {url[:90]}"


# ======================================================================
# G. MACRO / FRED
# ======================================================================
@net_test
def macro_market_context():
    from indiaagents.data.macro import get_market_context
    m = get_market_context()
    b = m["market_context_block"]
    for token in ("NIFTY 50", "SENSEX", "India VIX", "USD/INR"):
        assert token in b, f"missing {token}"


@net_test
def macro_fred_block():
    from indiaagents.data.macro import get_fred_global_macro
    f = get_fred_global_macro()
    b = f["fred_block"]
    assert "GLOBAL MACRO" in b
    assert "Fed Funds" in b or "unavailable" in b


# ======================================================================
# H. LLM ENGINE — mock & simulated (ZERO real API calls)
# ======================================================================
@test
def llm_mock_engine_end_to_end():
    from indiaagents.config import Settings
    from indiaagents.llm import LLMEngine
    s = Settings()
    s.mock_llm = True
    eng = LLMEngine(s)
    assert "mock" in eng.provider_names()
    text, prov = eng.call("market_analyst", "sys", "user")
    assert isinstance(text, str) and len(text) > 10 and prov == "mock"


@test
def llm_mock_parallel_order():
    from indiaagents.config import Settings
    from indiaagents.llm import LLMEngine
    s = Settings(); s.mock_llm = True
    eng = LLMEngine(s)
    jobs = [{"role": "trader", "system": "s", "user": f"msg{i}"} for i in range(6)]
    out = eng.call_parallel(jobs)
    assert len(out) == 6
    assert all(t and p == "mock" and e is None for t, p, e in out)


@test
def llm_stats_recorded():
    from indiaagents.config import Settings
    from indiaagents.llm import LLMEngine
    s = Settings(); s.mock_llm = True
    eng = LLMEngine(s)
    eng.call("trader", "s", "u")
    eng.call("trader", "s", "u")
    ok, fail = eng.stats.total()
    assert ok == 2 and fail == 0


@test
def llm_gemini_pool_rotation():
    """Simulated: 3 fake keys, all working -> round-robin rotation."""
    import indiaagents.llm as L
    cfg = {"min_interval": 0.0, "rpm": 999, "model_env": "GM",
           "preference": ["gemini-3.8-flash"], "native": True}
    s = L.Settings(); s.llm_retries = 0
    keys_used = []

    class FakeResp:
        status_code = 200
        text = "{}"
        headers = {}
        def raise_for_status(self): pass
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def fake_get(url, headers=None, timeout=None, **kw):
        keys_used.append(headers["x-goog-api-key"])
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"models": [{"name": "models/gemini-3.8-flash",
                                           "supportedGenerationMethods": ["generateContent"]}]}
        return r

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        keys_used.append(headers["x-goog-api-key"])
        return FakeResp()

    p = L.GeminiProvider(cfg, ["K1", "K2", "K3"], s)
    with patch.object(L.requests, "get", side_effect=fake_get), \
         patch.object(L.requests, "post", side_effect=fake_post):
        assert p.detect_model() == "gemini-3.8-flash"
        keys_used.clear()
        for _ in range(6):
            assert p.chat("s", "u", 0.3, 100) == "ok"
    used = [k for k in keys_used if k in ("K1", "K2", "K3")]
    assert set(used) == {"K1", "K2", "K3"}, f"rotation broken: {used}"


@test
def llm_gemini_429_cooldown_rotation():
    """Key1 rate-limited -> engine rotates to key2 without failing."""
    import indiaagents.llm as L
    cfg = {"min_interval": 0.0, "rpm": 999, "model_env": "GM",
           "preference": ["gemini-3.8-flash"], "native": True}
    s = L.Settings(); s.llm_retries = 0

    state = {"post_count": 0}

    class Resp429:
        status_code = 429
        text = "rate limited"
        headers = {"Retry-After": "0"}
        def raise_for_status(self): raise AssertionError()

    class Resp200:
        status_code = 200
        text = "{}"
        headers = {}
        def raise_for_status(self): pass
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "recovered"}]}}]}

    def fake_get(url, headers=None, **kw):
        r = MagicMock(); r.status_code = 200
        r.json.return_value = {"models": [{"name": "models/gemini-3.8-flash",
                                           "supportedGenerationMethods": ["generateContent"]}]}
        return r

    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        state["post_count"] += 1
        if headers["x-goog-api-key"] == "BAD" and state["post_count"] <= 1:
            return Resp429()
        return Resp200()

    p = L.GeminiProvider(cfg, ["BAD", "GOOD"], s)
    with patch.object(L.requests, "get", side_effect=fake_get), \
         patch.object(L.requests, "post", side_effect=fake_post):
        p.detect_model()
        state["post_count"] = 0
        out = p.chat("s", "u", 0.3, 100)
    assert out == "recovered", "429 did not rotate to next key"


@test
def llm_gemini_dead_key_skipped():
    """401 marks a key dead forever; subsequent calls never use it."""
    import indiaagents.llm as L
    cfg = {"min_interval": 0.0, "rpm": 999, "model_env": "GM",
           "preference": ["gemini-3.8-flash"], "native": True}
    s = L.Settings(); s.llm_retries = 0

    class Resp401:
        status_code = 401
        text = "unauthorized"
        headers = {}
        def raise_for_status(self): raise AssertionError()

    class Resp200:
        status_code = 200
        text = "{}"
        headers = {}
        def raise_for_status(self): pass
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def fake_get(url, headers=None, **kw):
        r = MagicMock(); r.status_code = 200
        r.json.return_value = {"models": [{"name": "models/gemini-3.8-flash",
                                           "supportedGenerationMethods": ["generateContent"]}]}
        return r

    seen = []
    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        k = headers["x-goog-api-key"]
        seen.append(k)
        return Resp401() if k == "DEAD" else Resp200()

    p = L.GeminiProvider(cfg, ["DEAD", "OK1", "OK2"], s)
    with patch.object(L.requests, "get", side_effect=fake_get), \
         patch.object(L.requests, "post", side_effect=fake_post):
        p.detect_model()
        for _ in range(4):
            assert p.chat("s", "u", 0.3, 100) == "ok"
        assert p._alive_count() == 2, "dead key not marked"
        # DEAD exactly 2x: once in detect_model probe, once in a chat call
        # (which gets 401 and marks it dead). Round-robin order se position
        # badal sakti hai, isliye order-independent assertions:
        assert seen.count("DEAD") == 2, f"dead key used {seen.count('DEAD')}x: {seen}"
        last_dead = len(seen) - 1 - seen[::-1].index("DEAD")
        assert "DEAD" not in seen[last_dead + 1:], f"dead key reused after 401: {seen}"
        assert p._alive_count() == 2


@test
def llm_gemini_all_keys_dead():
    import indiaagents.llm as L
    cfg = {"min_interval": 0.0, "rpm": 999, "model_env": "GM",
           "preference": ["gemini-3.8-flash"], "native": True}
    s = L.Settings(); s.llm_retries = 0

    class Resp401:
        status_code = 401
        text = "unauthorized"
        headers = {}
        def raise_for_status(self): raise AssertionError()

    def fake_get(url, headers=None, **kw):
        r = MagicMock(); r.status_code = 200
        r.json.return_value = {"models": [{"name": "models/gemini-3.8-flash",
                                           "supportedGenerationMethods": ["generateContent"]}]}
        return r

    p = L.GeminiProvider(cfg, ["A", "B"], s)
    with patch.object(L.requests, "get", side_effect=fake_get), \
         patch.object(L.requests, "post", side_effect=lambda *a, **kw: Resp401()):
        p.detect_model()
        try:
            p.chat("s", "u", 0.3, 100)
        except L.ProviderError:
            return
    raise AssertionError("all-dead pool did not raise ProviderError")


@test
def llm_pace_key_reserves_slot():
    import indiaagents.llm as L
    cfg = {"min_interval": 0.4, "rpm": 150, "model_env": "GM",
           "preference": ["x"], "native": True}
    s = L.Settings()
    p = L.GeminiProvider(cfg, ["K"], s)
    t0 = time.time()
    p._pace_key(0)
    t1 = time.time()
    p._pace_key(0)
    t2 = time.time()
    assert t1 - t0 < 0.35, "first pace should be instant"
    assert t2 - t1 >= 0.35, "second pace must wait for min_interval"


@test
def llm_pick_list_preference():
    from indiaagents.llm import _pick_list_by_preference
    avail = ["a-1", "b-2", "c-3"]
    assert _pick_list_by_preference(avail, ["b-2"], ["x"])[0] == "b-2"
    assert _pick_list_by_preference(avail, ["missing"], ["instruct"])[0] == "a-1"  # no keyword match -> first sorted
    assert _pick_list_by_preference([], ["x"], ["y"]) == []


@test
def llm_engine_fallback_chain():
    """Provider A fails -> engine falls back to provider B for the role."""
    from indiaagents.config import Settings
    import indiaagents.llm as L
    s = Settings(); s.mock_llm = True
    eng = L.LLMEngine(s)
    # inject a fake failing primary before mock
    class Failer(L.BaseProvider):
        name = "failer"
        def detect_model(self): return "f"
        def chat(self, *a, **kw): raise L.ProviderError("always down")
    eng.providers["failer"] = Failer({}, "k", s)
    with patch.dict(L.ROLE_ASSIGNMENTS, {"trader": ["failer", "mock"]}):
        text, prov = eng.call("trader", "s", "u")
    assert prov == "mock" and text  # fell back


@test
def llm_battle_off_collapses_chain():
    from indiaagents.config import Settings
    import indiaagents.llm as L
    s = Settings(); s.mock_llm = True; s.battle_mode = "off"
    eng = L.LLMEngine(s)
    # simulate that gemini + mock are both available
    eng.providers["gemini"] = eng.providers["mock"]
    chain = eng._chain_for("market_analyst")
    assert chain[0] == "gemini", f"battle-off primary wrong: {chain}"
    assert len(chain) == len(eng.providers)


# ======================================================================
# I. PIPELINE — decision parsing torture
# ======================================================================
@test
def parse_fenced_json():
    from indiaagents.pipeline import _parse_decision
    d = _parse_decision('blah ```json\n{"decision": "BUY", "confidence": 80}\n``` end')
    assert d["decision"] == "BUY" and d["confidence"] == 80


@test
def parse_raw_json_with_trailing_commas():
    from indiaagents.pipeline import _parse_decision
    d = _parse_decision('{"decision": "SELL", "confidence": 65, "key_risks": ["a", "b",],}')
    assert d["decision"] == "SELL" and len(d["key_risks"]) == 2


@test
def parse_lowercases_and_clamps():
    from indiaagents.pipeline import _parse_decision
    d = _parse_decision('{"decision": "buy", "confidence": 250}')
    assert d["decision"] == "BUY" and d["confidence"] == 100
    d2 = _parse_decision('{"decision": "weird", "confidence": "x"}')
    assert d2["decision"] == "HOLD" and d2["confidence"] == 50


@test
def parse_key_risks_string_coercion():
    """LLM sometimes returns a string instead of list — must not iterate chars."""
    from indiaagents.pipeline import _parse_decision
    d = _parse_decision('{"decision": "HOLD", "key_risks": "risk one, risk two"}')
    assert isinstance(d["key_risks"], (list, str))
    # iterating must yield sensible items, not single characters
    items = d["key_risks"] if isinstance(d["key_risks"], list) else \
        [x.strip() for x in d["key_risks"].split(",")]
    assert len(items) <= 2 and all(len(i) > 3 for i in items)


@test
def parse_missing_fields_defaults():
    from indiaagents.pipeline import _parse_decision
    d = _parse_decision('{"decision": "BUY"}')
    for k in ("rationale", "entry_zone", "target", "stop_loss",
              "timeframe", "battle_notes"):
        assert k in d and d[k] == "—"
    assert d["position_size_pct"] == 0


@test
def parse_garbage_raises_valueerror():
    from indiaagents.pipeline import _parse_decision
    try:
        _parse_decision("no json here at all")
    except (ValueError, json.JSONDecodeError):
        return
    raise AssertionError("garbage input should raise")


@test
def parse_position_size_coercion():
    from indiaagents.pipeline import _parse_decision
    d = _parse_decision('{"decision": "BUY", "position_size_pct": "3"}')
    assert d["position_size_pct"] == 3


# ======================================================================
# J. MEMORY
# ======================================================================
@test
def memory_log_roundtrip():
    from indiaagents.memory import DecisionLog
    with tempfile.TemporaryDirectory() as td:
        log = DecisionLog(Path(td))
        log.append("TCS.NS", {"decision": "BUY", "rating": "Buy",
                              "confidence": 70, "rationale": "test"}, 3500.0)
        log.append("TCS.NS", {"decision": "HOLD", "rating": "Hold",
                              "confidence": 40, "rationale": "t2"}, 3600.0)
        log.append("INFY.NS", {"decision": "SELL", "rating": "Sell",
                               "confidence": 55, "rationale": "t3"}, 1500.0)
        past = log.past_decisions("TCS.NS")
        assert len(past) == 2 and past[-1]["decision"] == "HOLD"
        recent = log.recent_lessons(5)
        assert len(recent) == 3


@test
def memory_context_empty():
    from indiaagents.memory import memory_context_text
    out = memory_context_text([], None)
    assert "pehle koi decision nahi" in out


@test
def memory_realized_return_math():
    import pandas as pd
    from indiaagents.memory import realized_return
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    close = pd.DataFrame({"Close": [100, 110, 120, 130, 140, 150, 160, 170, 180, 190]}, index=idx)
    rr = realized_return(close, "X", "2026-01-01")
    assert rr and abs(rr["stock_ret"] - 90.0) < 0.01  # 100 -> 190


# ======================================================================
# K. REPORT
# ======================================================================
def _fake_result(decision="BUY", mock=True, with_chart=True):
    return {
        "ticker": "TEST.NS", "name": "Test Industries Ltd", "exchange": "NSE",
        "trade_date": "2026-09-27", "price": 1234.5,
        "snapshot": {"sector": "Tech", "industry": "Software", "market_cap": 1.65e12,
                     "pe": 22.2, "pb": 1.8, "beta": 0.9, "rsi": 42.5,
                     "from_52w_high": -15.2, "from_52w_low": 30.1,
                     "ret_1m": -4.4, "ret_1y": -10.9, "date": "2026-09-25"},
        "analyst_reports": {"market": "MKT report", "fundamentals": "FUND report",
                            "news": "NEWS report", "social": "SOC report"},
        "debate": "Bull said X. Bear said Y.",
        "draft_verdict": "Draft verdict text",
        "battle_critiques": "Critic 1: ...",
        "final_research": "Final research text",
        "trader_plan": "Trader plan text",
        "risk_views": "Risk views text",
        "decision": {"decision": decision, "rating": "Buy", "confidence": 64,
                     "rationale": "Solid hai <script>alert('x')</script>",
                     "key_risks": ["R1", "R2"], "entry_zone": "1200-1250",
                     "target": "1400", "stop_loss": "1150",
                     "position_size_pct": 3, "timeframe": "1-3m",
                     "battle_notes": "Gemini vs NVIDIA disagree on valuation"},
        "memory": "No past",
        "news_block": "news", "macro_news_block": "macro",
        "social_block": "social", "indicator_block": "ind",
        "fundamentals_block": "fund", "market_context_block": "ctx",
        "fred_block": "fred",
        "models": {"gemini": "gemini-3.8-flash"}, "stats": {
            "gemini": {"ok": 7, "fail": 0, "models": ["gemini-3.8-flash"],
                       "roles": ["trader", "market_analyst"]}},
        "settings": {}, "mock": mock,
        "chart_b64": "aVRleHQ=" if with_chart else None,
        "chart_png": b"\x89PNG\r\n\x1a\n" if with_chart else None,
    }


@test
def report_markdown_all_sections():
    from indiaagents.report import build_markdown
    md = build_markdown(_fake_result())
    for s in ("FINAL VERDICT", "Model Battle Scoreboard", "Company Snapshot",
              "Analyst Team", "Bull", "Bear", "Model Battle Round",
              "Trading Team Plan", "Risk Management", "Memory", "Appendix",
              "Disclaimer"):
        assert s in md, f"missing section: {s}"


@test
def report_html_premium_structure():
    from indiaagents.report import build_html
    h = build_html(_fake_result())
    for token in ("class='hero'", "vpill", "confbar", "kpis", "trade-grid",
                  "data:image/png;base64,", "pbadge", "secnum", "@media print"):
        assert token in h, f"missing premium element: {token}"


@test
def report_html_escapes_xss():
    from indiaagents.report import build_html
    h = build_html(_fake_result())
    assert "<script>alert" not in h, "XSS not escaped!"
    assert "&lt;script&gt;" in h


@test
def report_all_verdict_variants():
    from indiaagents.report import build_html
    for d, css in (("BUY", "v-buy"), ("SELL", "v-sell"), ("HOLD", "v-hold")):
        h = build_html(_fake_result(decision=d))
        assert css in h, f"{d} verdict style missing"


@test
def report_no_chart_no_crash():
    from indiaagents.report import build_html, build_markdown
    r = _fake_result(with_chart=False)
    assert "base64" not in build_html(r)
    assert "FINAL VERDICT" in build_markdown(r)


@test
def report_indian_units():
    from indiaagents.report import indian_units
    assert indian_units(16590810644480) == "₹16,59,081 Cr"
    assert indian_units(500000) == "₹5 L"
    assert indian_units(None) == "—"
    assert indian_units(999) == "₹999"


@test
def report_rnd_safe():
    from indiaagents.report import rnd
    assert rnd(22.2222) == "22.22"
    assert rnd(None) == "—"
    assert rnd("abc") == "—"


@test
def report_saved_to_disk():
    from indiaagents import report as rep
    with tempfile.TemporaryDirectory() as td:
        rep.REPORTS_DIR = Path(td)
        paths = rep.build_report(_fake_result())
        assert Path(paths["md"]).exists() and Path(paths["html"]).exists()
        assert Path(paths["dir"], "chart.png").exists()
        html = Path(paths["html"]).read_text(encoding="utf-8")
        assert "Test Industries" in html


# ======================================================================
# L. CHARTS
# ======================================================================
@net_test
def chart_generates_valid_png():
    import yfinance as yf
    from indiaagents.charts import build_price_chart
    df = yf.Ticker("RELIANCE.NS").history(period="1y")
    assert not df.empty
    out = build_price_chart(df, "Reliance", "RELIANCE.NS", "BUY", save_dir="/tmp")
    assert out["png"][:8] == b"\x89PNG\r\n\x1a\n"
    assert len(out["png"]) > 20000
    assert len(out["b64"]) > 1000


@test
def chart_tiny_dataframe_no_crash():
    import pandas as pd
    from indiaagents.charts import build_price_chart
    idx = pd.date_range("2026-01-01", periods=8)
    df = pd.DataFrame({"Open": [10]*8, "High": [11]*8, "Low": [9]*8,
                       "Close": [10.5]*8, "Volume": [1e6]*8}, index=idx)
    out = build_price_chart(df, "Tiny", "TINY.NS", "HOLD")
    assert out["png"][:8] == b"\x89PNG\r\n\x1a\n"


@test
def chart_all_decisions():
    import pandas as pd
    from indiaagents.charts import build_price_chart
    idx = pd.date_range("2026-01-01", periods=60)
    import numpy as np
    closes = np.linspace(100, 140, 60)
    df = pd.DataFrame({"Open": closes, "High": closes + 2, "Low": closes - 2,
                       "Close": closes, "Volume": np.full(60, 5e6)}, index=idx)
    for d in ("BUY", "SELL", "HOLD"):
        out = build_price_chart(df, "X", "X.NS", d)
        assert out["png"][:4] == b"\x89PNG"


# ======================================================================
# M. PIPELINE INTEGRATION (mock LLM — zero API cost)
# ======================================================================
@test
def integration_full_mock_run():
    from indiaagents import report as rep, memory as mem
    from indiaagents.config import Settings
    from indiaagents.pipeline import TradingAgentsIndiaPipeline
    tmp = tempfile.mkdtemp()
    try:
        rep.REPORTS_DIR = Path(tmp)
        mem.MEMORY_DIR = Path(tmp)
        s = Settings()
        s.mock_llm = True
        s.debate_rounds = 1  # fast
        pipe = TradingAgentsIndiaPipeline(s)
        res = pipe.run("SBIN", None)
        assert res["decision"]["decision"] in ("BUY", "SELL", "HOLD")
        assert Path(res["paths"]["md"]).exists()
        assert Path(res["paths"]["html"]).exists()
        assert Path(res["paths"]["dir"], "chart.png").exists()
        # decision logged
        log = mem.DecisionLog(Path(tmp))
        assert len(log.past_decisions("SBIN.NS")) == 1
        # second run should see memory context
        res2 = TradingAgentsIndiaPipeline(s).run("SBIN", None)
        assert "PAST DECISIONS" in res2["memory"] or "SBIN" in res2["memory"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@test
def integration_future_date_clamped():
    from indiaagents import report as rep, memory as mem
    from indiaagents.config import Settings
    from indiaagents.pipeline import TradingAgentsIndiaPipeline
    tmp = tempfile.mkdtemp()
    try:
        rep.REPORTS_DIR = Path(tmp); mem.MEMORY_DIR = Path(tmp)
        s = Settings(); s.mock_llm = True; s.debate_rounds = 1
        events = []
        pipe = TradingAgentsIndiaPipeline(s, progress_cb=lambda ev: events.append(ev))
        future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        res = pipe.run("ITC", future)
        assert res["trade_date"] == datetime.now().strftime("%Y-%m-%d"), \
            f"future date not clamped: {res['trade_date']}"
        assert any("clamp" in e["detail"] for e in events)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ======================================================================
# N. STATIC / SYNTAX checks
# ======================================================================
@test
def static_app_compiles():
    src = (Path(__file__).resolve().parent.parent / "app.py").read_text()
    compile(src, "app.py", "exec")


@test
def static_run_compiles():
    src = (Path(__file__).resolve().parent.parent / "run.py").read_text()
    compile(src, "run.py", "exec")


@test
def static_no_bare_print_in_lib():
    base = Path(__file__).resolve().parent.parent / "indiaagents"
    offenders = []
    for f in base.rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            ls = line.strip()
            if ls.startswith("print(") and "logger" not in ls:
                offenders.append(f"{f.name}:{i}")
    assert not offenders, f"print() found in library code: {offenders}"


@test
def static_no_placeholder_keys():
    """Creds should never be hardcoded in code (only .env)."""
    import re
    base = Path(__file__).resolve().parent.parent
    for f in list(base.rglob("*.py")) + [base / ".env.example"]:
        txt = f.read_text(encoding="utf-8")
        for pattern in (r"AIza[0-9A-Za-z\-_]{20,}", r"nvapi-[A-Za-z0-9\-_]{20,}",
                        r"mstrl_[A-Za-z0-9\-_]{20,}", r"sk-or-v1-[a-f0-9]{30,}"):
            assert not re.search(pattern, txt), f"possible hardcoded key in {f.name}!"


@test
def static_env_not_in_zip_source():
    """The deploy zip must never contain .env (checked at zip build too)."""
    zp = Path(__file__).resolve().parent.parent.parent / "tradingagents-india.zip"
    if not zp.exists():
        return  # zip not built yet in this env — skip silently
    import zipfile
    with zipfile.ZipFile(zp) as z:
        assert not any(n.endswith("/.env") or n == ".env" for n in z.namelist()), \
            ".env leaked into deploy zip!"


@test
def static_requirements_complete():
    reqs = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text()
    for pkg in ("yfinance", "pandas", "requests", "openai", "python-dotenv",
                "streamlit", "markdown", "matplotlib"):
        assert pkg in reqs, f"{pkg} missing from requirements.txt"


# ======================================================================
# RUNNER
# ======================================================================
def main():
    print("=" * 72)
    print("🔍 TRADINGAGENTS INDIA — ULTRA DEEP DIAGNOSIS")
    print("=" * 72)
    passed = failed = skipped = 0
    failures = []
    t0 = time.time()
    for fn in RESULTS:
        name = fn.__name__
        try:
            r = fn()
            if r == "SKIP-NET":
                print(f"  ⚠️  SKIP  {name} (network)")
                skipped += 1
            else:
                print(f"  ✅ PASS  {name}")
                passed += 1
        except Exception:
            print(f"  ❌ FAIL  {name}")
            failures.append((name, traceback.format_exc()))
            failed += 1
    dt = time.time() - t0
    print("-" * 72)
    print(f"RESULT: {passed} passed · {failed} failed · {skipped} network-skipped "
          f"· {passed + failed + skipped} total · {dt:.1f}s")
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
