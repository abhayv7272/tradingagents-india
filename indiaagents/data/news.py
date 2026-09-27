"""
News for Indian stocks — Google News RSS (India edition: hl=en-IN&gl=IN&ceid=IN:en).
Covers Economic Times, Moneycontrol, Business Standard, Mint etc. Free, no key.
Replaces the original repo's Alpha Vantage news (US-focused) and FRED macro.
"""
from __future__ import annotations

import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

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


def _fetch_rss(query: str, when: str = "7d", limit: int = 10) -> list[dict]:
    url = (f"https://news.google.com/rss/search?q={quote_plus(query)}+when:{when}"
           f"&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
        root = ET.fromstring(raw)
    except Exception as e:
        logger.warning("Google News RSS failed for %r: %s", query, e)
        return []
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        source = (item.find("source").text or "").strip() if item.find("source") is not None else ""
        pub = (item.findtext("pubDate") or "").strip()
        dt = None
        try:
            dt = parsedate_to_datetime(pub)
        except Exception:
            pass
        if title:
            items.append({"title": title, "source": source, "date": dt})
        if len(items) >= limit:
            break
    return items


def _clean_title(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip()


def _dedupe(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        k = _clean_title(it["title"]).lower()[:60]
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def _fmt_date(dt) -> str:
    return dt.strftime("%d %b") if dt else "?"


def get_company_news(company_name: str, ticker: str, limit: int = 15,
                     trade_date: str | None = None) -> dict:
    """Ticker-specific Indian business news."""
    # historical date -> explicit window instead of when:7d
    when = "7d"
    if trade_date:
        try:
            d = datetime.strptime(trade_date, "%Y-%m-%d")
            if (datetime.now() - d).days > 35:
                after = (d - timedelta(days=10)).strftime("%Y-%m-%d")
                before = (d + timedelta(days=1)).strftime("%Y-%m-%d")
                return _company_news_window(company_name, limit, after, before)
        except ValueError:
            pass

    short = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
    queries = [
        f"{short} share price stock",
        f"{short} quarterly results earnings",
        f"{short} news",
    ]
    items: list[dict] = []
    for q in queries:
        items += _fetch_rss(q, when=when, limit=limit)
    items = _dedupe(items)[:limit]

    if not items:
        block = (f"COMPANY NEWS: <no headlines returned — Google News fetch failed or "
                 f"nothing recent found. Ye 'silence' ka claim nahi hai.>"
                 f"\n(Ticker: {ticker}, queries used: {queries})")
    else:
        lines = [f"- [{_fmt_date(it['date'])}] {it['source']}: {_clean_title(it['title'])}"
                 for it in items]
        block = (f"COMPANY NEWS HEADLINES — {company_name} ({ticker}) — last 7 days, "
                 f"Indian business media (Google News India):\n" + "\n".join(lines))
    return {"news_block": block, "items": items}


def _company_news_window(company_name: str, limit: int, after: str, before: str) -> dict:
    short = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
    q = f"{short} stock"
    url = (f"https://news.google.com/rss/search?q={quote_plus(q)}"
           f"+after:{after}+before:{before}&hl=en-IN&gl=IN&ceid=IN:en")
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        raw = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")
        root = ET.fromstring(raw)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            source = (item.find("source").text or "").strip() if item.find("source") is not None else ""
            if title:
                items.append({"title": title, "source": source, "date": None})
            if len(items) >= limit:
                break
    except Exception as e:
        logger.warning("historical news fetch failed: %s", e)
    items = _dedupe(items)
    if items:
        block = (f"COMPANY NEWS HEADLINES — {company_name} — window {after} to {before}:\n"
                 + "\n".join(f"- {it['source']}: {_clean_title(it['title'])}" for it in items))
    else:
        block = (f"COMPANY NEWS: <unavailable for historical window {after} to {before}>")
    return {"news_block": block, "items": items}


def get_india_macro_news(limit: int = 12, trade_date: str | None = None) -> dict:
    """India macro/regulator/market news — replaces FRED (US) from the original."""
    when = "7d"
    if trade_date:
        try:
            d = datetime.strptime(trade_date, "%Y-%m-%d")
            if (datetime.now() - d).days > 35:
                when = None
        except ValueError:
            pass

    items: list[dict] = []
    per_q = max(3, limit // len(INDIA_MACRO_QUERIES))
    for q in INDIA_MACRO_QUERIES:
        got = _fetch_rss(q, when=when or "30d", limit=per_q)
        items += got
    items = _dedupe(items)[:limit]
    if not items:
        block = "INDIA MACRO NEWS: <fetch unavailable — do not assume calm markets>"
    else:
        lines = [f"- [{_fmt_date(it['date'])}] {it['source']}: {_clean_title(it['title'])}"
                 for it in items]
        block = ("INDIA MACRO / MARKET NEWS (last 7 days) — RBI, inflation, SEBI, "
                 "FIIs, crude, rupee:\n" + "\n".join(lines))
    return {"macro_news_block": block, "items": items}
