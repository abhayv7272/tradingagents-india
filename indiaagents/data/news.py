"""Google News India RSS adapters with bounded historical windows.

Google News is a discovery feed, not a complete immutable news archive.  Every
result carries structured health so transport failure is not confused with a
legitimate zero-headline response.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from .health import (
    IST,
    SourceHealth,
    aggregate_health,
    classify_exception,
    health,
    india_today,
)
from .sources import _cached_get

logger = logging.getLogger(__name__)

INDIA_MACRO_QUERIES = [
    "RBI repo rate interest rate decision",
    "India inflation CPI IIP data",
    "Nifty Sensex stock market today",
    "SEBI regulation news",
    "India GDP growth economy",
    "crude oil price impact India",
    "rupee dollar USD INR",
    "India stock market outlook FII DII",
    "Union Budget tax India",
    "monsoon India economy",
]


class FeedItems(list):
    """List-compatible parser output carrying one request's health record."""

    def __init__(self, values=(), *, source_health: SourceHealth):
        super().__init__(values)
        self.source_health = source_health


def parse_google_news_rss(raw: bytes | str, limit: int = 10) -> list[dict]:
    """Parse an RSS fixture without network access."""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "ignore")
    root = ET.fromstring(raw)
    items: list[dict] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source_node = item.find("source")
        source = (source_node.text or "").strip() if source_node is not None else ""
        published = (item.findtext("pubDate") or "").strip()
        dt = None
        try:
            dt = parsedate_to_datetime(published)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
        except (TypeError, ValueError, OverflowError):
            pass
        if title:
            items.append({
                "title": title,
                "source": source,
                "date": dt,
                "link": (item.findtext("link") or "").strip(),
            })
        if len(items) >= limit:
            break
    return items


def _fetch_rss(query: str, when: str = "7d", limit: int = 10,
               after: str | None = None, before: str | None = None) -> list[dict]:
    window = (f"+after:{after}+before:{before}" if after and before
              else f"+when:{when}")
    url = (f"https://news.google.com/rss/search?q={quote_plus(query)}{window}"
           f"&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        raw = _cached_get(url, ttl_hours=1, timeout=15)
        items = parse_google_news_rss(raw, limit=limit)
        if after and before:
            lower = datetime.strptime(after, "%Y-%m-%d").date()
            upper = datetime.strptime(before, "%Y-%m-%d").date()
            # A historical headline without a parseable publication date cannot
            # be proven point-in-time and is therefore dropped.
            items = [item for item in items if item["date"] is not None
                     and lower <= item["date"].astimezone(IST).date() < upper]
        status = "available" if items else "empty"
        detail = "RSS parsed" if items else "valid RSS returned no in-window headlines"
        return FeedItems(items, source_health=health(
            "google-news", "rss-query", status, detail, rows=len(items),
            as_of=(max(item["date"] for item in items if item["date"] is not None)
                   .astimezone(IST).date().isoformat()
                   if any(item["date"] is not None for item in items) else None),
            cached=bool(getattr(raw, "cached", False)),
        ))
    except Exception as exc:
        status, detail = classify_exception(exc)
        logger.warning("Google News RSS failed for %r: %s", query, type(exc).__name__)
        return FeedItems([], source_health=health(
            "google-news", "rss-query", status, detail,
        ))


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for item in items:
        key = _clean_title(item["title"]).lower()[:60]
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _fmt_date(dt) -> str:
    return dt.strftime("%d %b") if dt else "?"


def _bounded_window(trade_date: str | None) -> tuple[str | None, str | None]:
    if not trade_date:
        return None, None
    try:
        analysis_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
    except ValueError:
        return None, None
    # Even a one-day-old run must not query ``when:7d`` and ingest tomorrow's
    # headlines. Today uses the current seven-day discovery feed.
    if analysis_date < india_today():
        return ((analysis_date - timedelta(days=10)).isoformat(),
                (analysis_date + timedelta(days=1)).isoformat())
    return None, None


def _fetch_queries(queries: list[str], *, limit: int,
                   after: str | None, before: str | None) -> tuple[list[dict], list[SourceHealth]]:
    items: list[dict] = []
    records: list[SourceHealth] = []
    per_query = max(3, limit // max(1, len(queries)))

    def fetch(query: str):
        return _fetch_rss(query, when="7d", limit=max(limit, per_query),
                          after=after, before=before)

    # Independent queries are I/O-bound. A fixed, small pool prevents the ten
    # macro queries from serially multiplying a provider timeout.
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(queries)))) as executor:
        responses = list(executor.map(fetch, queries))
    for got in responses:
        items.extend(got)
        record = getattr(got, "source_health", None)
        if isinstance(record, SourceHealth):
            records.append(record)
        else:  # test/injected list
            records.append(health(
                "google-news", "rss-query", "available" if got else "empty",
                "injected adapter result", rows=len(got),
            ))
    return _dedupe(items)[:limit], records


def get_company_news(company_name: str, ticker: str, limit: int = 15,
                     trade_date: str | None = None) -> dict:
    """Ticker-specific Indian business headlines with strict PIT bounds."""
    after, before = _bounded_window(trade_date)
    short = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
    queries = [
        f"{short} share price stock",
        f"{short} quarterly results earnings",
        f"{short} news",
    ]
    items, records = _fetch_queries(
        queries, limit=limit, after=after, before=before,
    )
    aggregate = aggregate_health(
        "google-news", "company-news", records, rows=len(items),
        detail=(f"{len(items)} unique in-window headlines across {len(queries)} queries"),
    )
    if not items:
        period = f"historical window {after} to {before}" if after else "latest seven-day window"
        block = (f"COMPANY NEWS: <{aggregate.status} — no usable headlines for {period}; "
                 "do not infer silence.>"
                 f"\n(Ticker: {ticker}, queries used: {queries})")
    else:
        lines = [f"- [{_fmt_date(item['date'])}] {item['source']}: {_clean_title(item['title'])}"
                 for item in items]
        period = f"window {after} to {before}" if after else "last 7 days"
        block = (f"COMPANY NEWS HEADLINES — {company_name} ({ticker}) — {period}, "
                 "Google News India discovery feed:\n" + "\n".join(lines))
    return {"news_block": block, "items": items,
            "source_health": [aggregate.to_dict()]}


def _company_news_window(company_name: str, limit: int, after: str, before: str) -> dict:
    """Backward-compatible bounded helper used by older callers/tests."""
    short = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
    items, records = _fetch_queries(
        [f"{short} stock"], limit=limit, after=after, before=before,
    )
    aggregate = aggregate_health(
        "google-news", "company-news", records, rows=len(items),
        detail=f"{len(items)} headlines in historical window",
    )
    if items:
        block = (f"COMPANY NEWS HEADLINES — {company_name} — window {after} to {before}:\n"
                 + "\n".join(
                     f"- [{_fmt_date(item['date'])}] {item['source']}: {_clean_title(item['title'])}"
                     for item in items))
    else:
        block = f"COMPANY NEWS: <{aggregate.status} for historical window {after} to {before}>"
    return {"news_block": block, "items": items,
            "source_health": [aggregate.to_dict()]}


def get_india_macro_news(limit: int = 12, trade_date: str | None = None) -> dict:
    """RBI/regulator/market headlines from Google News India discovery RSS."""
    after, before = _bounded_window(trade_date)
    items, records = _fetch_queries(
        INDIA_MACRO_QUERIES, limit=limit, after=after, before=before,
    )
    aggregate = aggregate_health(
        "google-news", "india-macro-news", records, rows=len(items),
        detail=f"{len(items)} unique headlines across {len(INDIA_MACRO_QUERIES)} queries",
    )
    if not items:
        block = (f"INDIA MACRO NEWS: <{aggregate.status} — no usable in-window headlines; "
                 "do not assume calm markets>")
    else:
        lines = [f"- [{_fmt_date(item['date'])}] {item['source']}: {_clean_title(item['title'])}"
                 for item in items]
        period = f"window {after} to {before}" if after else "last 7 days"
        block = (f"INDIA MACRO / MARKET NEWS ({period}) — RBI, inflation, SEBI, "
                 "FIIs, crude, rupee:\n" + "\n".join(lines))
    return {"macro_news_block": block, "items": items,
            "source_health": [aggregate.to_dict()]}
