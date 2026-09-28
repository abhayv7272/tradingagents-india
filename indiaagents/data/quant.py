"""
Quant Engine — Qlib-inspired (Alpha158-lite) for Indian stocks
==============================================================
Do kaam:
  1. compute_factors(): 27 point-in-time factors (KBAR/ROC/MA/STD/Volume/RSI/
     MACD/Bollinger/52w) — Alpha158 ka tested subset
  2. ml_score(): pre-trained HistGradientBoosting model se 0-100 score
     (model offline train hota hai: scripts/train_ml_model.py)

Model file: indiaagents/models/ml_score_v1.joblib (+ ml_calib_v1.json)
Koi model na ho to graceful degradation — sirf factor block milta hai.

NOTE: ML score ek DETERMINISTIC second-opinion hai (LLM anchor) — advisory,
not advice. POC IC = +0.025 (Rank IC, 10-day, NSE 40-stock universe).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

_MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
_MODEL_FILE = _MODELS_DIR / "ml_score_v1.joblib"
_CALIB_FILE = _MODELS_DIR / "ml_calib_v1.json"

# Feature order FIXED hai — training aur inference same order use karte hain
FEATURE_COLS = [
    "kbar_co", "kbar_hl", "kbar_ch", "kbar_cl",
    "roc5", "roc10", "roc20", "roc60",
    "c_ma5", "c_ma10", "c_ma20", "c_ma60",
    "ma5_10", "ma10_20", "ma20_60",
    "std20", "std60", "std5_20",
    "vol_5", "vol_20", "vol_ratio",
    "rsi14", "macd", "boll", "pos52", "c_max20", "c_min20",
]


# ---------------------------------------------------------------------------
def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """Alpha158-lite factors — sab rolling history se (point-in-time, no leak)."""
    c, o, h, l, v = df["Close"], df["Open"], df["High"], df["Low"], df["Volume"]
    f = pd.DataFrame(index=df.index)
    f["kbar_co"] = (c - o) / o
    f["kbar_hl"] = (h - l) / o
    f["kbar_ch"] = c / h - 1
    f["kbar_cl"] = c / l - 1
    for n in (5, 10, 20, 60):
        f[f"roc{n}"] = c / c.shift(n) - 1
    for n in (5, 10, 20, 60):
        f[f"c_ma{n}"] = c / c.rolling(n).mean() - 1
    f["ma5_10"] = c.rolling(5).mean() / c.rolling(10).mean() - 1
    f["ma10_20"] = c.rolling(10).mean() / c.rolling(20).mean() - 1
    f["ma20_60"] = c.rolling(20).mean() / c.rolling(60).mean() - 1
    r = c.pct_change(fill_method=None)   # NaN ko pad mat karo (leak-safe)
    f["std20"] = r.rolling(20).std()
    f["std60"] = r.rolling(60).std()
    f["std5_20"] = r.rolling(5).std() / (r.rolling(20).std() + 1e-9)
    f["vol_5"] = v / (v.rolling(5).mean() + 1e-9) - 1
    f["vol_20"] = v / (v.rolling(20).mean() + 1e-9) - 1
    f["vol_ratio"] = v.rolling(5).mean() / (v.rolling(20).mean() + 1e-9)
    d = c.diff()
    f["rsi14"] = (d.clip(lower=0).rolling(14).mean()
                  / (d.abs().rolling(14).mean() + 1e-9))
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    f["macd"] = ((ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()) / c
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    f["boll"] = (c - m20) / (2 * s20 + 1e-9)
    lo52, hi52 = c.rolling(252).min(), c.rolling(252).max()
    f["pos52"] = (c - lo52) / (hi52 - lo52 + 1e-9)
    f["c_max20"] = c / c.rolling(20).max() - 1
    f["c_min20"] = c / c.rolling(20).min() - 1
    return f[FEATURE_COLS]


# ---------------------------------------------------------------------------
# REGIME ENGINE — TradeHive "hard discipline" se inspired (India-adapted)
# 7-regime state + position bands. DETERMINISTIC hai — LLM isse argue nahi,
# sirf respect karta hai (code clamp backstop hai).
# Percent of TOTAL portfolio capital, not "% of a planned trade".  The old
# 75-100% uptrend band accidentally encouraged single-stock concentration while
# the report labelled the number "% capital".  These caps are deliberately
# portfolio-safe defaults; a user's suitability/liquidity constraints may be lower.
REGIME_BANDS = {
    "confirmed_uptrend":   (10, 20, "strong trend — normal/full single-stock allocation allowed"),
    "early_uptrend":       (5, 10,  "trend confirm ho raha hai — starter allocation"),
    "consolidation":       (0, 5,   "range-bound — watch ya small allocation"),
    "topping":             (0, 5,   "top zone — fresh allocation avoid / existing position trim"),
    "early_downtrend":     (0, 3,   "trend bigad raha hai — capital preservation"),
    "confirmed_downtrend": (0, 0,   "confirmed downtrend — no fresh position (hard lock)"),
    "bottoming":           (0, 5,   "bottom fishing — sirf small probe"),
}


def regime_state(df: pd.DataFrame) -> dict:
    """7-regime deterministic state (TradeHive 5-of-6 rule se inspired).
    Returns {regime, band_lo, band_hi, intent, conditions, score}."""
    c = df["Close"]
    if len(c) < 210:
        lo, hi, _ = REGIME_BANDS["consolidation"]
        return {"regime": "consolidation", "band_lo": lo, "band_hi": hi,
                "intent": "insufficient history — conservative default",
                "conditions": {}, "bull_of6": 0, "bear_of6": 0}
    price = float(c.iloc[-1])
    sma20 = float(c.rolling(20).mean().iloc[-1])
    sma50 = float(c.rolling(50).mean().iloc[-1])
    sma200 = float(c.rolling(200).mean().iloc[-1])
    r = c.diff()
    rsi = float((r.clip(lower=0).ewm(alpha=1/14).mean().iloc[-1])
                / (r.abs().ewm(alpha=1/14).mean().iloc[-1] + 1e-9) * 100)
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    macd_hist = float(((ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()).iloc[-1])
    roc20 = float(c.iloc[-1] / c.iloc[-21] - 1) if len(c) > 21 else 0.0
    lo52, hi52 = float(c.rolling(252).min().iloc[-1]), float(c.rolling(252).max().iloc[-1])
    pos52 = (price - lo52) / (hi52 - lo52 + 1e-9)

    # Deep-diagnosis guards: (1) NaN/broken data, (2) zero-movement (suspended/flat)
    # series — dono mein TREND claim karna galat hai; conservative default lo.
    # (Perfect-flat series 0/6 conditions se falsely confirmed_downtrend ban jati tha.)
    # NOTE: mean ABSOLUTE return use hota hai, return-STD nahi — linear ramp
    # (perfect trend) ka return-STD near-zero hota hai par movement badi hoti hai.
    _finite = all(np.isfinite(x) for x in
                  (price, sma20, sma50, sma200, rsi, macd_hist, roc20, lo52, hi52))
    _rmag = float(c.pct_change(fill_method=None).tail(60).abs().mean())
    if not _finite or _rmag < 5e-4:
        lo, hi, intent = REGIME_BANDS["consolidation"]
        return {"regime": "consolidation", "band_lo": lo, "band_hi": hi,
                "intent": intent + " (flat/insufficient-movement data — no trend claim)",
                "conditions": {}, "bull_of6": 0, "bear_of6": 0}

    cond = {
        "price>sma20": price > sma20, "sma20>sma50": sma20 > sma50,
        "sma50>sma200": sma50 > sma200, "macd_hist>0": macd_hist > 0,
        "roc20>0": roc20 > 0, "rsi>50": rsi > 50,
    }
    bull_of6 = sum(cond.values())
    bear_of6 = sum(not v for v in cond.values())

    if bull_of6 >= 5:                                   # TradeHive 5-of-6
        regime = "confirmed_uptrend"
    elif bear_of6 >= 5:
        regime = "confirmed_downtrend"
    elif sma50 > sma200 and (rsi >= 65 or pos52 >= 0.95) and (macd_hist < 0 or roc20 < 0):
        regime = "topping"
    elif sma50 < sma200 and (rsi <= 35 or pos52 <= 0.05) and (macd_hist > 0 or roc20 > 0):
        regime = "bottoming"
    elif sma20 > sma50 and macd_hist > 0:
        regime = "early_uptrend"
    elif sma20 < sma50 and macd_hist < 0:
        regime = "early_downtrend"
    else:
        regime = "consolidation"

    lo, hi, intent = REGIME_BANDS[regime]
    return {"regime": regime, "band_lo": lo, "band_hi": hi, "intent": intent,
            "conditions": cond, "bull_of6": bull_of6, "bear_of6": bear_of6,
            "rsi": round(rsi, 1), "pos52": round(pos52, 2)}


# Regime state machine — realistic next states (TradeHive LEGAL_TRANSITIONS se;
# humara regime daily deterministic compute hota hai, ye map sirf LLM ko context
# deti hai ki kaise transitions realistically aate hain — "consolidation se seedha
# confirmed_uptrend" nahi hota).
LEGAL_TRANSITIONS = {
    "confirmed_uptrend":   ["topping", "(stay)"],
    "early_uptrend":       ["confirmed_uptrend", "consolidation", "(stay)"],
    "consolidation":       ["early_uptrend", "early_downtrend", "(stay)"],
    "topping":             ["consolidation", "early_downtrend", "early_uptrend", "(stay)"],
    "early_downtrend":     ["confirmed_downtrend", "consolidation", "(stay)"],
    "confirmed_downtrend": ["bottoming", "(stay)"],
    "bottoming":           ["consolidation", "early_uptrend", "early_downtrend", "(stay)"],
}


def position_structure(df: pd.DataFrame, lookback: int = 120, bins: int = 12) -> dict:
    """Volume-profile position structure (TradeHive market-analyst pattern, deterministic).
    Kahan volume concentrate hai (accumulation/distribution zones) aur current price
    un zones ke mukable kahan hai — overhead supply vs support-below read."""
    try:
        d = df.tail(lookback)
        if len(d) < 40:
            return {}
        c = d["Close"].astype(float).values
        v = pd.to_numeric(d["Volume"], errors="coerce").fillna(0).values
        if float(v.sum()) <= 0:
            return {}
        price = float(c[-1])
        lo, hi = float(np.nanmin(c)), float(np.nanmax(c))
        if not np.isfinite(lo) or hi <= lo:
            return {}
        edges = np.linspace(lo, hi, bins + 1)
        idx = np.clip(np.digitize(c, edges) - 1, 0, bins - 1)
        vol = np.zeros(bins)
        np.add.at(vol, idx, v)
        total = float(vol.sum())
        vol_pct = vol / (total + 1e-12) * 100.0
        centers = (edges[:-1] + edges[1:]) / 2.0
        below = float(vol[centers < price].sum() / (total + 1e-12) * 100.0)
        above = 100.0 - below
        order = np.argsort(vol)[::-1]
        zones = [(round(float(edges[b]), 2), round(float(edges[b + 1]), 2),
                  round(float(vol_pct[b]), 1)) for b in order[:2] if vol_pct[b] > 3.0]
        # 60d volume-trend flags (TradeHive reversal-signal type (a)/(d) ka data basis)
        cc = df["Close"].astype(float)
        vv = pd.to_numeric(df["Volume"], errors="coerce").fillna(0)
        hi60 = float(cc.rolling(60).max().iloc[-1]) if len(cc) >= 60 else float(cc.max())
        lo60 = float(cc.rolling(60).min().iloc[-1]) if len(cc) >= 60 else float(cc.min())
        v20 = float(vv.rolling(20).mean().iloc[-1]) if len(vv) >= 20 else float(vv.mean())
        v60 = float(vv.rolling(60).mean().iloc[-1]) if len(vv) >= 60 else v20
        vol_drain = v60 > 0 and (v20 / v60) < 0.85
        at_60d_high = price >= hi60 * 0.99
        at_60d_low = price <= lo60 * 1.01
        pattern = ("overhead_supply" if above > 55 else
                   "support_below" if below > 65 else "balanced")
        flags = []
        if at_60d_high and vol_drain:
            flags.append("new_highs_thin_volume")
        if at_60d_low and vol_drain:
            flags.append("selling_exhaustion_dry_volume")
        hvn = int(vol.argmax())
        out = {
            "below_pct": round(below, 1), "above_pct": round(above, 1),
            "pattern": pattern, "zones": zones,
            "node_lo": round(float(edges[hvn]), 2), "node_hi": round(float(edges[hvn + 1]), 2),
            "node_pct": round(float(vol_pct[hvn]), 1),
            "vol20_vs_60": round(v20 / (v60 + 1e-9), 2),
            "flags": flags,
        }
        out["dist_node_pct"] = round(float(
            (price - (edges[hvn] + edges[hvn + 1]) / 2.0) / price * 100.0), 1)
        return out
    except Exception:
        return {}


def recent_daily_lines(df: pd.DataFrame, n: int = 5) -> list[str]:
    """Last n sessions ka table (date/close/chg%/volume, ±3% = ABNORMAL flag).
    TradeHive reversal-signal rules DATES maangti hain — ye table wahi raw data hai."""
    try:
        d = df.tail(n + 1)
        if len(d) < 2:
            return []
        c = d["Close"].astype(float)
        v = pd.to_numeric(d["Volume"], errors="coerce")
        out = ["RECENT DAILY PERFORMANCE (reversal-signal evidence ke liye dates yahan se cite karo):",
               "| Date | Close | Chg% | Volume | Note |"]
        prev = c.shift(1)
        for i in range(1, len(d)):
            chg = (c.iloc[i] / prev.iloc[i] - 1) * 100.0
            dt = d.index[i]
            dt = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") else str(dt)[:10]
            vv = v.iloc[i]
            if vv == vv and vv > 0:
                vs = f"{vv/1e6:.1f}M" if vv >= 1e6 else f"{vv/1e3:.0f}K"
            else:
                vs = "—"
            note = "⚠️ ABNORMAL (>±3%)" if abs(chg) > 3 else ""
            out.append(f"| {dt} | {c.iloc[i]:,.2f} | {chg:+.1f}% | {vs} | {note} |")
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
_model_cache: dict = {}


def ml_score(df: pd.DataFrame) -> dict | None:
    """Trained model se 0-100 score + expected 10-day return.
    Model/calib missing ya error ho to None (graceful)."""
    if not _MODEL_FILE.exists() or not _CALIB_FILE.exists():
        return None
    try:
        f = compute_factors(df).dropna()
        if len(f) < 5:
            return None
        x = f.iloc[-1].values.reshape(1, -1)
        if "m" not in _model_cache:
            import joblib
            _model_cache["m"] = joblib.load(_MODEL_FILE)
            _model_cache["calib"] = json.loads(_CALIB_FILE.read_text())
        pred = float(_model_cache["m"].predict(x)[0])          # exp. 10d return
        calib = _model_cache["calib"]
        q = calib["quantiles"]                                   # training dist.
        pct = float(np.searchsorted(q, pred) / len(q) * 100)     # 0-100
        return {
            "score": round(pct, 0),
            "exp_ret_10d_pct": round(pred * 100, 2),
            "trained": calib.get("trained", "?"),
            "val_ic": calib.get("val_ic"),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
def quant_block(df: pd.DataFrame) -> str:
    """LLM/prompt ke liye quant evidence block (factors + ML score)."""
    f = compute_factors(df).dropna()
    if f.empty:
        return ""
    last = f.iloc[-1]
    lines = ["QUANT FACTOR SNAPSHOT (Alpha158-lite, point-in-time):"]
    lines.append(f"- Momentum: ROC5 {last['roc5']*100:+.1f}% | ROC20 "
                 f"{last['roc20']*100:+.1f}% | ROC60 {last['roc60']*100:+.1f}%")
    lines.append(f"- Trend: close/MA20 {last['c_ma20']*100:+.1f}% | MA10/MA20 "
                 f"{last['ma10_20']*100:+.1f}% | MA20/MA60 {last['ma20_60']*100:+.1f}%")
    lines.append(f"- Volatility: STD20 {last['std20']*100:.2f}% daily | "
                 f"STD5/STD20 {last['std5_20']:.2f} (regime {'up' if last['std5_20'] > 1 else 'down'})")
    lines.append(f"- Volume: 5d vs 20d ratio {last['vol_ratio']:.2f} | "
                 f"vol vs 20d avg {last['vol_20']*100:+.0f}%")
    lines.append(f"- RSI(norm): {last['rsi14']:.2f} | MACD/px {last['macd']*100:+.2f}% | "
                 f"Bollinger pos {last['boll']:+.2f}")
    lines.append(f"- 52w position: {last['pos52']*100:.0f}% | vs 20d-high "
                 f"{last['c_max20']*100:+.1f}% | vs 20d-low {last['c_min20']*100:+.1f}%")
    try:
        rs = regime_state(df)
        trans = ", ".join(LEGAL_TRANSITIONS.get(rs["regime"], []))
        lines.append(f"MARKET REGIME (deterministic): {rs['regime']} | allowed position band: "
                     f"{rs['band_lo']}-{rs['band_hi']}% ({rs['intent']}) | "
                     f"bull-conditions {rs['bull_of6']}/6")
        lines.append(f"- Regime context: realistic next transitions: {trans} "
                     "(regime jump karna realistic nahi hai — e.g. consolidation se "
                     "seedha confirmed_uptrend nahi hota)")
    except Exception:
        pass
    try:
        ps = position_structure(df)
        if ps:
            z = "; ".join(f"₹{a:,.0f}–₹{b:,.0f} ({p}% of volume)"
                          for a, b, p in ps["zones"]) or "spread evenly"
            lines.append(
                f"POSITION STRUCTURE (volume-profile, last 120 sessions): "
                f"{ps['pattern']} | volume below current price: {ps['below_pct']}% "
                f"(holders in profit) | above: {ps['above_pct']}% (overhead supply)")
            lines.append(
                f"- Heaviest volume zones: {z} | price high-volume node se "
                f"{ps['dist_node_pct']:+.1f}% | 20d-vs-60d avg volume: "
                f"{ps['vol20_vs_60']:.2f}x")
            if ps["flags"]:
                fl = "; ".join(ps["flags"])
                lines.append(f"- ⚠️ Structure flags: {fl} "
                             "(new highs on thin volume = participation fading; "
                             "dry-volume selloff = selling exhaustion)")
    except Exception:
        pass
    lines.extend(recent_daily_lines(df))
    ms = ml_score(df)
    if ms:
        lines.append(
            f"ML SCORE (Qlib-style model, {ms['trained']} ko train, val IC={ms['val_ic']}): "
            f"{ms['score']:.0f}/100 | expected 10-day move: {ms['exp_ret_10d_pct']:+.2f}% "
            f"(cross-section percentile — 50=average stock, 80+=strong, <30=weak)")
        lines.append(
            "ML score DETERMINISTIC hai (koi hallucination nahi). Ise evidence ke roop "
            "mein use karo — support karo ya data-based reason se contradict karo.")
    else:
        lines.append("(ML model available nahi — sirf factors upar hain)")
    return "\n".join(lines)
