"""Point-in-time daily and completed-week technical features."""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

REQUIRED_OHLCV = ("Open", "High", "Low", "Close", "Volume")


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Return sorted, numeric, unique, timezone-naive OHLCV bars.

    Invalid bars are removed rather than forward-filled.  Forward-filling price or
    volume would manufacture tradable sessions and understate execution risk.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=REQUIRED_OHLCV)
    missing = [c for c in REQUIRED_OHLCV if c not in df.columns]
    if missing:
        raise ValueError(f"OHLCV columns missing: {', '.join(missing)}")
    out = df.loc[:, REQUIRED_OHLCV].copy()
    idx = pd.to_datetime(out.index, errors="coerce")
    # Daily exchange bars are labelled by the exchange-local session date.
    # Converting midnight Asia/Kolkata to UTC would shift every label one day
    # backwards; remove timezone metadata without changing the wall-date.
    out.index = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    for col in REQUIRED_OHLCV:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    before = len(out)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    positive = (out[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
    consistent = (
        (out["High"] >= out[["Open", "Close", "Low"]].max(axis=1))
        & (out["Low"] <= out[["Open", "Close", "High"]].min(axis=1))
    )
    out = out[positive & consistent]
    dropped = before - len(out)
    if dropped:
        logger.warning("Dropped %d invalid/non-positive OHLCV bar(s)", dropped)
    out["Volume"] = out["Volume"].fillna(0).clip(lower=0)
    return out


def rsi_series(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    value = 100 - 100 / (1 + rs)
    # Flat prices are neutral, not RSI=0/100.
    flat = gain.abs().lt(1e-12) & loss.abs().lt(1e-12)
    return value.mask(flat, 50.0)


def atr_series(df: pd.DataFrame, length: int = 14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def _rolling_slope(series: pd.Series, length: int) -> pd.Series:
    """OLS slope normalized by window mean; only backward-looking windows."""
    x = np.arange(length, dtype=float)
    x -= x.mean()
    denom = float(np.dot(x, x))

    def calc(values: np.ndarray) -> float:
        if not np.isfinite(values).all():
            return np.nan
        mean = float(np.mean(values))
        if abs(mean) < 1e-12:
            return 0.0
        return float(np.dot(x, values - mean) / denom / mean)

    return series.rolling(length, min_periods=length).apply(calc, raw=True)


def daily_features(df: pd.DataFrame) -> pd.DataFrame:
    d = normalize_ohlcv(df)
    if d.empty:
        return d
    out = d.copy()
    c, v = out["Close"], out["Volume"]
    out["ema10"] = c.ewm(span=10, adjust=False).mean()
    out["ema20"] = c.ewm(span=20, adjust=False).mean()
    for n in (20, 50, 200):
        out[f"sma{n}"] = c.rolling(n, min_periods=n).mean()
    out["rsi14"] = rsi_series(c)
    out["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    out["atr14"] = atr_series(out)
    mid = c.rolling(20, min_periods=20).mean()
    std = c.rolling(20, min_periods=20).std(ddof=1)
    out["boll_width"] = (4 * std / mid.replace(0, np.nan)).clip(lower=0)
    out["volume_avg20"] = v.rolling(20, min_periods=20).mean()
    out["volume_ratio"] = v / out["volume_avg20"].replace(0, np.nan)
    ret = c.pct_change(fill_method=None)
    out["volatility10"] = ret.rolling(10, min_periods=10).std(ddof=1)
    out["volatility20"] = ret.rolling(20, min_periods=20).std(ddof=1)
    out["volatility_ratio"] = out["volatility10"] / out["volatility20"].replace(0, np.nan)
    # Thresholds use the previous bar's distribution.  Today's width cannot alter
    # the threshold against which today's contraction/expansion is classified.
    width_q25 = out["boll_width"].shift(1).rolling(60, min_periods=30).quantile(0.25)
    width_q75 = out["boll_width"].shift(1).rolling(60, min_periods=30).quantile(0.75)
    out["volatility_contraction"] = out["boll_width"] <= width_q25
    out["volatility_expansion"] = out["boll_width"] >= width_q75
    prev_close = c.shift(1)
    out["gap_pct"] = (out["Open"] / prev_close - 1) * 100
    out["gap_atr"] = (out["Open"] - prev_close) / out["atr14"].shift(1).replace(0, np.nan)
    # Breakout levels are shifted: a close never compares with its own high.
    for n in (20, 55):
        out[f"prior_high{n}"] = out["High"].shift(1).rolling(n, min_periods=n).max()
        out[f"prior_low{n}"] = out["Low"].shift(1).rolling(n, min_periods=n).min()
        out[f"breakout{n}"] = c > out[f"prior_high{n}"]
        out[f"breakdown{n}"] = c < out[f"prior_low{n}"]
    peak = c.rolling(252, min_periods=20).max()
    out["drawdown252"] = c / peak - 1
    out["trend_slope20"] = _rolling_slope(c, 20)
    out["range20_pct"] = (
        out["High"].shift(1).rolling(20, min_periods=20).max()
        / out["Low"].shift(1).rolling(20, min_periods=20).min() - 1
    )
    out["bullish_reversal"] = (
        (out["Close"] > out["Open"])
        & (out["Close"] > out["Close"].shift(1))
        & ((out["Close"] - out["Low"]) >= (out["High"] - out["Low"]) * 0.6)
    )
    out["failed_breakout55"] = (
        out["breakout55"].shift(1).rolling(5, min_periods=1).max().fillna(0).astype(bool)
        & (c < out["prior_high55"])
    )
    return out


def completed_weekly_ohlcv(df: pd.DataFrame, as_of: pd.Timestamp | str | None = None) -> pd.DataFrame:
    """Aggregate only weeks whose Friday label is on/before ``as_of``.

    A Wednesday analysis therefore sees last Friday's completed candle, never a
    partial candle labelled with the coming Friday.  This is the central weekly
    look-ahead guard.
    """
    d = normalize_ohlcv(df)
    if d.empty:
        return d
    cutoff = pd.Timestamp(as_of) if as_of is not None else d.index[-1]
    d = d[d.index <= cutoff]
    weekly = d.resample("W-FRI", label="right", closed="right").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    }).dropna(subset=["Close"])
    return weekly[weekly.index <= cutoff]


def weekly_features(df: pd.DataFrame, as_of: pd.Timestamp | str | None = None) -> pd.DataFrame:
    w = completed_weekly_ohlcv(df, as_of)
    if w.empty:
        return w
    out = w.copy()
    c = out["Close"]
    for n in (10, 20, 40):
        out[f"sma{n}"] = c.rolling(n, min_periods=n).mean()
    out["sma20_slope"] = _rolling_slope(out["sma20"], 4)
    out["rsi14"] = rsi_series(c)
    out["macd"] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]
    positive = (
        (c > out["sma20"])
        & (out["sma20"] > out["sma40"])
        & (out["sma20_slope"] > 0)
        & (out["rsi14"] >= 50)
    )
    negative = (
        (c < out["sma20"])
        & (out["sma20"] < out["sma40"])
        & (out["sma20_slope"] < 0)
        & (out["rsi14"] < 50)
    )
    out["trend_state"] = np.select([positive, negative], ["positive", "negative"], default="neutral")
    out["prior_week_high"] = out["High"].shift(1)
    out["prior_week_low"] = out["Low"].shift(1)
    return out


def previous_period_levels(df: pd.DataFrame, as_of: pd.Timestamp | str) -> dict[str, float | None]:
    d = normalize_ohlcv(df)
    cutoff = pd.Timestamp(as_of)
    d = d[d.index <= cutoff]
    result: dict[str, float | None] = {
        "previous_week_high": None, "previous_week_low": None,
        "previous_month_high": None, "previous_month_low": None,
    }
    for freq, prefix in (("W-FRI", "previous_week"), ("ME", "previous_month")):
        try:
            bars = d.resample(freq, label="right", closed="right").agg({"High": "max", "Low": "min"})
        except ValueError:  # pandas <2.2 uses M instead of ME
            bars = d.resample("M", label="right", closed="right").agg({"High": "max", "Low": "min"})
        bars = bars[bars.index < cutoff.normalize()]
        if len(bars):
            result[f"{prefix}_high"] = float(bars.iloc[-1]["High"])
            result[f"{prefix}_low"] = float(bars.iloc[-1]["Low"])
    return result


def finite_or_none(value, digits: int = 4):
    try:
        x = float(value)
        return round(x, digits) if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None
