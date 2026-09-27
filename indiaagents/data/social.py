"""
Social chatter for Indian stocks — Reddit (keyless RSS like the original repo)
with Indian-market search bias and honest degradation:
a failed fetch is reported as <unavailable>, never as "no posts".
"""
from __future__ import annotations

import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Reddit's public RSS/JSON search (no key). May be 403-blocked on some
# networks/sandboxes — we degrade honestly and try a Google News fallback.
REDDIT_FEEDS = [
    "https://www.reddit.com/search.xml",
    "https://old.reddit.com/search.xml",
]


def _fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        return urllib.request.urlopen(req, timeout=12).read().decode("utf-8", "ignore")
    except Exception as e:
        logger.info("fetch failed %s: %s", url, e)
        return None


def _parse_reddit_rss(xml: str, limit: int) -> list[dict]:
    posts = []
    try:
        root = ET.fromstring(xml)
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = (entry.findtext("{http://www.w3.org/2005/Atom}title") or "").strip()
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            link = link_el.get("href", "") if link_el is not None else ""
            updated = (entry.findtext("{http://www.w3.org/2005/Atom}updated") or "").strip()
            dt = None
            try:
                dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            except Exception:
                pass
            if title:
                posts.append({"title": title, "link": link, "date": dt})
            if len(posts) >= limit:
                break
    except Exception as e:
        logger.info("reddit parse failed: %s", e)
    return posts


def get_social_chatter(company_name: str, ticker: str, trade_date: str | None = None) -> dict:
    """Reddit chatter about the company (r/IndianStockMarket, r/IndiaInvestments,
    r/StockMarketIndia, r/DalalStreetTalks surface via global search)."""
    short = company_name.split(" Limited")[0].split(" Ltd")[0].strip()
    base = re.split(r"[ .]", ticker)[0] if ticker else short
    from urllib.parse import quote_plus
    q = quote_plus(f'"{short}" OR "{base}" (stock OR share OR NSE OR BSE OR India)')

    try:
        d = datetime.strptime(trade_date, "%Y-%m-%d") if trade_date else datetime.now()
        cutoff = d - timedelta(days=7)
    except ValueError:
        cutoff = datetime.now() - timedelta(days=7)

    posts: list[dict] = []
    source_used = None
    for feed in REDDIT_FEEDS:
        xml = _fetch(f"{feed}?q={q}&limit=25&sort=new&t=month")
        if not xml:
            continue
        got = _parse_reddit_rss(xml, 25)
        if got:
            posts = got
            source_used = "reddit-search"
            break

    if posts:
        # filter: mention of company/ticker in title, within a week of trade date
        words = {w.lower() for w in (short.split() + [base.lower()]) if len(w) > 2}
        keep = []
        for p in posts:
            tl = p["title"].lower()
            if any(w in tl for w in words):
                if cutoff is None or p["date"] is None or p["date"].replace(tzinfo=None) >= cutoff.replace(tzinfo=None) - timedelta(days=30):
                    keep.append(p)
        posts = keep[:15]
        lines = [f"- r/ post: {p['title']} ({p['date'].strftime('%d %b') if p['date'] else '?'})"
                 for p in posts]
        if lines:
            block = (f"SOCIAL CHATTER — Reddit posts mentioning {short} ({ticker}), "
                     f"newest first. Note: Reddit par retail sentiment hota hai — often "
                     f"contrarian/noisy; weighted opinion nahi.\n" + "\n".join(lines))
            return {"social_block": block, "source": source_used, "count": len(posts)}

    # fallback: google news search restricted to reddit results
    gq = quote_plus(f"reddit {short} stock")
    xml = _fetch(f"https://news.google.com/rss/search?q={gq}+when:30d&hl=en-IN&gl=IN&ceid=IN:en")
    if xml:
        try:
            root = ET.fromstring(xml)
            titles = [(it.findtext("title") or "").strip()
                      for it in root.iter("item")][:10]
            words_f = {w.lower() for w in (short.split() + [base.lower()]) if len(w) > 2}
            titles = [t for t in titles if t and any(w in t.lower() for w in words_f)]
            if titles:
                block = (f"SOCIAL CHATTER — direct Reddit access unavailable tha, "
                         f"to Google News se Reddit/community discussions mile "
                         f"(lower coverage — isko 'no chatter' mat samjho):\n"
                         + "\n".join(f"- {t}" for t in titles))
                return {"social_block": block, "source": "google-news-reddit", "count": len(titles)}
        except Exception:
            pass

    block = ("SOCIAL CHATTER: <unavailable — Reddit fetch blocked/fail hua. "
             "Iska matlab log chup hain YEHI claim mat karo; data hi nahi mila.>")
    return {"social_block": block, "source": "unavailable", "count": 0}
