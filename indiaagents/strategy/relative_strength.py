"""Point-in-time stock/benchmark/sector relative-strength calculations."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .features import normalize_ohlcv

# Maintainable Yahoo symbols for broad NSE sector indices.  A missing mapping is
# represented as unavailable; the engine never guesses one from company prose.
SECTOR_INDEX_MAP: dict[str, str] = {
    "basic materials": "^CNXMETAL", "metals": "^CNXMETAL",
    "consumer cyclical": "^CNXAUTO", "auto": "^CNXAUTO",
    "consumer defensive": "^CNXFMCG", "fmcg": "^CNXFMCG",
    "energy": "^CNXENERGY", "oil & gas": "^CNXENERGY",
    "financial services": "^NSEBANK", "financial": "^NSEBANK", "banks": "^NSEBANK",
    "healthcare": "^CNXPHARMA", "pharmaceuticals": "^CNXPHARMA",
    "industrials": "^CNXINFRA", "infrastructure": "^CNXINFRA",
    "real estate": "^CNXREALTY", "technology": "^CNXIT", "information technology": "^CNXIT",
    "utilities": "^CNXENERGY", "communication services": "^CNXMEDIA",
}

# Explicit symbol overrides are auditable and avoid fuzzy classification.
SYMBOL_SECTOR_OVERRIDES: dict[str, str] = {
    "TCS": "^CNXIT", "INFY": "^CNXIT", "HCLTECH": "^CNXIT", "WIPRO": "^CNXIT", "TECHM": "^CNXIT",
    "HDFCBANK": "^NSEBANK", "ICICIBANK": "^NSEBANK", "SBIN": "^NSEBANK", "AXISBANK": "^NSEBANK",
    "SUNPHARMA": "^CNXPHARMA", "CIPLA": "^CNXPHARMA", "DRREDDY": "^CNXPHARMA",
    "MARUTI": "^CNXAUTO", "TMPV": "^CNXAUTO", "M&M": "^CNXAUTO", "BAJAJ-AUTO": "^CNXAUTO",
    "TATASTEEL": "^CNXMETAL", "HINDALCO": "^CNXMETAL", "JSWSTEEL": "^CNXMETAL",
    "RELIANCE": "^CNXENERGY", "ONGC": "^CNXENERGY", "NTPC": "^CNXENERGY",
}


def sector_index_for(ticker: str, sector: str | None = None) -> str | None:
    stem = str(ticker or "").upper().replace(".NS", "").replace(".BO", "")
    if stem in SYMBOL_SECTOR_OVERRIDES:
        return SYMBOL_SECTOR_OVERRIDES[stem]
    return SECTOR_INDEX_MAP.get(str(sector or "").strip().lower())


def _slope(values: pd.Series, length: int = 63) -> float | None:
    y = np.log(values.replace(0, np.nan)).dropna().tail(length).to_numpy(float)
    if len(y) < min(20, length) or not np.isfinite(y).all():
        return None
    x = np.arange(len(y), dtype=float)
    value = float(np.polyfit(x, y, 1)[0] * 252 * 100)
    return round(value, 2) if math.isfinite(value) else None


def _relative(stock: pd.Series, reference: pd.Series | None, label: str) -> dict:
    unavailable = {"status": "unavailable", "reference": label, "1m_pct": None,
                   "3m_pct": None, "6m_pct": None, "slope_ann_pct": None, "trend": "unavailable"}
    if reference is None or reference.empty:
        return unavailable
    pair = pd.concat([stock.rename("stock"), reference.rename("ref")], axis=1).dropna()
    if len(pair) < 22:
        return unavailable
    ratio = pair["stock"] / pair["ref"].replace(0, np.nan)
    result = {"status": "available", "reference": label}
    for name, days in (("1m_pct", 21), ("3m_pct", 63), ("6m_pct", 126)):
        if len(pair) > days and pair["stock"].iloc[-1-days] > 0 and pair["ref"].iloc[-1-days] > 0:
            stock_return = pair["stock"].iloc[-1] / pair["stock"].iloc[-1-days] - 1
            ref_return = pair["ref"].iloc[-1] / pair["ref"].iloc[-1-days] - 1
            result[name] = round(float((stock_return - ref_return) * 100), 2)
        else:
            result[name] = None
    result["slope_ann_pct"] = _slope(ratio)
    slope = result["slope_ann_pct"]
    r3 = result["3m_pct"]
    result["trend"] = (
        "positive" if slope is not None and slope > 0 and (r3 is None or r3 > 0)
        else "negative" if slope is not None and slope < 0 and (r3 is None or r3 < 0)
        else "mixed"
    )
    return result


def relative_strength(stock_df: pd.DataFrame, nifty_df: pd.DataFrame | None,
                      sector_df: pd.DataFrame | None = None,
                      sector_symbol: str | None = None,
                      peer_df: pd.DataFrame | None = None) -> dict:
    stock = normalize_ohlcv(stock_df)["Close"]
    nifty = normalize_ohlcv(nifty_df)["Close"] if nifty_df is not None and not nifty_df.empty else None
    sector = normalize_ohlcv(sector_df)["Close"] if sector_df is not None and not sector_df.empty else None
    peer = normalize_ohlcv(peer_df)["Close"] if peer_df is not None and not peer_df.empty else None
    n = _relative(stock, nifty, "NIFTY 50")
    s = _relative(stock, sector, sector_symbol or "sector index")
    p = _relative(stock, peer, "configured peer basket")
    # Agreement means stock trend and sector absolute trend point the same way.
    sector_regime = "unavailable"
    if sector is not None and len(sector.dropna()) >= 50:
        sm = sector.rolling(50).mean()
        sector_regime = "positive" if sector.iloc[-1] > sm.iloc[-1] else "negative"
    stock_regime = "positive" if len(stock) >= 50 and stock.iloc[-1] > stock.rolling(50).mean().iloc[-1] else "negative"
    agreement = sector_regime != "unavailable" and stock_regime == sector_regime
    return {"nifty": n, "sector": s, "peer": p, "stock_regime": stock_regime,
            "sector_regime": sector_regime, "regime_agreement": agreement}
