"""
Indian market context — NIFTY 50, SENSEX, Bank Nifty, India VIX, USD/INR,
plus Brent crude. Global macro (Fed rate, US 10Y, DXY, Brent) comes from FRED
(free key). This grounds every agent in the broader market state.
"""
from __future__ import annotations

import logging
import os

import requests
import yfinance as yf

from .market import _pct

logger = logging.getLogger(__name__)

# FRED series that matter for Indian markets (Fed/FII flows, dollar, crude)
FRED_SERIES = [
    ("DFF", "US Fed Funds Rate"),
    ("DGS10", "US 10-Year Treasury"),
    ("DTWEXBGS", "Broad Dollar Index (DXY-proxy)"),
    ("DCOILBRENTEU", "Brent Crude (USD/bbl)"),
]


def _snap(ticker: str) -> dict | None:
    try:
        h = yf.Ticker(ticker).history(period="1y")
        if h.empty:
            return None
        c = h["Close"]
        last = float(c.iloc[-1])
        prev = float(c.iloc[-2]) if len(c) > 1 else last
        m1 = float(c.iloc[-22]) if len(c) > 22 else last
        y_hi, y_lo = float(h["Close"].max()), float(h["Close"].min())
        return {
            "last": last, "d1": _pct(last, prev), "m1": _pct(last, m1),
            "from_high": _pct(last, y_hi), "from_low": _pct(last, y_lo),
        }
    except Exception:
        return None


def get_fred_global_macro() -> dict:
    """Global macro from FRED (free key) — Fed, US yields, dollar, crude.
    These drive FII flows into India, INR, and OMC/energy stocks."""
    api_key = (os.environ.get("FRED_API_KEY") or "").strip()
    if not api_key:
        return {"fred_block": "GLOBAL MACRO (FRED): <FRED_API_KEY not configured>"}
    rows = []
    for series_id, label in FRED_SERIES:
        try:
            r = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": series_id, "api_key": api_key,
                        "file_type": "json", "sort_order": "desc", "limit": 2},
                timeout=15)
            if r.status_code != 200:
                rows.append(f"- {label}: <unavailable>")
                continue
            obs = [o for o in r.json().get("observations", []) if o.get("value", ".") != "."]
            if not obs:
                rows.append(f"- {label}: <no data>")
                continue
            latest = obs[0]
            val = float(latest["value"])
            chg = ""
            if len(obs) > 1:
                prev = float(obs[1]["value"])
                if prev:
                    chg = f" (prev {prev:.2f}, {'+' if val >= prev else ''}{val - prev:.2f})"
            unit = "%" if series_id in ("DFF", "DGS10") else ""
            rows.append(f"- {label}: {val:.2f}{unit}{chg} — as of {latest['date']}")
        except Exception as e:
            logger.info("FRED %s failed: %s", series_id, e)
            rows.append(f"- {label}: <unavailable>")
    block = ("GLOBAL MACRO (FRED, US data — FII flows & INR ke liye matter karta hai):\n"
             + "\n".join(rows))
    return {"fred_block": block}


def get_market_context() -> dict:
    syms = {
        "NIFTY 50": "^NSEI",
        "SENSEX": "^BSESN",
        "Bank Nifty": "^NSEBANK",
        "India VIX": "^INDIAVIX",
        "USD/INR": "USDINR=X",
        "Brent Crude (USD)": "BZ=F",
    }
    rows = []
    for name, sym in syms.items():
        s = _snap(sym)
        if s:
            if name == "India VIX":
                rows.append(f"- {name}: {s['last']:.2f} (1M: {s['m1']}%) — "
                            f"{'low volatility regime' if s['last'] < 13 else 'elevated volatility' if s['last'] > 18 else 'moderate volatility'}")
            elif name.startswith("USD"):
                rows.append(f"- {name}: ₹{s['last']:.2f} (1D: {s['d1']}%, 1M: {s['m1']}%) — "
                            f"rupee {'weakening' if (s['m1'] or 0) > 0.5 else 'stable/strengthening'}")
            else:
                rows.append(f"- {name}: {s['last']:,.1f} (1D: {s['d1']}%, 1M: {s['m1']}%, "
                            f"52w-high se {s['from_high']}% neeche, 52w-low se {s['from_low']}% upar)")
        else:
            rows.append(f"- {name}: <unavailable>")

    nifty = _snap("^NSEI")
    regime = ""
    if nifty:
        if (nifty["from_high"] or 0) > -3:
            regime = "NIFTY apne 52-week high ke paas hai — bullish market regime."
        elif (nifty["from_high"] or 0) < -12:
            regime = "NIFTY 52-week high se kaafi neeche hai — weak/corrective market regime."
        else:
            regime = "NIFTY mid-range mein hai — neutral market regime."

    block = ("INDIAN MARKET CONTEXT (aaj ka):\n" + "\n".join(rows) +
             f"\nRead: {regime}")
    return {"market_context_block": block, "nifty": nifty}
