#!/usr/bin/env python3
"""
QLIB-STYLE POC for Indian stocks (zero API cost — sirf free yfinance data)
==========================================================================
Sawaal: "Qlib jaisa ML approach implement karne se improvement kitna aayega?"

Method (Qlib ke quick-start LightGBM workflow se inspired):
  - Universe: 40 liquid NSE stocks
  - Features: ~30 Alpha158-lite factors (KBAR, ROC, MA-ratios, STD, volume, RSI,
    MACD, Bollinger, 52w position)
  - Label: agle 10-din ka return (point-in-time, koi future leak nahi)
  - Model: HistGradientBoosting (sklearn — LightGBM ka built-in cousin)
  - Split: TIME split (train 70% purane din, validate 30% naye din) — overfitting
    pakadne ke liye shuffle NAHI
  - Metrics (Qlib standard): Rank IC, ICIR, IC>0 rate, top-vs-bottom quintile spread
  - Baselines: (1) hamara current 7-part composite signal, (2) simple 1-month momentum
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC",
    "BHARTIARTL", "LT", "TATASTEEL", "AXISBANK", "KOTAKBANK", "TITAN",
    "SUNPHARMA", "MARUTI", "BAJFINANCE", "HCLTECH", "TECHM", "WIPRO",
    "ULTRACEMCO", "NESTLEIND", "HINDUNILVR", "TATACONSUM", "POWERGRID",
    "NTPC", "ONGC", "COALINDIA", "JSWSTEEL", "HINDALCO", "ADANIENT",
    "ADANIPORTS", "TRENT", "DMART", "SIEMENS", "ABB", "BEL", "HAL",
    "IRCTC", "IRFC", "LICI",
]
FWD = 10          # label horizon (trading days)


def factors(df: pd.DataFrame) -> pd.DataFrame:
    """Alpha158-lite — sab point-in-time (rolling history only)."""
    c, o, h, l, v = df["Close"], df["Open"], df["High"], df["Low"], df["Volume"]
    f = pd.DataFrame(index=df.index)
    # KBAR
    f["kbar_co"] = (c - o) / o
    f["kbar_hl"] = (h - l) / o
    f["kbar_ch"] = c / h - 1
    f["kbar_cl"] = c / l - 1
    # ROC
    for n in (5, 10, 20, 60):
        f[f"roc{n}"] = c / c.shift(n) - 1
    # MA ratios
    for n in (5, 10, 20, 60):
        f[f"c_ma{n}"] = c / c.rolling(n).mean() - 1
    f["ma5_10"] = c.rolling(5).mean() / c.rolling(10).mean() - 1
    f["ma10_20"] = c.rolling(10).mean() / c.rolling(20).mean() - 1
    f["ma20_60"] = c.rolling(20).mean() / c.rolling(60).mean() - 1
    # Volatility
    r = c.pct_change()
    f["std20"] = r.rolling(20).std()
    f["std60"] = r.rolling(60).std()
    f["std5_20"] = r.rolling(5).std() / (r.rolling(20).std() + 1e-9)
    # Volume
    f["vol_5"] = v / (v.rolling(5).mean() + 1e-9) - 1
    f["vol_20"] = v / (v.rolling(20).mean() + 1e-9) - 1
    f["vol_ratio"] = v.rolling(5).mean() / (v.rolling(20).mean() + 1e-9)
    # RSI(14)
    d = c.diff()
    f["rsi14"] = (d.clip(lower=0).rolling(14).mean()
                  / (d.abs().rolling(14).mean() + 1e-9))
    # MACD hist / price
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    f["macd"] = ((ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()) / c
    # Bollinger position
    m20, s20 = c.rolling(20).mean(), c.rolling(20).std()
    f["boll"] = (c - m20) / (2 * s20 + 1e-9)
    # 52w position + window extremes
    lo52, hi52 = c.rolling(252).min(), c.rolling(252).max()
    f["pos52"] = (c - lo52) / (hi52 - lo52 + 1e-9)
    f["c_max20"] = c / c.rolling(20).max() - 1
    f["c_min20"] = c / c.rolling(20).min() - 1
    return f


def composite_signal(df: pd.DataFrame) -> pd.Series:
    """Hamara CURRENT 7-part composite (Part A wala) — baseline."""
    c = df["Close"]
    sma20, sma50, sma200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    hist = (ema12 - ema26) - (ema12 - ema26).ewm(span=9).mean()
    d = c.diff()
    rsi = 100 - 100 / (1 + d.clip(lower=0).ewm(alpha=1/14).mean()
                       / (-d.clip(upper=0)).ewm(alpha=1/14).mean().replace(0, 1e-9))
    mom = c / c.shift(22) - 1
    parts = [(c > sma20).astype(int) * 2 - 1, (sma20 > sma50).astype(int) * 2 - 1,
             (sma50 > sma200).astype(int) * 2 - 1, (hist > 0).astype(int) * 2 - 1,
             (ema12 - ema26 > 0).astype(int) * 2 - 1, (mom > 0).astype(int) * 2 - 1]
    parts.append(pd.Series(np.where(rsi < 35, 1, np.where(rsi > 65, -1, 0)), index=c.index))
    return sum(parts)


def load(tkr: str) -> pd.DataFrame | None:
    df = yf.download(tkr + ".NS", period="6y", interval="1d",
                     progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Close"]) if not df.empty else None


def main():
    print("Data download (40 NSE stocks, 6y daily)...")
    feats, labels, base_scores, base_mom = {}, {}, {}, {}
    for t in UNIVERSE:
        df = load(t)
        if df is None or len(df) < 320:
            print(f"  {t:14} SKIP (data nahi/short)")
            continue
        f = factors(df)
        lab = df["Close"].shift(-FWD) / df["Close"] - 1        # future 10d return
        sig = composite_signal(df)
        mom = df["Close"] / df["Close"].shift(22) - 1
        feats[t], labels[t] = f, lab
        base_scores[t], base_mom[t] = sig, mom
    tickers = list(feats.keys())
    print(f"  {len(tickers)} stocks ready")

    # panel banao: (date, ticker) rows
    X, y, meta = [], [], []
    for t in tickers:
        f, lab = feats[t].dropna(), labels[t]
        common = f.index.intersection(lab.dropna().index)
        for dt in common:
            X.append(f.loc[dt].values); y.append(lab[dt]); meta.append((dt, t))
    X, y = np.array(X), np.array(y)
    dates = pd.Index([m[0] for m in meta])
    tk_col = np.array([m[1] for m in meta])
    print(f"Panel: {len(X)} rows x {X.shape[1]} factors")

    # TIME split (70/30) — shuffle NAHI (Qlib discipline)
    uniq = dates.unique().sort_values()
    cut = uniq[int(len(uniq) * 0.7)]
    tr, va = dates <= cut, dates > cut
    print(f"Train: {tr.sum()} rows ({uniq.min().date()} → {cut.date()})")
    print(f"Valid: {va.sum()} rows ({uniq[uniq > cut].min().date()} → {uniq.max().date()})")

    from sklearn.ensemble import HistGradientBoostingRegressor
    model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.05, max_depth=6,
        min_samples_leaf=100, l2_regularization=1.0, random_state=42)
    model.fit(X[tr], y[tr])
    pred = model.predict(X)

    # ---- Qlib-style evaluation: daily RANK IC ----
    def daily_ic(score_getter, mask):
        ics = []
        for dt in sorted(set(dates[mask])):
            rows = np.where((dates == dt) & mask)[0]
            if len(rows) < 15:
                continue
            ic, _ = stats.spearmanr(score_getter(rows), y[rows])
            ics.append(ic)
        ics = np.array(ics)
        return ics.mean(), ics.mean() / (ics.std() + 1e-9), (ics > 0).mean(), len(ics)

    print("\n" + "=" * 72)
    print(f"VALIDATION RESULTS — Rank IC (10-day forward return, {len(tickers)} NSE stocks)")
    print("=" * 72)
    rows = []
    for name, getter in (
        ("QLIB-STYLE ML (Alpha158-lite + HistGB)", lambda r: pred[r]),
        ("Current composite (7-part)", lambda r: _map_scores(base_scores, tk_col, dates, r)),
        ("Baseline: 1-month momentum", lambda r: _map_scores(base_mom, tk_col, dates, r)),
    ):
        ic, icir, pos, n = daily_ic(getter, va)
        rows.append((name, ic, icir, pos, n))
        print(f"{name:42} IC={ic:+.4f}  ICIR={icir:+.3f}  IC>0: {pos:.0%}  (days={n})")

    # quintile spread for ML model
    spreads, top_ret, bot_ret = [], [], []
    for dt in sorted(set(dates[va])):
        rows_i = np.where((dates == dt) & va)[0]
        if len(rows_i) < 15:
            continue
        order = np.argsort(pred[rows_i])
        q = len(order) // 5
        top, bot = order[-q:], order[:q]
        top_ret.append(y[rows_i][top].mean()); bot_ret.append(y[rows_i][bot].mean())
        spreads.append(y[rows_i][top].mean() - y[rows_i][bot].mean())
    print("-" * 72)
    sp = float(np.mean(spreads)) * 100
    ann = (1 + float(np.mean(spreads))) ** (252 / FWD) - 1
    print(f"ML quintile spread (10d): TOP 20% avg {np.mean(top_ret)*100:+.2f}% vs "
          f"BOTTOM 20% avg {np.mean(bot_ret)*100:+.2f}% → spread {sp:+.2f}% per 10d "
          f"(long-short ~{ann:+.0%} annualized,IGNORE costs)")
    ml_ic = rows[0][1]; base_ic = rows[1][1]
    print(f"\n>>> ML IC vs current composite IC: {ml_ic:+.4f} vs {base_ic:+.4f} "
          f"(|IC| improvement: {abs(ml_ic)/max(abs(base_ic),1e-9):.1f}x)")

    out = Path(__file__).parent / "qlib_poc_results.json"
    import json
    out.write_text(json.dumps({
        "stocks": tickers, "rows": len(X), "factors": int(X.shape[1]),
        "train_until": str(cut.date()), "results": [
            {"name": n, "ic": round(i, 4), "icir": round(r, 3),
             "ic_positive_rate": round(p, 3), "days": d} for n, i, r, p, d in rows],
        "quintile_spread_10d_pct": round(float(np.mean(spreads)), 3),
    }, indent=1))
    print(f"Saved: {out}")


def _map_scores(score_dict, tk_col, dates, rows):
    """Baseline scores ko panel rows pe map karo."""
    out = []
    for i in rows:
        dt, t = dates[i], tk_col[i]
        s = score_dict[t]
        out.append(s.loc[dt] if dt in s.index else np.nan)
    return np.array(out, dtype=float)


if __name__ == "__main__":
    sys.exit(main())
