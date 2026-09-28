#!/usr/bin/env python3
"""
ML Score Model — offline training (sandbox/CI mein chalao, app mein NAHI)
========================================================================
Qlib-inspired: Alpha158-lite factors (indiaagents/data/quant.py se — single
source of truth) + HistGradientBoosting (LightGBM ka sklearn cousin).

Output:
  indiaagents/models/ml_score_v1.joblib   (model)
  indiaagents/models/ml_calib_v1.json     (score calibration + metadata)

Evaluation: 2-fold walk-forward (time-ordered, shuffle NAHI).
Run: python3 scripts/train_ml_model.py   (free yfinance data, zero API cost)
Retrain cadence: monthly/quarterly (IC girne pe bhi).
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from indiaagents.data.quant import compute_factors, FEATURE_COLS  # noqa: E402

warnings.filterwarnings("ignore")

UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "ITC",
    "BHARTIARTL", "LT", "TATASTEEL", "AXISBANK", "KOTAKBANK", "TITAN",
    "SUNPHARMA", "MARUTI", "BAJFINANCE", "HCLTECH", "TECHM", "WIPRO",
    "ULTRACEMCO", "NESTLEIND", "HINDUNILVR", "TATACONSUM", "POWERGRID",
    "NTPC", "ONGC", "COALINDIA", "JSWSTEEL", "HINDALCO", "ADANIENT",
    "ADANIPORTS", "TRENT", "DMART", "SIEMENS", "ABB", "BEL", "HAL",
    "IRCTC", "IRFC", "LICI", "INDUSINDBK", "BAJAJFINSV", "CIPLA",
    "DRREDDY", "DIVISLAB", "APOLLOHOSP", "TECHM", "M&M", "HEROMOTOCO",
    "EICHERMOT",
]
FWD = 10


def build_panel():
    X, y, dates, tks = [], [], [], []
    for t in UNIVERSE:
        try:
            df = yf.download(t + ".NS", period="6y", interval="1d",
                             progress=False, auto_adjust=True)
        except Exception:
            continue
        if df is None or df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if len(df) < 320:
            continue
        f = compute_factors(df).dropna()
        lab = (df["Close"].shift(-FWD) / df["Close"] - 1).dropna()
        common = f.index.intersection(lab.index)
        f, lab = f.loc[common], lab.loc[common]
        for dt in common:
            X.append(f.loc[dt].values)
            y.append(lab[dt])
            dates.append(dt)
            tks.append(t)
    return (np.array(X), np.array(y), pd.Index(dates),
            np.array(tks), sorted(set(tks)))


def daily_rank_ic(pred, y, dates, mask):
    ics = []
    for dt in sorted(set(dates[mask])):
        rows = np.where((dates == dt) & mask)[0]
        if len(rows) < 15:
            continue
        ic, _ = stats.spearmanr(pred[rows], y[rows])
        ics.append(ic)
    ics = np.array(ics)
    if len(ics) == 0:
        return 0.0, 0.0
    return float(ics.mean()), float(ics.mean() / (ics.std() + 1e-9))


def main():
    print("Panel build ho raha hai (50 NSE stocks, 6y)...")
    X, y, dates, tks, tickers = build_panel()
    print(f"Stocks: {len(tickers)} | rows: {len(X)} | factors: {X.shape[1]}")

    uniq = dates.unique().sort_values()
    n = len(uniq)

    # ---- 2-fold walk-forward validation ----
    from sklearn.ensemble import HistGradientBoostingRegressor
    ics = []
    for k, (a, b) in enumerate([(0.5, 0.75), (0.75, 1.0)]):
        cut_tr, cut_va = uniq[int(n * a)], uniq[int(n * b) - 1]
        tr, va = (dates <= cut_tr), (dates > cut_tr) & (dates <= cut_va)
        m = HistGradientBoostingRegressor(
            max_iter=400, learning_rate=0.05, max_depth=6,
            min_samples_leaf=100, l2_regularization=1.0, random_state=42)
        m.fit(X[tr], y[tr])
        pred = m.predict(X)
        ic, icir = daily_rank_ic(pred, y, dates, va)
        ics.append(ic)
        print(f"Fold {k+1}: train → {cut_tr.date()} | valid {cut_tr.date()}→{cut_va.date()} "
              f"| IC={ic:+.4f} ICIR={icir:+.3f}")

    val_ic = float(np.mean(ics))
    print(f"Mean walk-forward IC: {val_ic:+.4f}")

    # ---- final model: saara data ----
    model = HistGradientBoostingRegressor(
        max_iter=400, learning_rate=0.05, max_depth=6,
        min_samples_leaf=100, l2_regularization=1.0, random_state=42)
    model.fit(X, y)
    full_pred = model.predict(X)

    import joblib
    out_dir = ROOT / "indiaagents" / "models"
    out_dir.mkdir(exist_ok=True)
    joblib.dump(model, out_dir / "ml_score_v1.joblib")

    quantiles = [float(np.quantile(full_pred, q / 100))
                 for q in range(0, 101, 2)]        # 51 points, ~2% granularity
    meta = {
        "trained": pd.Timestamp.now().strftime("%Y-%m-%d"),
        "universe": tickers,
        "n_rows": int(len(X)),
        "factors": FEATURE_COLS,
        "val_ic": round(val_ic, 4),
        "folds_ic": [round(i, 4) for i in ics],
        "label": f"{FWD}-day forward return",
        "quantiles": quantiles,
    }
    (out_dir / "ml_calib_v1.json").write_text(json.dumps(meta, indent=1))

    mb = (out_dir / "ml_score_v1.joblib").stat().st_size / 1e6
    print(f"\nSaved: ml_score_v1.joblib ({mb:.1f} MB) + ml_calib_v1.json")
    print(f"Deploy note: retrain monthly — IC < 0.01 ho to model card hide karo.")


if __name__ == "__main__":
    main()
