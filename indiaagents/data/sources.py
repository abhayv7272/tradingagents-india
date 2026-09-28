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
import time
from pathlib import Path
from urllib.parse import quote

import requests

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


def _cached_get(url: str, headers: dict | None = None, ttl_hours: float = 12.0,
                timeout: int = 12) -> bytes:
    """GET with file-TTL cache. Raises on HTTP error (cache me sirf 200s)."""
    f = CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".cache")
    if f.exists() and (time.time() - f.stat().st_mtime) < ttl_hours * 3600:
        return f.read_bytes()
    r = requests.get(url, headers=headers or BASE_HEADERS, timeout=timeout)
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code} for {url}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(r.content)
    return r.content


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


def get_screener_fundamentals(ticker: str, name: str | None = None,
                              trade_date: str | None = None) -> dict | None:
    """Fetch screener.in top-ratios + about for an NSE/BSE symbol. None on failure."""
    sym = ticker.replace(".NS", "").replace(".BO", "").replace(".BSE", "").strip().upper()
    if not sym:
        return None
    candidates = [
        f"https://www.screener.in/company/{sym}/consolidated/",
        f"https://www.screener.in/company/{sym}/",
    ]
    # search-API fallback (screener slug ≠ ticker ho sakta hai, e.g. M&M)
    if name:
        try:
            q = quote(name.strip()[:40])
            data = json.loads(_cached_get(
                f"https://www.screener.in/api/company/search/?q={q}", ttl_hours=24).decode("utf-8", "ignore"))
            for hit in data[:3]:
                u = (hit.get("url") or "").strip()
                if u:
                    if not u.startswith("http"):
                        u = "https://www.screener.in" + u
                    candidates += [u.rstrip("/") + "/consolidated/", u.rstrip("/") + "/"]
        except Exception:
            pass

    for url in candidates:
        try:
            html_text = _cached_get(url, ttl_hours=12).decode("utf-8", "ignore")
            if "top-ratios" not in html_text:
                continue
            parsed = parse_screener_html(html_text)
            if not parsed["ratios"]:
                continue
            out = {"ratios": parsed["ratios"], "about": parsed["about"],
                   "url": url, "slug": url.split("/company/")[1].strip("/") if "/company/" in url else sym}
            # normalized numeric keys (for cross-checks)
            for label, key in _SCREENER_KEYS.items():
                if label in parsed["ratios"]:
                    v = _num(parsed["ratios"][label])
                    if v is not None:
                        out[key] = v
            return out
        except Exception:
            continue
    return None


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
    pi = (d or {}).get("priceInfo") or {}
    last = pi.get("lastPrice")
    if not last:
        return None
    ti = (d.get("tradeInfo") or {})
    out = {
        "last": last, "prev_close": pi.get("previousClose"), "vwap": pi.get("vwap"),
        "day_high": pi.get("intraDayHighLow", {}).get("max") if isinstance(pi.get("intraDayHighLow"), dict) else pi.get("dayHigh"),
        "day_low": pi.get("intraDayHighLow", {}).get("min") if isinstance(pi.get("intraDayHighLow"), dict) else pi.get("dayLow"),
        "week_52_high": pi.get("week52High"), "week_52_low": pi.get("week52Low"),
        "volume": ti.get("totalTradedVolume"),
        "updated": (d.get("metadata") or {}).get("lastUpdateTime"),
    }
    return out


def get_nse_quote(ticker: str) -> dict | None:
    """Live NSE quote (session bootstrap homepage → api). None on any failure."""
    if str(ticker).upper().endswith((".BO", ".BSE")):
        return None  # NSE API sirf NSE-listed symbols ke liye
    sym = ticker.replace(".NS", "").strip().upper()
    if not sym:
        return None
    try:
        s = requests.Session()
        s.headers.update(BASE_HEADERS)
        s.get("https://www.nseindia.com", timeout=8)  # cookies bootstrap
        r = s.get(f"https://www.nseindia.com/api/quote-equity?symbol={quote(sym)}", timeout=8)
        if r.status_code != 200:
            return None
        return parse_nse_quote(r.json())
    except Exception:
        return None


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
    if not q.get("05. price"):
        return None
    return {"price": float(q["05. price"]), "prev_close": _num(q.get("08. previous close")),
            "day_high": _num(q.get("03. high")), "day_low": _num(q.get("04. low")),
            "volume": _num(q.get("06. volume"))}


def get_alpha_vantage_quote(ticker: str) -> dict | None:
    """Needs ALPHA_VANTAGE_API_KEY (free). None if no key / failure."""
    key = _av_key()
    if not key:
        return None
    try:
        url = (f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE"
               f"&symbol={quote(_av_symbol(ticker))}&apikey={key}")
        return parse_av_quote(json.loads(_cached_get(url, ttl_hours=0.05).decode()))
    except Exception:
        return None


def parse_av_history(d: dict):
    """AV TIME_SERIES_DAILY(_FULL) JSON → DataFrame (Open/High/Low/Close/Volume, tz-naive)."""
    import pandas as pd
    raw = d.get("Time Series (Daily)") or d.get("Monthly Time Series") or {}
    if not raw:
        return None
    rows = {}
    for date, vals in raw.items():
        try:
            rows[date] = {"Open": float(vals["1. open"]), "High": float(vals["2. high"]),
                          "Low": float(vals["3. low"]), "Close": float(vals["4. close"]),
                          "Volume": float(vals.get("5. volume") or 0)}
        except (KeyError, ValueError, TypeError):
            continue
    if not rows:
        return None
    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def get_alpha_vantage_history(ticker: str, full: bool = True):
    """Daily OHLCV from Alpha Vantage (BSE symbol). DataFrame | None."""
    key = _av_key()
    if not key:
        return None
    try:
        outputsize = "full" if full else "compact"
        url = (f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY"
               f"&symbol={quote(_av_symbol(ticker))}&outputsize={outputsize}&apikey={key}")
        return parse_av_history(json.loads(_cached_get(url, ttl_hours=12).decode()))
    except Exception:
        return None


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
