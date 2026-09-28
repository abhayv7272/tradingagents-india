"""Multi-source data layer (India).

yfinance ke ilava independent sources — single-source gaps (BETA jaisa) survive karne ke liye:

1. Yahoo Finance (yfinance)          — primary OHLCV + financials (existing, market.py/fundamentals.py)
2. Alpha Vantage                     — OHLCV fallback (free key, SYMBOL.BSE) + quote cross-check
3. NSE (nseindia.com unofficial API) — live quote cross-check (last/VWAP/52w/prev-close)
4. Screener.in                       — independent fundamentals (MCap, P/E, BV, DivYield, ROCE, ROE, High/Low)
5. Google News RSS                   — news (existing, news.py)
6. FRED                             — macro (existing, news.py)

Sab functions GRACEFUL hain: fail → None/{} return, kabhi crash nahi.
Requests file-cache ke through jaate hain (.cache/data/, TTL based) — polite + fast repeats.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests

from .health import SourceResult, classify_exception, health

try:  # optional at import time — parser tests bina bs4 ke bhi chal jaate hain
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None

# --------------------------------------------------------------------------------------------------
# Shared polite-HTTP layer (with file TTL cache)
# --------------------------------------------------------------------------------------------------

CACHE_DIR = Path(__file__).resolve().parent.parent.parent / ".cache" / "data"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BASE_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}


class CachedBytes(bytes):
    """Bytes-compatible HTTP payload with cache-hit provenance."""

    def __new__(cls, value: bytes, *, cached: bool):
        obj = bytes.__new__(cls, value)
        obj.cached = cached
        return obj


class HTTPFetchError(RuntimeError):
    """HTTP failure carrying only a status code (never a credential-bearing URL)."""

    def __init__(self, status_code: int):
        self.status_code = int(status_code)
        super().__init__(f"HTTP {self.status_code}")


def _cache_path(url: str) -> Path:
    # SHA-256 avoids a weak cache key. The URL/API key itself is never written.
    return CACHE_DIR / (hashlib.sha256(url.encode()).hexdigest() + ".cache")


def _cached_get(url: str, headers: dict | None = None, ttl_hours: float = 12.0,
                timeout: int = 12) -> bytes:
    """GET with a file-TTL cache; cache only complete HTTP-200 payloads.

    Writes are atomic so concurrent Streamlit sessions cannot leave a partial
    parser input.  Expired content is not silently served as current evidence.
    """
    f = _cache_path(url)
    if f.exists() and (time.time() - f.stat().st_mtime) < ttl_hours * 3600:
        return CachedBytes(f.read_bytes(), cached=True)
    r = requests.get(url, headers=headers or BASE_HEADERS, timeout=timeout)
    if r.status_code != 200:
        raise HTTPFetchError(r.status_code)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=f.parent, prefix=f.name + ".", delete=False) as tmp:
            tmp.write(r.content)
            tmp.flush()
            tmp_name = tmp.name
        Path(tmp_name).replace(f)
    finally:
        if tmp_name:
            Path(tmp_name).unlink(missing_ok=True)
    return CachedBytes(r.content, cached=False)


def _num(text: str | None) -> float | None:
    """'₹ 1,234.50 Cr' → 1234.5 (numeric extraction, robust)."""
    if not text:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(text))
    if not m:
        return None
    try:
        v = float(m.group(0).replace(",", ""))
        return None if math.isnan(v) else v
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------
# 4. Screener.in — independent fundamentals
# --------------------------------------------------------------------------------------------------

# top-ratios li label → normalized key
_SCREENER_KEYS = {
    "market cap": "market_cap_cr", "current price": "price",
    "high / low": "high_low", "stock p/e": "pe", "book value": "book_value",
    "dividend yield": "div_yield", "roce": "roce", "roe": "roe",
    "face value": "face_value", "p/b": "pb", "opm": "opm",
    "debt to equity": "de", "eps": "eps", "dividend payout": "payout",
}


def parse_screener_html(html_text: str) -> dict:
    """Parse screener.in company page (fixture-testable, no network).

    2026 page structure: <ul id="top-ratios"><li>...<span class="name"> + <span class="nowrap value">
    Returns {"ratios": {label: display_text}, "about": str}.
    """
    if BeautifulSoup is None:
        return {"ratios": {}, "about": ""}
    soup = BeautifulSoup(html_text, "html.parser")
    ratios: dict[str, str] = {}
    # section-wrapper (purana) ya seedha ul (naya) — dono support
    wrap = soup.find("section", id="top-ratios")
    top = wrap if wrap is not None else soup.find("ul", id="top-ratios")
    if top:
        for li in top.find_all("li"):
            nm = li.find("span", class_="name")
            # value container (full text: "₹ 1,612 / 1,196") → fallback: number span
            val = (li.find("span", class_="value") or li.find("span", class_="nowrap-value")
                   or li.find("span", class_="number"))
            if nm and val:
                label = nm.get_text(" ", strip=True).lower().rstrip(":")
                if label:
                    ratios[label] = re.sub(r"\s+", " ", val.get_text(" ", strip=True))
    about = ""
    prof = (soup.find("div", class_="company-profile")
            or soup.find("div", class_="company-profile remove-line-height")
            or soup.find("div", {"id": "company-info"}))
    if prof:
        p = prof.find("p") or prof.find("div")
        if p:
            about = re.sub(r"\s+", " ", p.get_text(" ", strip=True))[:900]
    return {"ratios": ratios, "about": about}


def parse_screener_search(payload: object) -> list[str]:
    """Return safe, canonical company URLs from Screener's search JSON.

    Current search results already include ``/consolidated/`` for many stocks;
    canonicalization avoids accidentally requesting
    ``.../consolidated/consolidated/`` before the real page.
    """
    if not isinstance(payload, list):
        return []
    urls: list[str] = []
    for hit in payload[:5]:
        if not isinstance(hit, dict):
            continue
        raw_url = str(hit.get("url") or "").strip()
        if not raw_url:
            continue
        absolute = urljoin("https://www.screener.in/", raw_url)
        parsed = urlparse(absolute)
        hostname = str(parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            hostname == "screener.in" or hostname.endswith(".screener.in")
        ):
            continue
        if not parsed.path.startswith("/company/"):
            continue
        canonical = f"https://www.screener.in{parsed.path.rstrip('/')}/"
        if canonical not in urls:
            urls.append(canonical)
    return urls


def _screener_page_variants(url: str) -> list[str]:
    """Prefer the searched page, then try its consolidated/standalone peer."""
    canonical = url.rstrip("/") + "/"
    marker = "/consolidated/"
    if canonical.endswith(marker):
        alternate = canonical[:-len(marker)] + "/"
    else:
        alternate = canonical.rstrip("/") + marker
    return list(dict.fromkeys((canonical, alternate)))


def get_screener_fundamentals(ticker: str, name: str | None = None,
                              trade_date: str | None = None, *,
                              with_health: bool = False) -> dict | None | SourceResult:
    """Fetch Screener top-ratios, optionally returning structured health.

    Screener is an unofficial HTML adapter and is never represented as an
    official or guaranteed feed. ``trade_date`` is accepted for compatibility;
    callers must suppress this latest-only snapshot in historical runs.
    """
    del trade_date
    sym = ticker.replace(".NS", "").replace(".BO", "").replace(".BSE", "").strip().upper()

    def done(value, record):
        result = SourceResult(value, record)
        return result if with_health else result.value

    if not sym:
        return done(None, health("screener", "fundamentals-crosscheck", "empty",
                                 "blank exchange symbol"))
    encoded_sym = quote(sym, safe="-")
    direct = f"https://www.screener.in/company/{encoded_sym}/"
    candidates = _screener_page_variants(direct + "consolidated/")
    failures = []
    # Search is only a slug fallback; a failed search does not prevent direct URLs.
    if name:
        try:
            q = quote(name.strip()[:40], safe="")
            raw = _cached_get(
                f"https://www.screener.in/api/company/search/?q={q}", ttl_hours=24,
            ).decode("utf-8", "ignore")
            data = json.loads(raw)
            search_urls = parse_screener_search(data)
            if not search_urls and not isinstance(data, list):
                raise TypeError("search payload is not a list")
            for search_url in search_urls:
                candidates.extend(_screener_page_variants(search_url))
        except Exception as exc:  # direct candidates are still attempted
            failures.append(classify_exception(exc))

    for url in dict.fromkeys(candidates):
        try:
            payload = _cached_get(url, ttl_hours=12)
            html_text = payload.decode("utf-8", "ignore")
            if "top-ratios" not in html_text:
                failures.append(("parse-failed", "expected top-ratios section missing"))
                continue
            parsed = parse_screener_html(html_text)
            if not parsed["ratios"]:
                failures.append(("parse-failed", "top-ratios section could not be parsed"))
                continue
            out = {"ratios": parsed["ratios"], "about": parsed["about"],
                   "url": url,
                   "slug": url.split("/company/", 1)[1].strip("/").split("/", 1)[0]
                   if "/company/" in url else sym}
            for label, key in _SCREENER_KEYS.items():
                if label in parsed["ratios"]:
                    value = _num(parsed["ratios"][label])
                    if value is not None:
                        out[key] = value
            return done(out, health(
                "screener", "fundamentals-crosscheck", "available",
                "unofficial latest HTML snapshot parsed", rows=len(parsed["ratios"]),
                cached=bool(getattr(payload, "cached", False)),
            ))
        except Exception as exc:
            failures.append(classify_exception(exc))

    status, detail = max(
        failures or [("empty", "no ratios returned")],
        key=lambda item: {"empty": 1, "parse-failed": 2, "network-blocked": 3,
                          "rate-limited": 4, "unconfigured": 0}.get(item[0], 0),
    )
    return done(None, health("screener", "fundamentals-crosscheck", status, detail))


def screener_text_block(sc: dict | None) -> str:
    """LLM-prompt block from screener dict. Empty string if none."""
    if not sc or not sc.get("ratios"):
        return ""
    order = ["market cap", "current price", "high / low", "stock p/e", "book value",
             "dividend yield", "roce", "roe", "face value", "p/b", "opm",
             "debt to equity", "eps"]
    lines = [f"- {k.title()}: {sc['ratios'][k]}" for k in order if k in sc["ratios"]]
    extra = [f"- {k.title()}: {v}" for k, v in sc["ratios"].items() if k not in order]
    head = (f"\n\n=== SCREENER.IN — INDEPENDENT FUNDAMENTALS (consolidated; {sc.get('url', '')}) ===\n"
            "Ye numbers Yahoo ke ilava ek AUR source (screener.in) se hain — cross-check karo:\n")
    body = "\n".join(lines + extra)
    about = f"\n\nCompany profile: {sc['about']}" if sc.get("about") else ""
    return head + body + about


# --------------------------------------------------------------------------------------------------
# 3. NSE — live quote cross-check
# --------------------------------------------------------------------------------------------------

def parse_nse_quote(d: dict) -> dict | None:
    """NSE /api/quote-equity JSON → compact dict (fixture-testable)."""
    if not isinstance(d, dict):
        return None
    pi = d.get("priceInfo") or {}
    try:
        last = float(pi.get("lastPrice"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(last) or last <= 0:
        return None
    ti = d.get("tradeInfo") or {}
    return {
        "last": last, "prev_close": _num(pi.get("previousClose")), "vwap": _num(pi.get("vwap")),
        "day_high": _num(pi.get("intraDayHighLow", {}).get("max"))
        if isinstance(pi.get("intraDayHighLow"), dict) else _num(pi.get("dayHigh")),
        "day_low": _num(pi.get("intraDayHighLow", {}).get("min"))
        if isinstance(pi.get("intraDayHighLow"), dict) else _num(pi.get("dayLow")),
        "week_52_high": _num(pi.get("week52High")), "week_52_low": _num(pi.get("week52Low")),
        "volume": _num(ti.get("totalTradedVolume")),
        "updated": (d.get("metadata") or {}).get("lastUpdateTime"),
    }


def get_nse_quote(ticker: str, *, with_health: bool = False) -> dict | None | SourceResult:
    """Live unofficial NSE quote (homepage cookie bootstrap then quote API)."""
    def done(value, record):
        result = SourceResult(value, record)
        return result if with_health else result.value

    if str(ticker).upper().endswith((".BO", ".BSE")):
        return done(None, health("nse", "live-quote", "suppressed",
                                 "BSE-only symbol is not eligible for NSE quote API"))
    sym = ticker.replace(".NS", "").strip().upper()
    if not sym:
        return done(None, health("nse", "live-quote", "empty", "blank symbol"))
    try:
        session = requests.Session()
        session.headers.update(BASE_HEADERS)
        bootstrap = session.get("https://www.nseindia.com", timeout=8)
        if bootstrap.status_code != 200:
            raise HTTPFetchError(bootstrap.status_code)
        response = session.get(
            f"https://www.nseindia.com/api/quote-equity?symbol={quote(sym, safe='')}", timeout=8,
        )
        if response.status_code != 200:
            raise HTTPFetchError(response.status_code)
        try:
            payload = response.json()
        except Exception as exc:
            raise ValueError("invalid NSE JSON") from exc
        quote_data = parse_nse_quote(payload)
        if quote_data is None:
            return done(None, health("nse", "live-quote", "parse-failed",
                                     "quote payload had no valid positive last price"))
        return done(quote_data, health("nse", "live-quote", "available",
                                       "unofficial live quote parsed", rows=1,
                                       as_of=quote_data.get("updated")))
    except Exception as exc:
        status, detail = classify_exception(exc)
        return done(None, health("nse", "live-quote", status, detail))


# --------------------------------------------------------------------------------------------------
# 2. Alpha Vantage — OHLCV fallback + quote
# --------------------------------------------------------------------------------------------------

def _av_symbol(ticker: str) -> str:
    return (ticker.replace(".NS", ".BSE").replace(".BO", ".BSE")
            .replace(".BSE.BSE", ".BSE").strip().upper())


def _av_key() -> str:
    return (os.getenv("ALPHA_VANTAGE_API_KEY") or "").strip()


def parse_av_quote(d: dict) -> dict | None:
    """Alpha Vantage GLOBAL_QUOTE JSON → compact dict (fixture-testable)."""
    q = (d or {}).get("Global Quote") or {}
    try:
        price = float(q.get("05. price"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price <= 0:
        return None
    return {"price": price, "prev_close": _num(q.get("08. previous close")),
            "day_high": _num(q.get("03. high")), "day_low": _num(q.get("04. low")),
            "volume": _num(q.get("06. volume"))}


def _av_payload_failure(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return "parse-failed", "provider payload is not a JSON object"
    text = " ".join(str(payload.get(key) or "") for key in ("Note", "Information"))
    if "rate" in text.lower() or "frequency" in text.lower() or "call" in text.lower():
        return "rate-limited", "provider returned a call-frequency/rate-limit message"
    if payload.get("Error Message"):
        return "empty", "provider rejected or did not recognize the symbol"
    return None


def get_alpha_vantage_quote(ticker: str, *,
                            with_health: bool = False) -> dict | None | SourceResult:
    """Alpha Vantage live quote; requires a free external API key."""
    def done(value, record):
        result = SourceResult(value, record)
        return result if with_health else result.value

    key = _av_key()
    if not key:
        return done(None, health("alpha-vantage", "live-quote", "unconfigured",
                                 "ALPHA_VANTAGE_API_KEY is not configured"))
    try:
        url = (f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
               f"&symbol={quote(_av_symbol(ticker), safe='')}&apikey={key}")
        raw = _cached_get(url, ttl_hours=0.05)
        payload = json.loads(raw.decode("utf-8", "strict"))
        failure = _av_payload_failure(payload)
        if failure:
            return done(None, health("alpha-vantage", "live-quote", *failure))
        parsed = parse_av_quote(payload)
        if parsed is None:
            return done(None, health("alpha-vantage", "live-quote", "parse-failed",
                                     "GLOBAL_QUOTE had no valid positive price"))
        return done(parsed, health(
            "alpha-vantage", "live-quote", "available",
            "quote payload parsed", rows=1,
            cached=bool(getattr(raw, "cached", False)),
        ))
    except Exception as exc:
        status, detail = classify_exception(exc)
        return done(None, health("alpha-vantage", "live-quote", status, detail))


def parse_av_history(d: dict):
    """AV daily JSON → validated, sorted, tz-naive OHLCV DataFrame."""
    import pandas as pd
    if not isinstance(d, dict):
        return None
    raw = d.get("Time Series (Daily)") or {}
    if not isinstance(raw, dict) or not raw:
        return None
    rows = {}
    for date, vals in raw.items():
        try:
            row = {"Open": float(vals["1. open"]), "High": float(vals["2. high"]),
                   "Low": float(vals["3. low"]), "Close": float(vals["4. close"]),
                   "Volume": float(vals.get("5. volume") or 0)}
            if (not all(math.isfinite(row[key]) and row[key] > 0
                        for key in ("Open", "High", "Low", "Close"))
                    or not math.isfinite(row["Volume"]) or row["Volume"] < 0
                    or row["High"] < max(row["Open"], row["Close"], row["Low"])
                    or row["Low"] > min(row["Open"], row["Close"], row["High"])):
                continue
            rows[date] = row
        except (KeyError, ValueError, TypeError):
            continue
    if not rows:
        return None
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.to_datetime(df.index, errors="coerce")
    df = df[~df.index.isna()]
    return df[~df.index.duplicated(keep="last")].sort_index() if not df.empty else None


def get_alpha_vantage_history(ticker: str, full: bool = True, *,
                              with_health: bool = False):
    """Unadjusted daily OHLCV from Alpha Vantage (BSE symbol)."""
    def done(value, record):
        result = SourceResult(value, record)
        return result if with_health else result.value

    key = _av_key()
    if not key:
        return done(None, health("alpha-vantage", "ohlcv-fallback", "unconfigured",
                                 "ALPHA_VANTAGE_API_KEY is not configured"))
    try:
        outputsize = "full" if full else "compact"
        url = (f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY"
               f"&symbol={quote(_av_symbol(ticker), safe='')}&outputsize={outputsize}&apikey={key}")
        raw = _cached_get(url, ttl_hours=12)
        payload = json.loads(raw.decode("utf-8", "strict"))
        failure = _av_payload_failure(payload)
        if failure:
            return done(None, health("alpha-vantage", "ohlcv-fallback", *failure))
        frame = parse_av_history(payload)
        if frame is None or frame.empty:
            return done(None, health("alpha-vantage", "ohlcv-fallback", "parse-failed",
                                     "daily payload had no valid OHLCV rows"))
        return done(frame, health(
            "alpha-vantage", "ohlcv-fallback", "available",
            "unadjusted daily BSE history parsed", rows=len(frame),
            as_of=frame.index[-1].date().isoformat(),
            cached=bool(getattr(raw, "cached", False)),
        ))
    except Exception as exc:
        status, detail = classify_exception(exc)
        return done(None, health("alpha-vantage", "ohlcv-fallback", status, detail))


# --------------------------------------------------------------------------------------------------
# Price cross-check (consensus + data-quality note)
# --------------------------------------------------------------------------------------------------

def cross_check_price(ref_price: float | None, others: list) -> tuple[int, str]:
    """others: [(source_name, price|None), ...] vs ref_price.

    Returns (n_sources, note). Note '' if nothing to compare.
    """
    if not ref_price or not others:
        return 0, ""
    parts, worst = [], 0.0
    for src, px in others:
        if px is None:
            continue
        try:
            d = (float(px) - float(ref_price)) / float(ref_price) * 100.0
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        worst = max(worst, abs(d))
        parts.append(f"{src} ₹{float(px):,.2f} ({d:+.1f}%)")
    if not parts:
        return 0, ""
    verdict = "⚠️ MISMATCH >2% — source data me conflict hai" if worst > 2 else "OK (sab consistent)"
    note = (f"Price cross-check vs {len(parts)} independent source(s): "
            + "; ".join(parts) + f" — {verdict}")
    return len(parts), note
