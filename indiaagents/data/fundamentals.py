"""
Fundamentals from yfinance for NSE/BSE stocks — income statement, balance
sheet, cashflow (₹ crore, Indian formatting), plus key ratios.
Replaces the original repo's Alpha Vantage / SEC EDGAR (US-only) sources.
"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd
import yfinance as yf

from .market import inr


def _fmt_millions(v) -> str:
    """yfinance financials are in actual currency units for .NS (INR)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return inr(float(v))


def _r(v, nd=2, suffix=""):
    """NaN-safe ratio formatter — never prints 'nan'."""
    import math as _m
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    if _m.isnan(v) or _m.isinf(v):
        return "—"
    return f"{v:.{nd}f}{suffix}"


def _first_valid(*values):
    """First non-null scalar; unlike ``a or b``, NaN does not win."""
    for value in values:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            continue
        return value
    return None


def _asof_statement(stmt, trade_date: str | None):
    """Exclude fiscal periods ending after the requested analysis date.

    This is only a partial point-in-time guard: Yahoo does not expose the filing
    publication timestamp, so an older period may still have been published later.
    """
    if stmt is None or stmt.empty or not trade_date:
        return stmt
    try:
        asof = pd.Timestamp(datetime.strptime(trade_date, "%Y-%m-%d").date())
        keep = []
        for col in stmt.columns:
            try:
                if pd.Timestamp(col).tz_localize(None) <= asof:
                    keep.append(col)
            except (TypeError, ValueError):
                continue
        return stmt.loc[:, keep]
    except (TypeError, ValueError):
        return stmt


def _row(stmt, name: str, idx: int = 0):
    """Best-effort row lookup across yfinance's naming variants."""
    if stmt is None or stmt.empty:
        return None
    for key in stmt.index:
        if key.lower() == name.lower():
            return stmt.loc[key].iloc[idx] if len(stmt.columns) > idx else None
    for key in stmt.index:
        if name.lower() in key.lower():
            return stmt.loc[key].iloc[idx] if len(stmt.columns) > idx else None
    return None


def _growth(stmt, name: str) -> str:
    vals = None
    for key in stmt.index if stmt is not None and not stmt.empty else []:
        if key.lower() == name.lower():
            vals = stmt.loc[key]
            break
    if vals is None or len(vals) < 2:
        return "—"
    try:
        cur, prev = float(vals.iloc[0]), float(vals.iloc[1])
        import math as _m
        if prev == 0 or _m.isnan(cur) or _m.isnan(prev) or _m.isinf(cur) or _m.isinf(prev):
            return "—"
        return f"{(cur - prev) / abs(prev) * 100:+.1f}%"
    except Exception:
        return "—"


def _div_yield(info: dict) -> float | None:
    """Sahi dividend yield % — dividendRate/price se compute (2026 yfinance
    dividendYield already % mein aata hai, purane versions fraction dete the;
    rate/price deterministic hai)."""
    dr = info.get("dividendRate")
    px = info.get("currentPrice") or info.get("regularMarketPrice")
    if dr and px:
        try:
            return float(dr) / float(px) * 100
        except (TypeError, ValueError):
            return None
    dy = info.get("dividendYield")
    if dy is None:
        return None
    try:
        dy = float(dy)
        return dy if dy < 15 else dy / 100   # >15% yield rare — fraction maano
    except (TypeError, ValueError):
        return None


def get_fundamentals_data(ticker: str, trade_date: str | None = None) -> dict:
    """Return a compact fundamentals text block + dict of key figures."""
    t = yf.Ticker(ticker)
    inc = _asof_statement(t.income_stmt, trade_date)
    bal = _asof_statement(t.balance_sheet, trade_date)
    cf = _asof_statement(t.cashflow, trade_date)
    try:
        info = t.info or {}
    except Exception:
        info = {}

    def cols(stmt):
        return [c.year if hasattr(c, "year") else str(c)[:4] for c in stmt.columns] if stmt is not None and not stmt.empty else []

    years = cols(inc) or cols(bal) or []

    revenue = _row(inc, "Total Revenue")
    ebitda = _first_valid(_row(inc, "Normalized EBITDA"), _row(inc, "EBITDA"))
    op_income = _row(inc, "Operating Income")
    net_income = _row(inc, "Net Income")
    eps = _row(inc, "Diluted EPS")

    total_assets = _row(bal, "Total Assets")
    total_debt = _row(bal, "Total Debt")
    equity = _first_valid(_row(bal, "Stockholders Equity"),
                          _row(bal, "Total Stockholder Equity"))
    cash = _first_valid(_row(bal, "Cash And Cash Equivalents"),
                        _row(bal, "Cash Cash Equivalents And Short Term Investments"))
    current_assets = _row(bal, "Current Assets")
    current_liab = _row(bal, "Current Liabilities")

    ocf = _first_valid(_row(cf, "Operating Cash Flow"),
                       _row(cf, "Total Cash From Operating Activities"))
    capex = _row(cf, "Capital Expenditure")
    fcf = (ocf + capex) if (ocf is not None and capex is not None) else None
    buyback = _row(cf, "Repurchase Of Capital Stock")
    dividends = _row(cf, "Cash Dividends Paid")

    # ratios
    de_ratio = (total_debt / equity) if (total_debt is not None and equity not in (None, 0)) else None
    current_ratio = (current_assets / current_liab) if (current_assets is not None and current_liab not in (None, 0)) else None
    roe = (net_income / equity * 100) if (net_income is not None and equity not in (None, 0)) else None
    roa = (net_income / total_assets * 100) if (net_income is not None and total_assets not in (None, 0)) else None
    net_margin = (net_income / revenue * 100) if (net_income is not None and revenue not in (None, 0)) else None
    op_margin = (op_income / revenue * 100) if (op_income is not None and revenue not in (None, 0)) else None
    mcap = info.get("marketCap")

    historical_note = ""
    if trade_date:
        try:
            if datetime.strptime(trade_date, "%Y-%m-%d").date() < datetime.now().date():
                historical_note = (
                    "\n⚠️ HISTORICAL FUNDAMENTALS LIMITATION: statement periods after the "
                    "analysis date were removed, but Yahoo does not provide as-filed/publication "
                    "timestamps and market-snapshot ratios are current. Do NOT treat this block "
                    "as fully point-in-time or use it for leakage-free backtests.\n")
        except ValueError:
            pass
    sector = str(info.get("sector") or "")
    bank_note = ""
    if "financial" in sector.lower() or "bank" in str(info.get("industry") or "").lower():
        bank_note = ("\nBANK/NBFC NOTE: Debt-to-equity, current ratio and generic FCF are not "
                     "comparable to industrial companies. Prefer NIM, GNPA/NNPA, PCR, CAR/CET1, "
                     "CASA, credit cost and loan/deposit growth from exchange filings.\n")

    block = f"""FUNDAMENTAL DATA — {ticker} | FY years (newest first): {years[:4]}
(Values are latest available fiscal year unless noted; ₹ in Indian units){historical_note}{bank_note}

INCOME STATEMENT (latest FY):
- Total Revenue: {_fmt_millions(revenue)}  (YoY growth: {_growth(inc, 'Total Revenue')})
- Operating Income: {_fmt_millions(op_income)} | EBITDA: {_fmt_millions(ebitda)}
- Net Income: {_fmt_millions(net_income)}  (YoY growth: {_growth(inc, 'Net Income')})
- Diluted EPS: {_r(eps)}
- Operating Margin: {_r(op_margin, 1, '%')} | Net Margin: {_r(net_margin, 1, '%')}

BALANCE SHEET (latest FY):
- Total Assets: {_fmt_millions(total_assets)}
- Total Debt: {_fmt_millions(total_debt)} | Stockholders Equity: {_fmt_millions(equity)}
- Cash & Equivalents: {_fmt_millions(cash)}
- Debt-to-Equity: {_r(de_ratio)} | Current Ratio: {_r(current_ratio)}

CASH FLOW (latest FY):
- Operating Cash Flow: {_fmt_millions(ocf)}
- CapEx: {_fmt_millions(capex)} | Free Cash Flow (OCF−CapEx): {_fmt_millions(fcf)}
- Buybacks: {buyback and _fmt_millions(buyback)} | Dividends Paid: {dividends and _fmt_millions(dividends)}

MARKET SNAPSHOT:
- Market Cap: {inr(mcap) if mcap else '—'} | P/E (TTM): {_r(info.get('trailingPE'))} | Forward P/E: {_r(info.get('forwardPE'))}
- P/B: {_r(info.get('priceToBook'))} | Dividend Yield: {_r(_div_yield(info), 2, '%')}
- ROE: {_r(roe, 1, '%')} | ROA: {_r(roa, 1, '%')} | Beta (global/S&P, indicative): {_r(info.get('beta'))}
- Sector: {info.get('sector') or '—'} | Industry: {info.get('industry') or '—'}
- Shares Out: {f'{info["sharesOutstanding"] / 1e7:.2f} Cr shares' if info.get('sharesOutstanding') else '—'}

NOTE: Financial statement data is annual (Indian FY ends March). Verify promoter
shareholding, pledges and auditor notes from NSE/BSE filings — Yahoo doesn't carry them."""

    # ── MULTI-SOURCE: Screener.in independent fundamentals + P/E cross-check ──
    screener, screener_note = None, ""
    try:
        from .sources import get_screener_fundamentals, screener_text_block
        screener = get_screener_fundamentals(
            ticker, info.get("shortName") or info.get("longName"), trade_date)
        if screener:
            block += screener_text_block(screener)
            yf_pe, sc_pe = info.get("trailingPE"), screener.get("pe")
            if yf_pe and sc_pe:
                d = abs(float(yf_pe) - float(sc_pe)) / max(float(sc_pe), 0.01) * 100
                tag = ("⚠️ P/E CONFLICT >15% — Yahoo vs Screener numbers alag, "
                       "dono quote karo aur conservative use karo" if d > 15
                       else f"P/E cross-check: Yahoo {float(yf_pe):.1f} vs Screener "
                            f"{float(sc_pe):.1f} (diff {d:.0f}% — OK)")
                screener_note = tag
                block += f"\n\n[{tag}]"
    except Exception:
        pass

    return {
        "fundamentals_block": block,
        "key": {
            "revenue": revenue, "net_income": net_income, "market_cap": mcap,
            "pe": info.get("trailingPE"), "pb": info.get("priceToBook"),
            "roe": roe, "de_ratio": de_ratio, "fcf": fcf,
        },
        "screener": screener, "screener_note": screener_note,
    }
