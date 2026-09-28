"""
Market data + technical indicators for NSE/BSE stocks via yfinance (free, no key).
Computes the same families of indicators the original TradingAgents offers
(SMA/EMA/MACD/RSI/Bollinger/ATR/VWMA) plus India-specific context.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

# A small map of popular NSE names -> ticker for friendly input ("reliance" -> RELIANCE.NS)
POPULAR_NSE = {
    "ujjivan": "UJJIVANSFB.NS", "ujjivan sfb": "UJJIVANSFB.NS",
    "ujjivan small finance bank": "UJJIVANSFB.NS", "ujjivan bank": "UJJIVANSFB.NS",
    "reliance": "RELIANCE.NS", "tcs": "TCS.NS", "hdfc bank": "HDFCBANK.NS",
    "infosys": "INFY.NS", "icici bank": "ICICIBANK.NS", "infy": "INFY.NS",
    "sbi": "SBIN.NS", "state bank of india": "SBIN.NS", "bharti airtel": "BHARTIARTL.NS",
    "airtel": "BHARTIARTL.NS", "itc": "ITC.NS", "larsen toubro": "LT.NS",
    "l&t": "LT.NS", "lt": "LT.NS", "bajaj finance": "BAJFINANCE.NS",
    "axis bank": "AXISBANK.NS", "kotak mahindra bank": "KOTAKBANK.NS",
    "kotak bank": "KOTAKBANK.NS", "asian paints": "ASIANPAINT.NS",
    "maruti": "MARUTI.NS", "maruti suzuki": "MARUTI.NS", "sun pharma": "SUNPHARMA.NS",
    "tata motors": "TMPV.NS", "tata motors passenger": "TMPV.NS", "tmpv": "TMPV.NS",
    "tata motors commercial": "TMCV.NS", "tmcv": "TMCV.NS",
    "tata steel": "TATASTEEL.NS",
    "tata power": "TATAPOWER.NS", "titan": "TITAN.NS", "wipro": "WIPRO.NS",
    "hcl tech": "HCLTECH.NS", "hcl technologies": "HCLTECH.NS",
    "tech mahindra": "TECHM.NS", "ultratech cement": "ULTRACEMCO.NS",
    "ultratech": "ULTRACEMCO.NS", "nestle india": "NESTLEIND.NS",
    "bajaj finserv": "BAJAJFINSV.NS", "power grid": "POWERGRID.NS",
    "ntpc": "NTPC.NS", "oil and natural gas corporation": "ONGC.NS",
    "ongc": "ONGC.NS", "coal india": "COALINDIA.NS",
    "hindustan unilever": "HINDUNILVR.NS", "hul": "HINDUNILVR.NS",
    "adani enterprises": "ADANIENT.NS", "adani ports": "ADANIPORTS.NS",
    "adani green": "ADANIGREEN.NS", "adani power": "ADANIPOWER.NS",
    "adani total gas": "ATGL.NS", "adani energy": "ADANIENSOL.NS",
    "hindalco": "HINDALCO.NS", "jsw steel": "JSWSTEEL.NS",
    "dr reddy": "DRREDDY.NS", "dr. reddy": "DRREDDY.NS",
    "cil": "COALINDIA.NS", "sbilife": "SBILIFE.NS", "hdfc life": "HDFCLIFE.NS",
    "bajaj auto": "BAJAJ-AUTO.NS", "heromoto": "HEROMOTOCO.NS",
    "hero motocorp": "HEROMOTOCO.NS", "eicher motors": "EICHERMOT.NS",
    "divi's labs": "DIVISLAB.NS", "divis labs": "DIVISLAB.NS",
    "grasim": "GRASIM.NS", "shree cement": "SHREECEM.NS",
    "indusind bank": "INDUSINDBK.NS", "indusind": "INDUSINDBK.NS",
    "bpcl": "BPCL.NS", "ioc": "IOC.NS", "indian oil": "IOC.NS",
    "zomato": "ETERNAL.NS", "eternal": "ETERNAL.NS", "paytm": "PAYTM.NS",
    "nykaa": "NYKAA.NS", "policybazaar": "POLICYBZR.NS",
    "irfc": "IRFC.NS", "ircon": "IRCON.NS",
    "zydus lifesciences": "ZYDUSLIFE.NS", "zydus": "ZYDUSLIFE.NS",
    "lupin": "LUPIN.NS", "cipla": "CIPLA.NS", "aurobindo": "AUROPHARMA.NS",
    "pidilite": "PIDILITIND.NS", "asian": "ASIANPAINT.NS",
    "trent": "TRENT.NS", "dmart": "DMART.NS", "avenue supermarts": "DMART.NS",
    "hdfc amc": "HDFCAMC.NS", "motilal oswal": "MOTILALOFS.NS",
    "angel one": "ANGELONE.NS", "5paisa": "5PAISA.NS",
    "irctc": "IRCTC.NS", "hudco": "HUDCO.NS", "suzlon": "SUZLON.NS",
    "ideainet": "IDEA.NS", "vi": "IDEA.NS", "vedanta": "VEDL.NS",
    "yes bank": "YESBANK.NS", "pnb": "PNB.NS", "bank of baroda": "BANKBARODA.NS",
    "canara bank": "CANBK.NS", "union bank": "UNIONBANK.NS",
    "bel": "BEL.NS", "bharat electronics": "BEL.NS",
    "hal": "HAL.NS", "hindustan aeronautics": "HAL.NS",
    "mazagon dock": "MAZDOCK.NS", "cochin shipyard": "COCHINSHIP.NS",
    "bhel": "BHEL.NS", "nmdc": "NMDC.NS", "sail": "SAIL.NS",
    "ioc": "IOC.NS", "gail": "GAIL.NS", "petronet": "PETRONET.NS",
    "trejhara": "TREJHARA.NS",
}

INDEX_MAP = {
    "nifty": "^NSEI", "nifty 50": "^NSEI", "nifty50": "^NSEI",
    "sensex": "^BSESN", "india vix": "^INDIAVIX", "vix": "^INDIAVIX",
    "bank nifty": "^NSEBANK", "nifty bank": "^NSEBANK",
    "nifty it": "^CNXIT", "usdinr": "USDINR=X", "usd/inr": "USDINR=X",
    "usd inr": "USDINR=X", "dollar": "USDINR=X", "rupee": "USDINR=X",
    "gold": "GC=F", "crude": "CL=F", "brent": "BZ=F",
}


def _clean_name(x) -> str:
    return str(x or "").strip().lower()


def _validate(ticker: str) -> dict | None:
    """Return basic info if the ticker resolves on Yahoo, else None."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        hist = t.history(period="1mo")
        if hist.empty and not info.get("longName"):
            return None
        return info
    except Exception:
        return None


def resolve_ticker(user_input: str) -> dict:
    """Turn 'reliance' / 'RELIANCE.NS' / 'Nifty' into a validated Yahoo ticker.
    Returns dict: {ticker, name, exchange, currency, is_index}"""
    raw = (user_input or "").strip()
    if not raw:
        raise ValueError("Stock ka naam khaali hai!")
    key = _clean_name(raw)

    # direct index / commodity requests
    if key in INDEX_MAP:
        sym = INDEX_MAP[key]
        info = _validate(sym)
        if info is not None or sym.startswith("^") or "=" in sym:
            return {"ticker": sym, "name": raw.upper(), "exchange": "INDEX",
                    "currency": "INR", "is_index": True}

    # already exchange-suffixed / index / crypto-style ticker
    if any(ch in raw for ch in (".", "=", "^")):
        info = _validate(raw)
        if info:
            return {"ticker": raw,
                    "name": info.get("longName") or info.get("shortName") or raw,
                    "exchange": info.get("exchange", "?"),
                    "currency": info.get("currency", "INR"),
                    "is_index": raw.startswith("^")}
        raise ValueError(f"'{raw}' Yahoo Finance par nahi mila. "
                         "NSE ticker + .NS try karo (e.g. RELIANCE.NS).")

    # popular name map
    if key in POPULAR_NSE:
        cand = POPULAR_NSE[key]
        info = _validate(cand)
        if info:
            return {"ticker": cand,
                    "name": info.get("longName") or info.get("shortName") or raw,
                    "exchange": info.get("exchange", "NSE"),
                    "currency": info.get("currency", "INR"),
                    "is_index": False}

    # try .NS then .BO
    for suffix, exch in ((".NS", "NSE"), (".BO", "BSE")):
        cand = f"{raw.upper()}{suffix}"
        info = _validate(cand)
        if info:
            return {"ticker": cand,
                    "name": info.get("longName") or info.get("shortName") or raw,
                    "exchange": info.get("exchange", exch),
                    "currency": info.get("currency", "INR"),
                    "is_index": False}

    raise ValueError(
        f"'{raw}' nahi mila! Sahi NSE ticker ya company naam likho — e.g. RELIANCE, TCS, "
        f"HDFCBANK, INFY, TATAMOTORS (ya full form jaise 'HDFC Bank')."
    )


# ---------------------------------------------------------------------------
# Indicators (pandas implementations — no heavy deps)
# ---------------------------------------------------------------------------

def _sma(s, n): return s.rolling(n).mean()
def _ema(s, n): return s.ewm(span=n, adjust=False).mean()


def _rsi(close: pd.Series, n=14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - 100 / (1 + rs)
    return float(rsi.iloc[-1])


def _macd(close: pd.Series):
    macd_line = _ema(close, 12) - _ema(close, 26)
    signal = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal
    return float(macd_line.iloc[-1]), float(signal.iloc[-1]), float(hist.iloc[-1])


def _atr(df: pd.DataFrame, n=14) -> float:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return float(tr.ewm(alpha=1 / n, adjust=False).mean().iloc[-1])


def _pct(a: float, b: float) -> float | None:
    if b is None or b == 0 or (isinstance(b, float) and math.isnan(b)):
        return None
    try:
        return round((a - b) / b * 100, 2)
    except Exception:
        return None


def _indian_group(n: float, decimals: int = 2) -> str:
    """Indian digit grouping: 1057219 -> 10,57,219"""
    s = f"{abs(n):.{decimals}f}"
    intpart, _, dec = s.partition(".")
    if len(intpart) > 3:
        head, tail = intpart[:-3], intpart[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        intpart = ",".join(groups + [tail])
    out = intpart + (("." + dec) if dec else "")
    return ("-" if n < 0 else "") + out


def inr(x: float) -> str:
    """Format an INR amount with Indian units (lakh/crore) and grouping."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    neg = x < 0
    x = abs(x)
    if x >= 1e7:
        s = f"₹{_indian_group(x / 1e7)} Cr"
    elif x >= 1e5:
        s = f"₹{_indian_group(x / 1e5)} L"
    else:
        s = f"₹{_indian_group(x)}"
    return ("-" if neg else "") + s


def _f(v, nd=2, prefix=""):
    """Safe float formatter for indicator blocks — never prints 'nan'."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if math.isnan(v) or math.isinf(v):
        return "—"
    return f"{prefix}{v:,.{nd}f}"


def _vol_ratio(last_vol: float, avg_vol: float) -> str:
    """Volume vs 20-day average — zero/NaN safe."""
    try:
        avg_vol = float(avg_vol)
        if avg_vol == 0 or math.isnan(avg_vol):
            return "—"
        return f"{(last_vol / avg_vol - 1) * 100:+.0f}%"
    except (TypeError, ValueError, ZeroDivisionError):
        return "—"


def get_market_data(ticker: str, trade_date: str | None = None,
                    lookback_months: int = 6) -> dict:
    """Fetch OHLCV + compute indicators. Returns dict with data blocks for prompts."""
    t = yf.Ticker(ticker)
    asof = trade_date or datetime.now().strftime("%Y-%m-%d")
    # yfinance ka 'end' EXCLUSIVE hota hai — trade_date ka bar paane ke liye +1 din
    end = (datetime.strptime(asof, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    start = (datetime.strptime(asof, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
    df = t.history(start=start, end=end, interval="1d", auto_adjust=True)
    if df.empty:
        raise ValueError(f"{ticker} ka price data nahi mila (yahoo).")
    df.index = df.index.tz_localize(None)
    # point-in-time: asof date tak hi (future leak nahi)
    df = df[df.index <= pd.Timestamp(asof)]

    close = df["Close"]
    last = float(close.iloc[-1])
    info = t.info or {}

    # indicators
    sma50 = _sma(close, 50); sma200 = _sma(close, 200)
    ema10 = _ema(close, 10); ema20 = _ema(close, 20)
    rsi = _rsi(close)
    macd_l, macd_s, macd_h = _macd(close)
    atr = _atr(df)
    vol20 = float(df["Volume"].rolling(20).mean().iloc[-1]) if len(df) >= 20 else float(df["Volume"].mean())
    vwma20 = float((close * df["Volume"]).rolling(20).sum().iloc[-1] / df["Volume"].rolling(20).sum().iloc[-1]) if len(df) >= 20 else None
    # Beta vs NIFTY (Yahoo ka beta S&P500 ke against hai — NSE stocks ke liye misleading)
    beta_nifty = None
    try:
        nb = yf.Ticker("^NSEI").history(start=start, end=end, interval="1d", auto_adjust=True)
        if not nb.empty:
            nb.index = nb.index.tz_localize(None)
            nb = nb[nb.index <= pd.Timestamp(asof)]
            j = pd.concat([close, nb["Close"]], axis=1, keys=["s", "n"]).dropna().tail(120)
            if len(j) >= 60:
                both = j.pct_change().dropna()
                beta_nifty = round(float(both["s"].cov(both["n"]) / both["n"].var()), 2)
    except Exception:
        beta_nifty = None
    # Bollinger
    boll_mid = _sma(close, 20)
    boll_std = close.rolling(20).std()
    boll_ub = float((boll_mid + 2 * boll_std).iloc[-1])
    boll_lb = float((boll_mid - 2 * boll_std).iloc[-1])

    # 52-week stats
    year_df = df.tail(252)
    hi52 = float(year_df["Close"].max()); lo52 = float(year_df["Close"].min())

    # returns
    def ret(days):
        if len(close) > days:
            return _pct(last, float(close.iloc[-1 - days]))
        return None
    rets = {k: ret(d) for k, d in
            (("1w", 5), ("1m", 21), ("3m", 63), ("6m", 126), ("1y", 252))}

    # volatility (annualized, 3m) & max drawdown (1y)
    daily_ret = close.pct_change().tail(63)
    vol_ann = float(daily_ret.std() * math.sqrt(252) * 100) if len(daily_ret) > 10 else None
    roll_max = year_df["Close"].cummax()
    mdd = float(((year_df["Close"] / roll_max) - 1).min() * 100)

    # support/resistance via recent swing levels (3m)
    recent = df.tail(63)
    sup = float(recent["Low"].min()); res = float(recent["High"].max())

    # golden / death cross
    cross = "n/a"
    if not (sma50.isna().iloc[-1] or sma200.isna().iloc[-1]) and len(df) > 205:
        prev = sma50.iloc[-2] - sma200.iloc[-2]
        curr = sma50.iloc[-1] - sma200.iloc[-1]
        if prev <= 0 < curr:
            cross = "GOLDEN CROSS (fresh)"
        elif prev >= 0 > curr:
            cross = "DEATH CROSS (fresh)"
        else:
            cross = "50-SMA above 200-SMA" if curr > 0 else "50-SMA below 200-SMA"

    # last 30 rows table for the prompt
    tbl = df.tail(30).copy()
    tbl.index = tbl.index.strftime("%Y-%m-%d")
    ohlcv = "\n".join(
        f"{i} | O={r['Open']:.2f} H={r['High']:.2f} L={r['Low']:.2f} "
        f"C={r['Close']:.2f} V={int(r['Volume']):,}"
        for i, r in tbl.iterrows()
    )

    ind_block = f"""TECHNICAL DATA — {ticker} ({info.get('longName', ticker)}) | as of {df.index[-1].date()}
Current price: ₹{last:,.2f} | Day change: {_pct(last, float(close.iloc[-2])) if len(close) > 1 else '—'}%
Returns: 1W: {rets['1w']}% | 1M: {rets['1m']}% | 3M: {rets['3m']}% | 6M: {rets['6m']}% | 1Y: {rets['1y']}%
52-week High: ₹{hi52:,.2f} (price is {_pct(last, hi52)}% below) | 52-week Low: ₹{lo52:,.2f} (price is {_pct(last, lo52)}% above)
3-month Support ≈ ₹{sup:,.2f} | Resistance ≈ ₹{res:,.2f}
Max Drawdown (1Y): {mdd:.1f}% | Annualized Volatility (3M): {_f(vol_ann, 1)}

INDICATORS:
- 50-SMA: {_f(sma50.iloc[-1])} | 200-SMA: {_f(sma200.iloc[-1])} | Trend: {cross}
- 10-EMA: {_f(ema10.iloc[-1])} | 20-EMA: {_f(ema20.iloc[-1])}
- RSI(14): {rsi:.1f} {'(overbought zone)' if rsi > 70 else '(oversold zone)' if rsi < 30 else '(neutral zone)'}
- MACD: line={macd_l:.2f} signal={macd_s:.2f} hist={macd_h:.2f} ({'bullish' if macd_h > 0 else 'bearish'} momentum)
- Bollinger(20,2): Upper ₹{_f(boll_ub)} | Mid ₹{_f(boll_mid.iloc[-1])} | Lower ₹{_f(boll_lb)}
- ATR(14): {atr:.2f} (~{atr / last * 100:.1f}% of price — for stop-loss sizing)
- Beta vs NIFTY (6M daily): {beta_nifty}
- VWMA(20): {_f(vwma20)}
- Volume: last {int(df['Volume'].iloc[-1]):,} vs 20-day avg {int(vol20):,} ({_vol_ratio(df['Volume'].iloc[-1], vol20)})

DAILY OHLCV (last 30 sessions):
Date | Open | High | Low | Close | Volume
{ohlcv}"""

    snapshot = {
        "price": last, "date": str(df.index[-1].date()),
        "name": info.get("longName") or info.get("shortName") or ticker,
        "sector": info.get("sector"), "industry": info.get("industry"),
        "market_cap": info.get("marketCap"), "currency": info.get("currency", "INR"),
        "pe": info.get("trailingPE"), "forward_pe": info.get("forwardPE"),
        "pb": info.get("priceToBook"), "dividend_yield": info.get("dividendYield"),
        "beta_nifty": beta_nifty,
        "beta": info.get("beta"), "website": info.get("website"),
        "rsi": round(rsi, 1), "from_52w_high": _pct(last, hi52),
        "from_52w_low": _pct(last, lo52), "ret_1m": rets["1m"], "ret_1y": rets["1y"],
    }
    return {"indicator_block": ind_block, "snapshot": snapshot, "df": df,
            "close": close, "price": last, "info": info}
