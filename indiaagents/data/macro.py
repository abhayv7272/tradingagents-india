"""Indian market context and optional FRED global macro data."""
from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timedelta

import pandas as pd
import requests
import yfinance as yf

from .health import (
    SourceResult,
    aggregate_health,
    classify_exception,
    health,
    india_today,
)
from .market import _pct
from .sources import HTTPFetchError

logger = logging.getLogger(__name__)

FRED_SERIES = [
    ("DFF", "US Fed Funds Rate"),
    ("DGS10", "US 10-Year Treasury"),
    ("DTWEXBGS", "Broad Dollar Index (DXY-proxy)"),
    ("DCOILBRENTEU", "Brent Crude (USD/bbl)"),
]


def _snap_result(ticker: str, trade_date: str | None = None) -> SourceResult:
    try:
        if trade_date:
            asof = datetime.strptime(trade_date, "%Y-%m-%d")
            history = yf.Ticker(ticker).history(
                start=(asof - timedelta(days=400)).strftime("%Y-%m-%d"),
                end=(asof + timedelta(days=1)).strftime("%Y-%m-%d"),
                auto_adjust=True,
            )
            analysis_date = asof.date()
        else:
            history = yf.Ticker(ticker).history(period="1y", auto_adjust=True)
            analysis_date = india_today()
        if not isinstance(history, pd.DataFrame) or history.empty or not {
            "Close", "High", "Low",
        }.issubset(history.columns):
            return SourceResult(None, health(
                "yahoo", f"market-context:{ticker}", "empty",
                "history returned no usable rows",
            ))
        history = history.copy()
        parsed_index = pd.to_datetime(history.index, errors="coerce")
        history.index = (parsed_index.tz_localize(None)
                         if getattr(parsed_index, "tz", None) is not None else parsed_index)
        history = history[~history.index.isna()]
        history = history[history.index.date <= analysis_date]
        history["Close"] = pd.to_numeric(history["Close"], errors="coerce")
        history = history.dropna(subset=["Close"])
        history = history[history["Close"] > 0].sort_index()
        if history.empty:
            return SourceResult(None, health(
                "yahoo", f"market-context:{ticker}", "empty",
                "no valid positive closes on/before analysis date",
            ))
        closes = history["Close"]
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else last
        month = float(closes.iloc[-22]) if len(closes) > 22 else last
        year_high, year_low = float(closes.max()), float(closes.min())
        snap = {
            "last": last, "d1": _pct(last, prev), "m1": _pct(last, month),
            "from_high": _pct(last, year_high), "from_low": _pct(last, year_low),
        }
        latest_date = history.index[-1].date()
        lag = max(0, (analysis_date - latest_date).days)
        status = "stale" if lag > 7 else "available"
        return SourceResult(snap, health(
            "yahoo", f"market-context:{ticker}", status,
            (f"latest bar is {lag} calendar days behind analysis date"
             if status == "stale" else "adjusted daily market snapshot"),
            rows=len(history), as_of=latest_date.isoformat(),
        ))
    except Exception as exc:
        status, detail = classify_exception(exc)
        return SourceResult(None, health("yahoo", f"market-context:{ticker}", status, detail))


def _snap(ticker: str, trade_date: str | None = None) -> dict | None:
    """Legacy value-only snapshot API."""
    return _snap_result(ticker, trade_date).value


def get_fred_global_macro(trade_date: str | None = None) -> dict:
    """Global macro from FRED, bounded to an analysis date when supplied."""
    api_key = (os.environ.get("FRED_API_KEY") or "").strip()
    if not api_key:
        record = health(
            "fred", "global-macro", "unconfigured",
            "FRED_API_KEY is not configured",
        )
        return {
            "fred_block": "GLOBAL MACRO (FRED): <unconfigured — FRED_API_KEY not configured>",
            "source_health": [record.to_dict()],
        }

    rows: list[str] = []
    records = []
    for series_id, label in FRED_SERIES:
        category = f"fred-series:{series_id}"
        try:
            response = requests.get(
                "https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": series_id, "api_key": api_key,
                        "file_type": "json", "sort_order": "desc", "limit": 10,
                        **({"observation_end": trade_date} if trade_date else {})},
                timeout=15,
            )
            if response.status_code != 200:
                raise HTTPFetchError(response.status_code)
            try:
                payload = response.json()
            except Exception as exc:
                raise ValueError("invalid FRED JSON") from exc
            if not isinstance(payload, dict) or not isinstance(payload.get("observations", []), list):
                raise ValueError("invalid FRED observations payload")
            observations = []
            for observation in payload.get("observations", []):
                try:
                    value = float(observation.get("value", "."))
                    observed = datetime.strptime(observation["date"], "%Y-%m-%d").date()
                    if math.isfinite(value):
                        observations.append((observed, value))
                except (KeyError, TypeError, ValueError):
                    continue
            observations.sort(key=lambda item: item[0], reverse=True)
            if trade_date:
                bound = datetime.strptime(trade_date, "%Y-%m-%d").date()
                observations = [item for item in observations if item[0] <= bound]
            if not observations:
                rows.append(f"- {label}: <empty>")
                records.append(health(
                    "fred", category, "empty", "no numeric observations on/before analysis date",
                ))
                continue
            observed, value = observations[0]
            change = ""
            if len(observations) > 1:
                previous = observations[1][1]
                change = f" (prev {previous:.2f}, {'+' if value >= previous else ''}{value - previous:.2f})"
            unit = "%" if series_id in ("DFF", "DGS10") else ""
            rows.append(f"- {label}: {value:.2f}{unit}{change} — as of {observed.isoformat()}")
            analysis_date = (datetime.strptime(trade_date, "%Y-%m-%d").date()
                             if trade_date else india_today())
            lag = max(0, (analysis_date - observed).days)
            # FRED series include holidays/release lags; ten calendar days is a
            # conservative stale threshold across this mixed-frequency set.
            status = "stale" if lag > 10 else "available"
            records.append(health(
                "fred", category, status,
                f"latest observation lag is {lag} calendar days",
                rows=len(observations), as_of=observed.isoformat(),
            ))
        except Exception as exc:
            status, detail = classify_exception(exc)
            logger.info("FRED %s failed: %s", series_id, type(exc).__name__)
            rows.append(f"- {label}: <{status}>")
            records.append(health("fred", category, status, detail))

    aggregate = aggregate_health(
        "fred", "global-macro", records,
        rows=sum(record.rows or 0 for record in records),
        detail=(f"{sum(record.status in ('available', 'stale') for record in records)}"
                f"/{len(FRED_SERIES)} series usable"),
    )
    block = ("GLOBAL MACRO (FRED, US data — FII flows & INR context):\n"
             + "\n".join(rows))
    return {"fred_block": block,
            "source_health": [aggregate.to_dict(), *(record.to_dict() for record in records)]}


def get_market_context(trade_date: str | None = None) -> dict:
    symbols = {
        "NIFTY 50": "^NSEI",
        "SENSEX": "^BSESN",
        "Bank Nifty": "^NSEBANK",
        "India VIX": "^INDIAVIX",
        "USD/INR": "USDINR=X",
        "Brent Crude (USD)": "BZ=F",
    }
    rows: list[str] = []
    records = []
    snapshots: dict[str, dict | None] = {}
    for name, symbol in symbols.items():
        result = _snap_result(symbol, trade_date)
        snapshots[symbol] = result.value
        records.append(result.health)
        snap = result.value
        if snap:
            if name == "India VIX":
                rows.append(f"- {name}: {snap['last']:.2f} (1M: {snap['m1']}%) — "
                            f"{'low volatility regime' if snap['last'] < 13 else 'elevated volatility' if snap['last'] > 18 else 'moderate volatility'}")
            elif name.startswith("USD"):
                rows.append(f"- {name}: ₹{snap['last']:.2f} (1D: {snap['d1']}%, 1M: {snap['m1']}%) — "
                            f"rupee {'weakening' if (snap['m1'] or 0) > 0.5 else 'stable/strengthening'}")
            else:
                rows.append(f"- {name}: {snap['last']:,.1f} (1D: {snap['d1']}%, 1M: {snap['m1']}%, "
                            f"52w-high se {snap['from_high']}% neeche, 52w-low se {snap['from_low']}% upar)")
        else:
            rows.append(f"- {name}: <{result.health.status}>")

    nifty = snapshots.get("^NSEI")
    regime = ""
    if nifty:
        if (nifty["from_high"] or 0) > -3:
            regime = "NIFTY apne 52-week high ke paas hai — bullish market regime."
        elif (nifty["from_high"] or 0) < -12:
            regime = "NIFTY 52-week high se kaafi neeche hai — weak/corrective market regime."
        else:
            regime = "NIFTY mid-range mein hai — neutral market regime."

    aggregate = aggregate_health(
        "yahoo", "market-context", records,
        rows=sum(record.rows or 0 for record in records),
        detail=f"{sum(record.status in ('available', 'stale') for record in records)}/{len(symbols)} instruments usable",
    )
    label = f"as of {trade_date}" if trade_date else "latest available"
    block = (f"INDIAN MARKET CONTEXT ({label}):\n" + "\n".join(rows)
             + f"\nRead: {regime}")
    return {"market_context_block": block, "nifty": nifty,
            "source_health": [aggregate.to_dict(), *(record.to_dict() for record in records)]}
