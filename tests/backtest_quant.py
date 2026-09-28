#!/usr/bin/env python3
"""
PART A — QUANT SIGNAL BACKTEST (ZERO API COST)
================================================
Hamari data-layer ke indicators (RSI/SMA/MACD/momentum) ka signal quality
napta hai — 15 NSE stocks x 6 monthly dates, point-in-time slicing se.

Ye poore AI system ka proxy hai: agar data-layer ka composite view follow
kiya jaye to kitni baar sahi hota? Alpha NIFTY (^NSEI) ke against measure
hoti hai (original TradingAgents repo ki tarah — raw return nahi).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from indiaagents.data.market import _rsi, _sma, _macd  # noqa: E402

UNIVERSE = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
    "SBIN.NS", "ITC.NS", "BHARTIARTL.NS", "LT.NS", "TATASTEEL.NS",
    "AXISBANK.NS", "KOTAKBANK.NS", "TITAN.NS", "SUNPHARMA.NS", "MARUTI.NS",
]
# NOTE: TATAMOTORS.NS Oct-2025 demerger (TMPV/TMCV) ke baad dead hai isliye
# continuous history wali TATASTEEL use kar rahe hain.

BENCH = "^NSEI"                      # NIFTY 50 benchmark (alpha baseline)
DATES = ["2026-04-01", "2026-05-01", "2026-06-01",
         "2026-07-01", "2026-08-01", "2026-09-01"]
HORIZONS = [5, 10, 20]               # trading days


def load_history(tkr: str) -> pd.DataFrame:
    df = yf.download(tkr, period="3y", interval="1d", progress=False,
                     auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"])


def quant_signal(df: pd.DataFrame, upto: str) -> dict | None:
    """Point-in-time composite signal using OUR indicator functions."""
    d = df.loc[:upto]
    if len(d) < 210:                                   # SMA200 chahiye
        return None
    close = d["Close"]
    px = float(close.iloc[-1])
    sma20 = float(_sma(close, 20).iloc[-1])
    sma50 = float(_sma(close, 50).iloc[-1])
    sma200 = float(_sma(close, 200).iloc[-1])
    rsi = _rsi(close)
    macd_line, _sig, hist = _macd(close)
    mom_1m = px / float(close.iloc[-22]) - 1 if len(close) > 22 else 0.0

    parts = {
        "px>sma20":    1 if px > sma20 else -1,
        "sma20>sma50": 1 if sma20 > sma50 else -1,
        "sma50>sma200": 1 if sma50 > sma200 else -1,
        "macd_hist":   1 if hist > 0 else -1,
        "macd_line":   1 if macd_line > 0 else -1,
        "mom_1m":      1 if mom_1m > 0 else -1,
        "rsi_extreme": (1 if rsi < 35 else -1) if (rsi < 35 or rsi > 65) else 0,
    }
    score = sum(parts.values())
    label = "BULLISH" if score >= 3 else ("BEARISH" if score <= -3 else "NEUTRAL")
    return {"date": upto, "score": score, "label": label, "rsi": round(rsi, 1),
            "mom_1m_pct": round(mom_1m * 100, 2), "parts": parts}


def fwd_returns(df: pd.DataFrame, bench: pd.DataFrame, upto: str):
    """Aligned (stock, NIFTY) forward returns from the signal day close."""
    j = pd.concat([df["Close"], bench["Close"]], axis=1,
                  keys=["s", "b"]).dropna()
    if j.empty:
        return None
    # signal-day = aakhri bar jo <= upto ho (future slice MAT karo!)
    i = j.index.searchsorted(pd.Timestamp(upto), side="right") - 1
    if i < 0:
        return None
    out = {}
    for h in HORIZONS:
        if i + h >= len(j):
            out[h] = None
            continue
        rs = j["s"].iloc[i + h] / j["s"].iloc[i] - 1
        rb = j["b"].iloc[i + h] / j["b"].iloc[i] - 1
        out[h] = {"raw": round(rs * 100, 2), "alpha": round((rs - rb) * 100, 2)}
    return out


def main():
    print("=" * 78)
    print("PART A — QUANT SIGNAL BACKTEST (data-layer quality, zero API)")
    print("=" * 78)
    bench = load_history(BENCH)
    rows, skipped = [], 0
    for tkr in UNIVERSE:
        df = load_history(tkr)
        for dt in DATES:
            if dt > datetime.now().strftime("%Y-%m-%d"):
                continue
            sig = quant_signal(df, dt)
            if sig is None:
                skipped += 1
                continue
            fr = fwd_returns(df, bench, dt)
            rows.append({"ticker": tkr, **sig, "fwd": fr})
        print(f"  {tkr:16} done ({len([r for r in rows if r['ticker']==tkr])} cells)")

    # ---------------- scoring ----------------
    print("\n" + "=" * 78)
    print("RESULTS — alpha vs NIFTY 50 (positive alpha = benchmark ko haraya)")
    print("=" * 78)
    print(f"{'Signal':10} {'N':>4} | {'5d hit%':>8} {'5d α':>7} | "
          f"{'10d hit%':>9} {'10d α':>7} | {'20d hit%':>9} {'20d α':>7}")
    print("-" * 78)
    summary = {}
    for label in ("BULLISH", "NEUTRAL", "BEARISH"):
        cells = [r for r in rows if r["label"] == label]
        line = f"{label:10} {len(cells):>4}"
        for h in HORIZONS:
            vals = [r["fwd"][h]["alpha"] for r in cells
                    if r["fwd"] and r["fwd"][h] is not None]
            if not vals:
                line += f" | {'—':>8} {'—':>7}"
                continue
            # hit = direction sahi: bullish/neutral -> alpha>0, bearish -> alpha<0
            want_pos = label != "BEARISH"
            hits = sum(1 for v in vals if (v > 0) == want_pos)
            line += f" | {hits/len(vals)*100:>7.0f}% {sum(vals)/len(vals):>+6.2f}"
            summary.setdefault(label, {})[h] = {
                "n": len(vals), "hit_rate": round(hits / len(vals) * 100, 1),
                "mean_alpha": round(sum(vals) / len(vals), 2)}
        print(line)

    bull = summary.get("BULLISH", {}).get(10, {})
    bear = summary.get("BEARISH", {}).get(10, {})
    print("-" * 78)
    if bull:
        print(f"Bullish 10d alpha: {bull['mean_alpha']:+.2f}% (hit {bull['hit_rate']}%, n={bull['n']})")
    if bear:
        print(f"Bearish 10d alpha: {bear['mean_alpha']:+.2f}% (hit {bear['hit_rate']}%, n={bear['n']})")
        print("(Bearish negative alpha + high hit = sahi 'avoid' calls)")
    print(f"\nTotal cells: {len(rows)} | skipped (insufficient history): {skipped}")

    out_path = Path(__file__).parent / "backtest_quant_results.json"
    out_path.write_text(json.dumps({"rows": rows, "summary": summary},
                                   indent=1, default=str))
    print(f"Saved: {out_path}")


if __name__ == "__main__":
    main()
