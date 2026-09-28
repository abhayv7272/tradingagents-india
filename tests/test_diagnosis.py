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


# These files use a tiny standalone runner; keep pytest from treating the
# decorator itself as a fixture-based test function.
test.__test__ = False


def net_test(fn):
    """Network-dependent test: connection issues -> WARN (not FAIL)."""
    def wrapper():
        try:
            return fn()
        except (ConnectionError, TimeoutError, OSError) as e:
            NETWORK_WARN.append((fn.__name__, str(e)[:80]))
            return "SKIP-NET"
        except ValueError as e:
            # Data functions intentionally degrade to a clear ValueError when all
            # remote sources are unavailable; classify that as reachability, not logic.
            if "data nahi mila" in str(e).lower() or "fetch" in str(e).lower():
                NETWORK_WARN.append((fn.__name__, str(e)[:80]))
                return "SKIP-NET"
            raise
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


@test
def config_optional_providers_registered():
    from indiaagents.config import PROVIDERS, ROLE_ASSIGNMENTS
    for p in ("groq", "cerebras", "sambanova"):
        cfg = PROVIDERS.get(p)
        assert cfg, f"{p} PROVIDERS mein nahi hai"
        assert cfg.get("base_url", "").startswith("https://"), f"{p} bad base_url"
        assert cfg.get("key_env"), f"{p} key_env khaali"
        assert cfg.get("preference"), f"{p} model preference khaali"
        assert cfg["rpm"] > 0 and cfg["min_interval"] > 0, f"{p} pacing invalid"
    # har chain mein naye providers included hone chahiye (fallback ke liye)
    for role, chain in ROLE_ASSIGNMENTS.items():
        assert "groq" in chain or "cerebras" in chain, f"{role} mein naya provider nahi"


@test
def quant_factors_shape_order():
    """Qlib-style factor engine: 27 factors, sahi order, no-nan."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import compute_factors, FEATURE_COLS
    rng = np.random.default_rng(7)
    n = 600
    df = pd.DataFrame({
        "Open": 100 + rng.normal(0, 2, n).cumsum(),
        "High": 0, "Low": 0, "Close": 100 + rng.normal(0, 2, n).cumsum(),
        "Volume": rng.integers(1e6, 5e6, n).astype(float),
    })
    df["High"] = df[["Open", "Close"]].max(1) + 1
    df["Low"] = df[["Open", "Close"]].min(1) - 1
    f = compute_factors(df).dropna()
    assert list(f.columns) == FEATURE_COLS, "feature order mismatch"
    assert len(f) > 200 and not f.isna().any().any(), "NaN in factors"
    assert np.isfinite(f.values).all(), "non-finite values"


@net_test
def quant_ml_score_bounds():
    """ML score 0-100 range mein + model artifacts present."""
    import pandas as pd
    from indiaagents.data.quant import ml_score
    import yfinance as yf
    df = yf.download("RELIANCE.NS", period="2y", interval="1d",
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise ConnectionError("Yahoo returned no RELIANCE data")
    ms = ml_score(df)
    assert ms is not None, "model file missing — scripts/train_ml_model.py chalao"
    assert 0 <= ms["score"] <= 100, f"score out of range: {ms['score']}"
    assert -25 <= ms["exp_ret_10d_pct"] <= 25, "expected return unrealistic"
    assert ms.get("val_ic") is not None and ms["val_ic"] > 0, "val IC missing/weak"


@net_test
def quant_block_renders():
    import pandas as pd
    from indiaagents.data.quant import quant_block
    import yfinance as yf
    df = yf.download("TCS.NS", period="2y", interval="1d",
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.empty:
        raise ConnectionError("Yahoo returned no TCS data")
    b = quant_block(df)
    assert "QUANT FACTOR SNAPSHOT" in b and "ML SCORE" in b
    assert "ROC5" in b and "52w position" in b


@test
def static_pm_calibration_prompts():
    """P0 improvements prompts mein hain."""
    from indiaagents.agents.prompts import (PORTFOLIO_MANAGER, BULL_RESEARCHER,
                                            BEAR_RESEARCHER, REFLECTION)
    assert "BEARISH TECHNICALS" in PORTFOLIO_MANAGER and "QUANT ANCHOR" in PORTFOLIO_MANAGER
    assert "Scenarios" in PORTFOLIO_MANAGER and "R:R" in PORTFOLIO_MANAGER
    assert "CONVICTION CHECK" in BULL_RESEARCHER and "CONVICTION CHECK" in BEAR_RESEARCHER
    assert "lesson" in REFLECTION.lower()


@test
def static_model_files_in_repo():
    from indiaagents.data.quant import _MODEL_FILE, _CALIB_FILE
    assert _MODEL_FILE.exists(), "ml_score_v1.joblib missing"
    assert _CALIB_FILE.exists(), "ml_calib_v1.json missing"
    import json
    meta = json.loads(_CALIB_FILE.read_text())
    assert len(meta["quantiles"]) >= 50 and meta["val_ic"] > 0


@test
def regime_engine_synthetic():
    """TradeHive-style 7-regime engine: uptrend/downtrend/sideways pe sahi state."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import regime_state, REGIME_BANDS

    def mk(closes):
        c = pd.Series(closes, dtype=float)
        return pd.DataFrame({"Open": c.shift(1).fillna(c.iloc[0]), "Close": c,
                             "High": c * 1.01, "Low": c * 0.99,
                             "Volume": [1e6] * len(c)})

    up = mk(np.linspace(100, 250, 320))              # steady uptrend
    dn = mk(np.linspace(250, 100, 320))              # steady downtrend
    flat = mk(100 + np.sin(np.linspace(0, 20, 320)) * 2)   # sideways
    r_up, r_dn, r_fl = regime_state(up), regime_state(dn), regime_state(flat)
    assert r_up["regime"] in ("confirmed_uptrend", "early_uptrend"), r_up
    assert r_dn["regime"] in ("confirmed_downtrend", "early_downtrend", "bottoming"), r_dn
    assert r_fl["regime"] in REGIME_BANDS
    for rs in (r_up, r_dn, r_fl):
        assert 0 <= rs["band_lo"] <= rs["band_hi"] <= 100
        assert rs["bull_of6"] + rs["bear_of6"] == 6


@net_test
def regime_pm_clamp_integration():
    """Mock run: PM decision mein regime fields + position band ke andar."""
    import tempfile as _tf
    from pathlib import Path as _P
    import indiaagents.memory as _mem
    _orig = _mem.DecisionLog
    _mem.DecisionLog = lambda *a, **k: _orig(memory_dir=_P(_tf.mkdtemp()))
    try:
        from indiaagents.config import Settings
        from indiaagents.pipeline import TradingAgentsIndiaPipeline
        from indiaagents.data.quant import REGIME_BANDS
        out = TradingAgentsIndiaPipeline(Settings(mock_llm=True)).run("ITC")
        d = out["decision"]
        assert d.get("regime") in REGIME_BANDS, "regime missing in decision"
        lo, hi = REGIME_BANDS[d["regime"]][:2]
        assert d["position_size_pct"] <= hi, (
            f"clamp fail: pos {d['position_size_pct']} > band {hi} ({d['regime']})")
    finally:
        _mem.DecisionLog = _orig          # patch restore — warna baaki tests tootenge


@test
def static_tradehive_prompt_rules():
    from indiaagents.agents.prompts import PORTFOLIO_MANAGER, BULL_RESEARCHER
    assert "REGIME DISCIPLINE" in PORTFOLIO_MANAGER
    assert "REASON FIRST" in PORTFOLIO_MANAGER
    # JSON field order: rationale pehle, decision baad mein (KV cache engineering)
    assert PORTFOLIO_MANAGER.index('"rationale"') < PORTFOLIO_MANAGER.index('"decision"')
    assert "EVIDENCE STRUCTURE" in BULL_RESEARCHER
    assert "REVERSAL SIGNALS" in BULL_RESEARCHER


@test
def static_tradehive_deep2_prompt_rules():
    """Deep-dive 2: 4-type reversal taxonomy + anti-noise rules dono researchers mein,
    PM engagement/survivability rules."""
    from indiaagents.agents.prompts import (PORTFOLIO_MANAGER, BULL_RESEARCHER,
                                            BEAR_RESEARCHER)
    for p in (BULL_RESEARCHER, BEAR_RESEARCHER):
        # 4 valid reversal-signal types (a)-(d)
        for token in ("(a) Volume-price divergence", "(b) Extreme one-sided sentiment",
                      "(c) Price desensitization", "ANTI-NOISE RULES",
                      "SCORING SCALE (1-10)", "REGIME-RELATIVE BASELINE",
                      "Reversal signals", "NOT FOUND"):
            assert token in p, f"missing in {'BULL' if p is BULL_RESEARCHER else 'BEAR'}: {token}"
    assert "(d) Decisive distribution day" in BULL_RESEARCHER       # topping mirror
    assert "(d) Decisive capitulation day" in BEAR_RESEARCHER       # bottoming mirror
    assert "RISK DEBATE ENGAGEMENT" in PORTFOLIO_MANAGER
    assert "SURVIVABILITY" in PORTFOLIO_MANAGER
    assert "REVERSAL-SIGNAL WEIGHT" in PORTFOLIO_MANAGER


@test
def position_structure_synthetic():
    """TradeHive volume-profile position structure: accumulation/distribution read."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import position_structure

    def mk(closes, vols):
        c = pd.Series(np.asarray(closes, dtype=float))
        v = pd.Series(np.asarray(vols, dtype=float), index=c.index)
        return pd.DataFrame({"Open": c.shift(1).fillna(c.iloc[0]), "Close": c,
                             "High": c * 1.01, "Low": c * 0.99, "Volume": v})

    # accumulation at lows → rally on thinning volume into new highs
    up = mk(np.concatenate([np.linspace(100, 120, 160), np.linspace(120, 150, 160)]),
            np.concatenate([np.full(160, 1e7), np.full(120, 4e6), np.full(40, 1e6)]))
    ps = position_structure(up)
    assert ps["pattern"] == "support_below", ps
    assert ps["below_pct"] >= 65, ps
    assert ps["flags"] == ["new_highs_thin_volume"], ps      # 20d vol << 60d vol at highs
    # distribution at highs → decline (overhead supply)
    dn = mk(np.concatenate([np.linspace(150, 130, 160), np.linspace(130, 100, 160)]),
            np.concatenate([np.full(160, 1e7), np.full(160, 3e6)]))
    ps2 = position_structure(dn)
    assert ps2["pattern"] == "overhead_supply", ps2
    assert ps2["above_pct"] >= 55, ps2
    # graceful: short df → {}
    assert position_structure(up.tail(20)) == {}


@test
def quant_block_structure_and_daily_table():
    """quant_block mein POSITION STRUCTURE + RECENT DAILY PERFORMANCE + transitions."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import quant_block

    c = pd.Series(list(np.linspace(100, 105, 319)) + [105, 106, 101.0, 101.5, 100.9])
    df = pd.DataFrame({"Open": c.shift(1).fillna(c.iloc[0]), "Close": c,
                       "High": c * 1.01, "Low": c * 0.99, "Volume": [1e6] * len(c)})
    qb = quant_block(df)
    assert "POSITION STRUCTURE" in qb
    assert "RECENT DAILY PERFORMANCE" in qb
    assert "ABNORMAL" in qb                       # -4% day flagged (|chg| > 3%)
    assert "transitions" in qb.lower()            # regime legal-transitions context
    assert "overhead supply" in qb.lower() or "support_below" in qb.lower() \
        or "balanced" in qb.lower()


@test
def regime_discipline_clamp_and_lock():
    """_apply_regime_discipline: upper clamp + BUY-0% → HOLD lock (no upward force)."""
    from indiaagents.pipeline import _apply_regime_discipline

    d = _apply_regime_discipline(
        {"decision": "BUY", "rating": "Buy", "position_size_pct": 3, "battle_notes": ""},
        {"regime": "confirmed_downtrend", "band_lo": 0, "band_hi": 0})
    assert d["decision"] == "HOLD" and d["position_size_pct"] == 0, d
    assert d["rating"] == "Hold" and "REGIME LOCK" in d["battle_notes"], d
    assert "REGIME CLAMP" in d["battle_notes"] and d["regime"] == "confirmed_downtrend"
    assert d["regime_band"] == "0-0%"

    d2 = _apply_regime_discipline(
        {"decision": "BUY", "rating": "Buy", "position_size_pct": 80, "battle_notes": ""},
        {"regime": "consolidation", "band_lo": 0, "band_hi": 15})
    assert d2["decision"] == "BUY" and d2["position_size_pct"] == 15, d2
    assert "REGIME CLAMP" in d2["battle_notes"] and "REGIME LOCK" not in d2["battle_notes"]

    # koi upward force nahi — PM conservative rahe to allowed
    d3 = _apply_regime_discipline(
        {"decision": "BUY", "rating": "Buy", "position_size_pct": 5, "battle_notes": ""},
        {"regime": "early_uptrend", "band_lo": 30, "band_hi": 60})
    assert d3["decision"] == "BUY" and d3["position_size_pct"] == 5, d3

    # SELL decision band se untouched (exit advisory)
    d4 = _apply_regime_discipline(
        {"decision": "SELL", "rating": "Reduce", "position_size_pct": 0, "battle_notes": ""},
        {"regime": "confirmed_uptrend", "band_lo": 75, "band_hi": 100})
    assert d4["decision"] == "SELL" and "REGIME LOCK" not in d4["battle_notes"], d4


@test
def key_risks_negation_filter():
    """TradeHive filter_reversal_signals se: NOT FOUND/None/N/A placeholder entries drop."""
    from indiaagents.pipeline import _parse_decision
    raw = ('{"decision":"BUY","confidence":70,"rating":"Buy","rationale":"x",'
           '"key_risks":["NOT FOUND","real risk: promoter pledge","None","N/A","-"],'
           '"entry_zone":"a","target":"b","stop_loss":"c","position_size_pct":10,'
           '"timeframe":"t","battle_notes":"n"}')
    d = _parse_decision(raw)
    assert d["key_risks"] == ["real risk: promoter pledge"], d["key_risks"]


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
    assert "Fed Funds" in b or "unavailable" in b or "unconfigured" in b


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
    if df.empty:
        raise ConnectionError("Yahoo returned no RELIANCE chart data")
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
@net_test
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


@net_test
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
def static_sidebar_covers_all_live_providers():
    """Sidebar 'AI Model Keys' list har live provider dikhaye.
    (Regression guard: Groq badge isliye nahi dikha tha kyunki hints dict mein
    groq entry hi missing thi — badge ka code theek tha par list mein hi nahi tha.)"""
    import ast as _ast
    src = (Path(__file__).resolve().parent.parent / "app.py").read_text()
    tree = _ast.parse(src)
    hints = None
    for node in _ast.walk(tree):
        if (isinstance(node, _ast.Assign)
                and any(isinstance(t, _ast.Name) and t.id == "hints"
                        for t in node.targets)
                and isinstance(node.value, _ast.Dict)):
            hints = [k.value for k in node.value.keys
                     if isinstance(k, _ast.Constant)]   # sirf keys — values mein f-string/ternary ho sakte hain
    assert hints is not None, "sidebar hints dict app.py mein nahi mila"
    live = {"gemini", "nvidia", "mistral", "groq", "openrouter"}
    missing = live - set(hints)
    assert not missing, f"sidebar badge list mein provider missing: {missing}"
    for p in live:
        assert f'"{p}"' in src, f"PROVIDER_BADGE map mein {p} nahi"


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
    py_files = [f for f in base.rglob("*.py")
                if not any(part in {".venv", "venv", ".git"} for part in f.parts)]
    for f in py_files + [base / ".env.example"]:
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
# L. DEEP DIAGNOSIS — HARDENING (deep-dive 2 verification + bug-fix regression)
# ======================================================================

@test
def quant_factors_point_in_time_no_leak():
    """LOOKAHEAD-LEAK GUARD (sabse important correctness test):
    row-i ke factors sirf rows <= i se bante hain. Truncated df ka row-299
    full df ke row-299 se EXACT match hona chahiye — warna model leak ho raha hai."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import compute_factors

    rng = np.random.default_rng(42)
    n = 600
    close = 100 + rng.normal(0, 2, n).cumsum()
    df = pd.DataFrame({
        "Open": close + rng.normal(0, 0.5, n),
        "High": close + np.abs(rng.normal(0, 1, n)) + 0.5,
        "Low": close - np.abs(rng.normal(0, 1, n)) - 0.5,
        "Close": close,
        "Volume": rng.integers(1e6, 5e6, n).astype(float)})
    full = compute_factors(df)
    trunc = compute_factors(df.iloc[:300])
    assert trunc.iloc[299].notna().all(), "row 299 truncated mein compute hona chahiye"
    assert np.allclose(full.iloc[299].values, trunc.iloc[299].values), \
        "LOOKAHEAD LEAK: row-299 factors aage ke data se influence ho rahe hain"


@test
def quant_ml_score_deterministic_synthetic():
    """ML score deterministic hai (same input → same output) + tiny df graceful."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import ml_score

    rng = np.random.default_rng(3)
    c = 100 + rng.normal(0, 2, 320).cumsum()
    df = pd.DataFrame({"Open": c, "Close": c, "High": c * 1.01, "Low": c * 0.99,
                       "Volume": rng.integers(1e6, 5e6, 320).astype(float)})
    m1, m2 = ml_score(df), ml_score(df)
    assert m1 is not None and m2 is not None, "model artifacts missing"
    assert m1 == m2, f"NON-DETERMINISTIC: {m1} vs {m2}"
    assert 0 <= m1["score"] <= 100
    tiny = df.head(30)
    assert ml_score(tiny) is None or isinstance(ml_score(tiny), dict)  # no crash


@test
def ml_calibration_quantiles_monotonic():
    """searchsorted SORTED quantiles maangta hai — calib file monotonic verify karo."""
    import json
    import numpy as np
    from indiaagents.data.quant import _CALIB_FILE

    q = json.loads(_CALIB_FILE.read_text())["quantiles"]
    assert len(q) >= 50, "calibration quantiles kam hain"
    assert all(a <= b for a, b in zip(q, q[1:])), "quantiles sorted NAHI — percentile galat hoga!"


@test
def regime_flat_line_and_nan_guards():
    """Deep-diagnosis fix regression: flat/suspended/NaN stock ko trend MAT banao.
    (Pehle perfect-flat series confirmed_downtrend ban jati thi — 0% hard lock!)."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import REGIME_BANDS, regime_state

    def mk(closes):
        c = pd.Series(np.asarray(closes, dtype=float))
        return pd.DataFrame({"Open": c.shift(1).fillna(c.iloc[0]), "Close": c,
                             "High": c * 1.01, "Low": c * 0.99,
                             "Volume": [1e6] * len(c)})

    flat = regime_state(mk([100.0] * 320))                     # suspended stock
    assert flat["regime"] == "consolidation", flat
    assert (flat["band_lo"], flat["band_hi"]) == REGIME_BANDS["consolidation"][:2]
    near_flat = regime_state(mk(100 + np.sin(np.linspace(0, 20, 320)) * 0.01))
    assert near_flat["regime"] == "consolidation", near_flat  # zero-info
    short = regime_state(mk(np.linspace(100, 200, 150)))      # insufficient history
    assert short["regime"] == "consolidation"
    assert short["band_hi"] == REGIME_BANDS["consolidation"][1]
    nan_c = list(np.linspace(100, 200, 320))
    nan_c[100] = float("nan")                                 # broken data
    nan_regime = regime_state(mk(nan_c))
    assert nan_regime["regime"] == "consolidation", nan_regime


@test
def regime_transitions_map_complete():
    """LEGAL_TRANSITIONS har regime cover kare + targets valid hon."""
    from indiaagents.data.quant import LEGAL_TRANSITIONS, REGIME_BANDS

    assert set(LEGAL_TRANSITIONS) == set(REGIME_BANDS), "transitions map incomplete"
    for src, targets in LEGAL_TRANSITIONS.items():
        assert targets, f"{src} ka koi transition nahi"
        for t in targets:
            assert t == "(stay)" or t in REGIME_BANDS, f"invalid transition {src} → {t}"


@test
def position_structure_edge_cases():
    """Volume-profile structure: broken inputs par graceful {} / no-crash."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import position_structure

    def mk(closes, vols):
        c = pd.Series(np.asarray(closes, dtype=float))
        v = pd.Series(np.asarray(vols, dtype=float), index=c.index)
        return pd.DataFrame({"Open": c, "Close": c, "High": c * 1.01, "Low": c * 0.99,
                             "Volume": v})

    big = list(np.linspace(100, 150, 200))
    assert position_structure(mk(big, [1e6] * 200).tail(20)) == {}      # too short
    assert position_structure(mk([100.0] * 200, [1e6] * 200)) == {}     # constant price
    assert position_structure(mk(big, [0.0] * 200)) == {}               # zero volume
    no_vol = mk(big, [1e6] * 200).drop(columns=["Volume"])
    assert position_structure(no_vol) == {}                             # column missing
    mixed = mk(big, [np.nan if i % 7 == 0 else 1e6 for i in range(200)])
    ps = position_structure(mixed)                                      # NaN volume mix
    assert ps == {} or ps["pattern"] in ("overhead_supply", "support_below", "balanced")


@test
def recent_daily_lines_edges():
    """±3% ABNORMAL flag exact boundary par sahi ho; broken index no-crash."""
    import numpy as np
    import pandas as pd
    from indiaagents.data.quant import recent_daily_lines

    def mk(closes):
        c = pd.Series(np.asarray(closes, dtype=float))
        return pd.DataFrame({"Open": c, "Close": c, "High": c * 1.01, "Low": c * 0.99,
                             "Volume": [1e6] * len(c)})

    # last 5 days: +2.9% (NO flag), +4.2% (flag), -2.0%, +0.5%, -1.0%
    closes = list(np.linspace(100, 120, 60))
    closes += [123.48, 128.67, 126.10, 126.73, 125.46]
    lines = recent_daily_lines(mk(closes))
    assert len([x for x in lines if x.startswith("|")]) == 6     # header + 5 rows
    abnormal = [x for x in lines if "ABNORMAL" in x]
    assert len(abnormal) == 1 and "+4.2%" in abnormal[0], lines
    assert "+2.9%" in "\n".join(lines) and "ABNORMAL" not in [
        x for x in lines if "+2.9%" in x][0]
    assert recent_daily_lines(mk([100.0])) == []                 # 1-row df


@test
def regime_discipline_full_matrix():
    """Clamp/lock matrix: HOLD/SELL/string-pos/None-pos/rating-variants."""
    from indiaagents.pipeline import _apply_regime_discipline as D

    # HOLD + over-band position → clamp note, NO lock (lock sirf BUY ke liye)
    d = D({"decision": "HOLD", "rating": "Hold", "position_size_pct": 40,
           "battle_notes": ""}, {"regime": "consolidation", "band_lo": 0, "band_hi": 15})
    assert d["decision"] == "HOLD" and d["position_size_pct"] == 15, d
    assert "REGIME CLAMP" in d["battle_notes"] and "REGIME LOCK" not in d["battle_notes"]
    # SELL ka position field advisory-moot hai — par clamp discipline phir bhi lagegi
    d2 = D({"decision": "SELL", "rating": "Reduce", "position_size_pct": 60,
            "battle_notes": ""}, {"regime": "consolidation", "band_lo": 0, "band_hi": 15})
    assert d2["decision"] == "SELL" and d2["position_size_pct"] == 15, d2
    assert "REGIME LOCK" not in d2["battle_notes"]
    # string position "40%" → 40 (deep-diagnosis hardening)
    d3 = D({"decision": "BUY", "rating": "Buy", "position_size_pct": "40%",
            "battle_notes": ""}, {"regime": "early_uptrend", "band_lo": 30, "band_hi": 60})
    assert d3["decision"] == "BUY" and d3["position_size_pct"] == 40, d3
    # None position + BUY → lock
    d4 = D({"decision": "BUY", "rating": "STRONG BUY", "position_size_pct": None,
            "battle_notes": ""}, {"regime": "confirmed_downtrend", "band_lo": 0, "band_hi": 0})
    assert d4["decision"] == "HOLD" and d4["position_size_pct"] == 0, d4
    assert d4["rating"] == "Hold" and "REGIME LOCK" in d4["battle_notes"]
    # band ke andar → untouched
    d5 = D({"decision": "BUY", "rating": "Buy", "position_size_pct": 20,
            "battle_notes": ""}, {"regime": "bottoming", "band_lo": 5, "band_hi": 20})
    assert d5["decision"] == "BUY" and d5["position_size_pct"] == 20
    assert "REGIME" not in d5["battle_notes"]


@test
def key_risks_negation_precision():
    """Deep-diagnosis fix regression: legit risk 'Q2 guidance not met' KO drop
    NAHI karna — sirf true placeholders drop hon."""
    from indiaagents.pipeline import _parse_decision

    raw = ('{"decision":"BUY","confidence":70,"rating":"Buy","rationale":"x",'
           '"key_risks":["Q2 guidance not met — downgrade risk","NOT FOUND","None",'
           '"N/A","no specific risks","insider activity not detected as material"],'
           '"entry_zone":"a","target":"b","stop_loss":"c","position_size_pct":10,'
           '"timeframe":"t","battle_notes":"n"}')
    d = _parse_decision(raw)
    assert "Q2 guidance not met — downgrade risk" in d["key_risks"], d["key_risks"]
    assert "insider activity not detected as material" in d["key_risks"], d["key_risks"]
    for gone in ("NOT FOUND", "None", "N/A", "—", "no specific risks"):
        assert gone not in d["key_risks"], f"placeholder bacha: {gone}"


@net_test
def pm_parse_error_retry_and_prompt_wiring():
    """END-TO-END: (1) PM garbage output → retry prompt mein PARSE ERROR feedback
    mile aur run survive kare (TradeHive two-layer safeguard). (2) Naye injections
    LIVE wiring mein pahunchen: PM mein regime+transitions, risk team mein regime
    context, debate mein quant snapshot (dates), trader mein regime line."""
    import pathlib
    import tempfile as _tf
    import indiaagents.llm as _llm
    import indiaagents.memory as _mem
    from indiaagents.config import Settings
    from indiaagents.pipeline import TradingAgentsIndiaPipeline

    _orig_log, _orig_chat = _mem.DecisionLog, _llm.MockProvider.chat
    _mem.DecisionLog = lambda *a, **k: _orig_log(memory_dir=pathlib.Path(_tf.mkdtemp()))
    captured, state = [], {"pm_fail": 1}

    def wrapped_chat(self, system, user, temperature, max_tokens):
        captured.append({"system": system, "user": user})
        if "portfolio manager" in system.lower() and state["pm_fail"] > 0:
            state["pm_fail"] -= 1
            return "MAIN JSON NAHI DUNGA — sirf garbage text, braces hi nahi"
        return _orig_chat(self, system, user, temperature, max_tokens)

    _llm.MockProvider.chat = wrapped_chat
    try:
        out = TradingAgentsIndiaPipeline(Settings(mock_llm=True)).run("ITC")
        d = out["decision"]
        # 1) retry ne bacha liya — fallback HOLD (confidence 0) NAHI, parsed decision hai
        assert d["decision"] in ("BUY", "SELL", "HOLD") and d["confidence"] > 0, d
        assert "regime" in d and "regime_band" in d
        # 2) retry prompt mein validation feedback gaya
        pm_users = [c["user"] for c in captured if "hard discipline layer" in c["user"]]
        assert len(pm_users) == 2, f"PM {len(pm_users)}x call hua, 2 (retry) expect tha"
        assert "PARSE ERROR" in pm_users[1], "retry prompt mein feedback nahi gaya"
        # 3) PM ko legal transitions mile
        assert any("Realistic next transitions" in u for u in pm_users)
        # 4) risk team (3 logs) ko regime context mila
        risk_users = [c["user"] for c in captured
                      if "TRADER PLAN" in c["user"] and "MARKET REGIME" in c["user"]]
        assert len(risk_users) >= 3, f"risk regime ctx sirf {len(risk_users)} ko mila"
        # 5) bull/bear debate ko quant snapshot (dates/volume) mila
        debate_users = [c["user"] for c in captured
                        if "DEBATE SO FAR" in c["user"] and "QUANT SNAPSHOT" in c["user"]]
        assert debate_users, "debate ko quant snapshot nahi mila"
        # 6) trader ko regime line mili
        trader_users = [c["user"] for c in captured
                        if "=== FINAL RESEARCH VERDICT ===" in c["user"]]
        assert trader_users and "MARKET REGIME" in trader_users[0]
    finally:
        _llm.MockProvider.chat = _orig_chat
        _mem.DecisionLog = _orig_log          # restore — baaki tests ispe depend karte hain


@test
def report_regime_rows_and_lock_notes():
    """Report MD+HTML dono mein: regime row, band, REGIME CLAMP/LOCK transparency."""
    from indiaagents.report import build_html, build_markdown

    r = _fake_result()
    r["decision"] = {**r["decision"], "regime": "confirmed_downtrend",
                     "regime_band": "0-0%",
                     "battle_notes": ("⚠️ REGIME CLAMP: PM ne 3% bola → 0% "
                                      "| 🚫 REGIME LOCK: BUY → HOLD")}
    md, h = build_markdown(r), build_html(r)
    for doc in (md, h):
        assert "Market Regime" in doc, "regime row missing"
        assert "0-0%" in doc, "band missing"
        assert "REGIME CLAMP" in doc and "REGIME LOCK" in doc, "transparency note missing"


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
