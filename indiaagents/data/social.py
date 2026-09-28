"""Keyless social-discussion discovery with honest degradation.

Reddit search RSS is unofficial and often blocked from cloud IPs.  Google News
restricted search is a lower-coverage fallback. Historical runs enforce both a
lower and upper publication bound so current posts cannot leak backwards.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

from .health import (
    IST,
    SourceHealth,
    aggregate_health,
    classify_exception,
    health,
    india_today,
)
from .news import parse_google_news_rss
from .sources import _cached_get

logger = logging.getLogger(__name__)

REDDIT_FEEDS = [
    "https://www.reddit.com/search.xml",
    "https://old.reddit.com/search.xml",
]


class FetchedText(str):
    def __new__(cls, value: str, source_health: SourceHealth):
        obj = str.__new__(cls, value)
        obj.source_health = source_health
        return obj


def _fetch(url: str) -> str | None:
    try:
        raw = _cached_get(url, ttl_hours=1, timeout=12)
        text = raw.decode("utf-8", "ignore")
        return FetchedText(text, health(
            "community-feed", "http-fetch", "available" if text else "empty",
            "response received" if text else "empty response body",
            cached=bool(getattr(raw, "cached", False)),
        ))
    except Exception as exc:
        status, detail = classify_exception(exc)
        logger.info("community fetch failed: %s", type(exc).__name__)
        return FetchedText("", health("community-feed", "http-fetch", status, detail))


def _parse_reddit_rss(xml: str, limit: int) -> list[dict]:
    posts = []
    try:
        root = ET.fromstring(xml)
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_node = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_node.get("href", "") if link_node is not None else ""
            updated = (entry.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
            published = None
            try:
                published = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
            except (TypeError, ValueError):
                pass
            if title:
                posts.append({"title": title, "link": link, "date": published})
            if len(posts) >= limit:
                break
    except ET.ParseError as exc:
        logger.info("reddit parse failed: %s", type(exc).__name__)
    return posts


def _fetch_health(value, source: str, category: str) -> SourceHealth:
    record = getattr(value, "source_health", None)
    if isinstance(record, SourceHealth):
        return health(source, category, record.status, record.detail, cached=record.cached)
    return health(source, category, "available" if value else "empty",
                  "injected adapter result")


def get_social_chatter(company_name: str, ticker: str, trade_date: str | None = None) -> dict:
    """Discover recent Reddit/community posts mentioning the stock."""
    short = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
    base = re.split(r"[ .]", ticker)[0] if ticker else short
    query = quote_plus(f'"{short}" OR "{base}" (stock OR share OR NSE OR BSE OR India)')

    try:
        analysis_date = (datetime.strptime(trade_date, "%Y-%m-%d").date()
                         if trade_date else india_today())
    except ValueError:
        analysis_date = india_today()
    lower = analysis_date - timedelta(days=7)
    upper = analysis_date + timedelta(days=1)
    historical = analysis_date < india_today()
    words = {word.lower() for word in (short.split() + [base.lower()]) if len(word) > 2}

    records: list[SourceHealth] = []
    posts: list[dict] = []
    source_used = None
    # Reddit's t=month endpoint cannot retrieve a deep historical window. Avoid
    # a pointless current request and represent that limitation explicitly.
    if (india_today() - analysis_date).days > 31:
        records.append(health(
            "reddit", "social-chatter", "suppressed",
            "current search cannot provide a point-in-time window older than one month",
        ))
    else:
        for feed in REDDIT_FEEDS:
            xml = _fetch(f"{feed}?q={query}&limit=25&sort=new&t=month")
            record = _fetch_health(xml, "reddit", "social-chatter")
            records.append(record)
            if not xml:
                continue
            got = _parse_reddit_rss(xml, 25)
            if not got and str(xml).strip():
                records[-1] = health(
                    "reddit", "social-chatter", "empty",
                    "valid response had no parseable Atom entries", rows=0,
                )
                continue
            for post in got:
                published = post.get("date")
                if published is None:
                    continue  # publication time cannot be proven point-in-time
                post_date = published.astimezone(IST).date()
                if lower <= post_date < upper and any(word in post["title"].lower() for word in words):
                    posts.append(post)
            if posts:
                source_used = "reddit-search"
                records[-1] = health(
                    "reddit", "social-chatter", "available",
                    "in-window matching posts parsed", rows=len(posts),
                    as_of=max(post["date"] for post in posts).astimezone(IST).date().isoformat(),
                )
                break

    posts = posts[:15]
    if posts:
        lines = [f"- r/ post: {post['title']} ({post['date'].strftime('%d %b')})"
                 for post in posts]
        aggregate = aggregate_health(
            "reddit", "social-chatter", records, rows=len(posts),
            detail=f"{len(posts)} matching posts in strict date window",
        )
        block = (f"SOCIAL CHATTER — Reddit posts mentioning {short} ({ticker}), "
                 "newest first. Reddit retail sentiment is noisy and unweighted.\n"
                 + "\n".join(lines))
        return {"social_block": block, "source": source_used, "count": len(posts),
                "source_health": [aggregate.to_dict()]}

    # Lower-coverage Google News fallback, date-bounded for every historical run.
    google_query = quote_plus(f"reddit {short} stock")
    window = (f"+after:{lower.isoformat()}+before:{upper.isoformat()}"
              if historical else "+when:7d")
    xml = _fetch(
        f"https://news.google.com/rss/search?q={google_query}{window}"
        "&hl=en-IN&gl=IN&ceid=IN:en",
    )
    google_record = _fetch_health(xml, "google-news", "community-fallback")
    titles: list[str] = []
    if xml:
        try:
            items = parse_google_news_rss(xml, limit=10)
            if historical:
                items = [item for item in items if item["date"] is not None
                         and lower <= item["date"].astimezone(IST).date() < upper]
            titles = [item["title"] for item in items
                      if any(word in item["title"].lower() for word in words)]
            google_record = health(
                "google-news", "community-fallback",
                "available" if titles else "empty",
                "restricted community search parsed", rows=len(titles),
            )
        except Exception:
            google_record = health(
                "google-news", "community-fallback", "parse-failed",
                "RSS response could not be parsed",
            )
    records.append(google_record)
    if titles:
        block = ("SOCIAL CHATTER — direct Reddit search had no usable posts; "
                 "Google News community discovery fallback (lower coverage):\n"
                 + "\n".join(f"- {title}" for title in titles))
        return {"social_block": block, "source": "google-news-reddit", "count": len(titles),
                "source_health": [google_record.to_dict()]}

    aggregate = aggregate_health(
        "community", "social-chatter", records, rows=0,
        detail="no usable point-in-time community posts; do not infer no chatter",
    )
    block = (f"SOCIAL CHATTER: <{aggregate.status} — Reddit/community data unavailable or "
             "empty. Do not interpret this as neutral sentiment.>")
    return {"social_block": block, "source": "unavailable", "count": 0,
            "source_health": [aggregate.to_dict()]}
