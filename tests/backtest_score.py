#!/usr/bin/env python3
"""PART B scoring — AI verdicts vs actual outcomes (alpha vs NIFTY)."""
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "reports" / "_backtest_llm_results.json"
HORIZONS = [5, 10, 20]


def fwd(tkr: str, bench: pd.DataFrame, d0: str):
    df = yf.download(tkr, start=d0, period="6mo", interval="1d",
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    j = pd.concat([df["Close"], bench["Close"]], axis=1, keys=["s", "b"]).dropna()
    j = j.loc[d0:]
    if len(j) < 2:
        return None
    out = {}
    for h in HORIZONS:
        if len(j) > h:
            rs = j["s"].iloc[h] / j["s"].iloc[0] - 1
            rb = j["b"].iloc[h] / j["b"].iloc[0] - 1
            out[h] = {"raw": round(rs * 100, 2), "alpha": round((rs - rb) * 100, 2)}
        else:
            out[h] = None
    return out


def main():
    recs = json.loads(RESULTS.read_text())
    bench = yf.download("^NSEI", period="1y", interval="1d",
                        progress=False, auto_adjust=True)
    if isinstance(bench.columns, pd.MultiIndex):
        bench.columns = bench.columns.get_level_values(0)

    rows = []
    for r in recs:
        if not r.get("ok"):
            rows.append({**r, "fwd": None})
            continue
        tkr = r["ticker"] + ".NS"
        rows.append({**r, "fwd": fwd(tkr, bench, r["trade_date"])})

    print("=" * 100)
    print("PART B — REAL AI REPORT BACKTEST: verdict vs actual (2026-07-15 se)")
    print("=" * 100)
    print(f"{'Stock':12} {'Verdict':18} {'Conf':>4} | {'5d raw':>7} {'5d α':>6} | "
          f"{'10d raw':>8} {'10d α':>7} | {'20d raw':>8} {'20d α':>7}")
    print("-" * 100)
    scored = []
    for r in rows:
        f = r.get("fwd") or {}
        if not f.get(10):
            print(f"{r['ticker']:12} {'(data missing)':18}")
            continue
        dec = f"{r['decision']}/{r['rating']}"
        line = f"{r['ticker']:12} {dec:18} {r['confidence']:>3}%"
        for h in HORIZONS:
            v = f.get(h)
            line += f" | {v['raw']:>+7.2f} {v['alpha']:>+6.2f}" if v else f" | {'—':>7} {'—':>6}"
        print(line)
        # direction correctness @10d alpha
        a10 = f[10]["alpha"]
        d = (r["decision"] or "").upper()
        if d == "BUY":
            correct = a10 > 0
        elif d == "SELL":
            correct = a10 < 0
        else:                       # HOLD — direction claim nahi (original ki tarah)
            correct = None
        scored.append({"ticker": r["ticker"], "decision": d, "alpha10": a10,
                       "correct": correct, "confidence": r["confidence"]})

    dir_calls = [s for s in scored if s["correct"] is not None]
    holds = [s for s in scored if s["correct"] is None]
    print("-" * 100)
    if dir_calls:
        hits = sum(1 for s in dir_calls if s["correct"])
        print(f"Directional calls (BUY/SELL): {hits}/{len(dir_calls)} sahi "
              f"({hits/len(dir_calls)*100:.0f}% hit rate) — 10d alpha vs NIFTY")
    if holds:
        alphas = [s['alpha10'] for s in holds]
        print(f"HOLD calls: {len(holds)} | inka 10d alpha: "
              f"{', '.join(f'{s[chr(39)+chr(39)] if False else s['ticker']}: {s['alpha10']:+.2f}%' for s in holds)}")
        big = [s for s in holds if abs(s["alpha10"]) > 2]
        if big:
            print(f"⚠️ HOLD calls jinka |alpha| > 2% (missed moves): "
                  f"{', '.join(s['ticker'] for s in big)}")
    out = ROOT / "reports" / "_backtest_scored.json"
    out.write_text(json.dumps({"rows": rows, "scored": scored}, indent=1,
                              default=str))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
