"""Confirmed support/resistance zones with explicit availability dates."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .features import atr_series, normalize_ohlcv, previous_period_levels
from .schemas import PriceZone


@dataclass(frozen=True)
class ConfirmedPivot:
    pivot_date: pd.Timestamp
    confirmation_date: pd.Timestamp
    price: float
    kind: str  # high | low
    timeframe: str = "daily"


def confirmed_pivots(df: pd.DataFrame, left: int = 3, right: int = 3,
                     timeframe: str = "daily") -> list[ConfirmedPivot]:
    """Find pivots, timestamped when the right-hand confirmation bar closes.

    A pivot at index ``i`` is not returned as available at ``i``; callers must
    filter on ``confirmation_date`` (index ``i + right``).  Equal highs/lows do
    not become pivots, avoiding ambiguous duplicate extrema.
    """
    d = normalize_ohlcv(df)
    if len(d) < left + right + 1:
        return []
    highs = d["High"].to_numpy(float)
    lows = d["Low"].to_numpy(float)
    out: list[ConfirmedPivot] = []
    for i in range(left, len(d) - right):
        h_neighbors = np.r_[highs[i-left:i], highs[i+1:i+right+1]]
        l_neighbors = np.r_[lows[i-left:i], lows[i+1:i+right+1]]
        if np.isfinite(highs[i]) and highs[i] > np.nanmax(h_neighbors):
            out.append(ConfirmedPivot(d.index[i], d.index[i + right], float(highs[i]), "high", timeframe))
        if np.isfinite(lows[i]) and lows[i] < np.nanmin(l_neighbors):
            out.append(ConfirmedPivot(d.index[i], d.index[i + right], float(lows[i]), "low", timeframe))
    return out


def _cluster(values: list[tuple[float, pd.Timestamp, str]], tolerance: float,
             kind: str, limit: int = 5) -> list[PriceZone]:
    if not values or tolerance <= 0:
        return []
    groups: list[list[tuple[float, pd.Timestamp, str]]] = []
    for item in sorted(values, key=lambda x: x[0]):
        if not groups:
            groups.append([item])
            continue
        center = float(np.median([x[0] for x in groups[-1]]))
        if abs(item[0] - center) <= tolerance:
            groups[-1].append(item)
        else:
            groups.append([item])
    zones: list[PriceZone] = []
    for group in groups:
        prices = [x[0] for x in group]
        center = float(np.median(prices))
        last = max(x[1] for x in group)
        sources = sorted({x[2] for x in group})
        half = tolerance * 0.5
        zones.append(PriceZone(
            low=round(center - half, 2), high=round(center + half, 2), kind=kind,
            touches=len(group), last_touch=last.date().isoformat(), source="+".join(sources),
        ))
    # Touch count first, then recency; price ordering happens after selection.
    zones.sort(key=lambda z: (z.touches, z.last_touch or ""), reverse=True)
    return zones[:limit]


def gap_zones(df: pd.DataFrame, as_of: pd.Timestamp | str,
              minimum_atr: float = 0.5) -> list[PriceZone]:
    """Return still-open daily gap zones known by ``as_of``.

    Gap-up zones act as support; gap-down zones as resistance.  A zone is removed
    once a later bar fully traverses it.  No intraday ordering is inferred.
    """
    d = normalize_ohlcv(df)
    cutoff = pd.Timestamp(as_of)
    d = d[d.index <= cutoff]
    if len(d) < 3:
        return []
    atr = atr_series(d).shift(1)
    zones: list[PriceZone] = []
    # Bound work and avoid treating decade-old gaps as current execution zones.
    # 180 sessions is long enough for positional setups while keeping each
    # bar-by-bar signal calculation effectively constant-memory/time.
    first = max(1, len(d) - 180)
    for i in range(first, len(d)):
        a = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
        if a <= 0:
            continue
        prev_high, prev_low = float(d["High"].iloc[i - 1]), float(d["Low"].iloc[i - 1])
        low, high = float(d["Low"].iloc[i]), float(d["High"].iloc[i])
        later = d.iloc[i + 1:]
        if low > prev_high and (low - prev_high) >= minimum_atr * a:
            # Full fill means a later low traded through the lower gap boundary.
            if later.empty or float(later["Low"].min()) > prev_high:
                zones.append(PriceZone(round(prev_high, 2), round(low, 2), "support", 1,
                                       d.index[i].date().isoformat(), "unfilled_gap_up"))
        elif (high < prev_low and (prev_low - high) >= minimum_atr * a
              and (later.empty or float(later["High"].max()) < prev_low)):
            zones.append(PriceZone(round(high, 2), round(prev_low, 2), "resistance", 1,
                                   d.index[i].date().isoformat(), "unfilled_gap_down"))
    return zones[-5:]


def build_level_context(df: pd.DataFrame, as_of: pd.Timestamp | str, *, left: int = 3,
                        right: int = 3, atr_tolerance: float = 0.35,
                        pivots: list[ConfirmedPivot] | None = None) -> dict:
    d = normalize_ohlcv(df)
    cutoff = pd.Timestamp(as_of)
    d = d[d.index <= cutoff]
    if d.empty:
        return {"supports": [], "resistances": [], "pivots": [], "period_levels": {}}
    atr = float(atr_series(d).iloc[-1])
    if not np.isfinite(atr) or atr <= 0:
        atr = float((d["High"] - d["Low"]).tail(20).median())
    tolerance = max(0.01, atr * atr_tolerance)
    all_pivots = pivots if pivots is not None else confirmed_pivots(d, left, right)
    available = [p for p in all_pivots if p.confirmation_date <= cutoff]
    current = float(d["Close"].iloc[-1])
    periods = previous_period_levels(d, cutoff)
    lows = [(p.price, p.pivot_date, f"confirmed_{p.timeframe}_pivot")
            for p in available if p.kind == "low"]
    highs = [(p.price, p.pivot_date, f"confirmed_{p.timeframe}_pivot")
             for p in available if p.kind == "high"]
    # Prior period levels are available only after period completion.
    for key in ("previous_week_low", "previous_month_low"):
        if periods.get(key) is not None:
            lows.append((float(periods[key]), cutoff, key))
    for key in ("previous_week_high", "previous_month_high"):
        if periods.get(key) is not None:
            highs.append((float(periods[key]), cutoff, key))
    supports = [z for z in _cluster(lows, tolerance, "support", limit=8) if z.low < current]
    resistances = [z for z in _cluster(highs, tolerance, "resistance", limit=8) if z.high > current]
    for z in gap_zones(d, cutoff):
        if z.kind == "support" and z.low < current:
            supports.append(z)
        elif z.kind == "resistance" and z.high > current:
            resistances.append(z)
    # Nearest first is most useful for stops/triggers, with touch count retained.
    supports = sorted(supports, key=lambda z: (abs(current - z.high), -z.touches))[:5]
    resistances = sorted(resistances, key=lambda z: (abs(z.low - current), -z.touches))[:5]
    return {
        "supports": supports, "resistances": resistances,
        "pivots": available, "period_levels": periods,
        "atr": atr, "tolerance": tolerance,
    }


def breakout_retest_state(features: pd.DataFrame, as_of: pd.Timestamp | str,
                          lookback: int = 15) -> dict:
    f = features.loc[:pd.Timestamp(as_of)]
    if f.empty or "breakout55" not in f:
        return {"confirmed_breakout": False, "retest": False, "failed": False, "level": None}
    recent = f.tail(lookback)
    hits = recent[recent["breakout55"].fillna(False)]
    if hits.empty:
        return {"confirmed_breakout": False, "retest": False,
                "failed": bool(recent["failed_breakout55"].iloc[-1]), "level": None}
    event = hits.iloc[-1]
    event_date = hits.index[-1]
    level = float(event["prior_high55"])
    after = f.loc[event_date:]
    atr = float(f.iloc[-1].get("atr14", 0) or 0)
    tol = max(0.0, atr * 0.35)
    last = f.iloc[-1]
    retest = (
        len(after) >= 2
        and float(after["Low"].min()) <= level + tol
        and float(last["Close"]) >= level
        and bool(last.get("bullish_reversal", False))
    )
    failed = float(last["Close"]) < level - tol
    return {"confirmed_breakout": True, "retest": bool(retest), "failed": bool(failed),
            "level": round(level, 2), "breakout_date": event_date.date().isoformat()}
