"""
Fundamentals from yfinance for NSE/BSE stocks — income statement, balance
sheet, cashflow (₹ crore, Indian formatting), plus key ratios.
Replaces the original repo's Alpha Vantage / SEC EDGAR (US-only) sources.
"""
from __future__ import annotations

import math

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


def get_fundamentals_data(ticker: str, trade_date: str | None = None) -> dict:
    """Return a compact fundamentals text block + dict of key figures."""
    t = yf.Ticker(ticker)
    inc = t.income_stmt
    bal = t.balance_sheet
    cf = t.cashflow
    info = t.info or {}

    def cols(stmt):
        return [c.year if hasattr(c, "year") else str(c)[:4] for c in stmt.columns] if stmt is not None and not stmt.empty else []

    years = cols(inc) or cols(bal) or []

    revenue = _row(inc, "Total Revenue")
    ebitda = _row(inc, "Normalized EBITDA") or _row(inc, "EBITDA")
    op_income = _row(inc, "Operating Income")
    net_income = _row(inc, "Net Income")
    eps = _row(inc, "Diluted EPS")

    total_assets = _row(bal, "Total Assets")
    total_debt = _row(bal, "Total Debt")
    equity = _row(bal, "Stockholders Equity") or _row(bal, "Total Stockholder Equity")
    cash = _row(bal, "Cash And Cash Equivalents") or _row(bal, "Cash Cash Equivalents And Short Term Investments")
    current_assets = _row(bal, "Current Assets")
    current_liab = _row(bal, "Current Liabilities")

    ocf = _row(cf, "Operating Cash Flow") or _row(cf, "Total Cash From Operating Activities")
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

    block = f"""FUNDAMENTAL DATA — {ticker} | FY years (newest first): {years[:4]}
(Values are latest fiscal year unless noted; ₹ in Indian units)

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
- P/B: {_r(info.get('priceToBook'))} | Dividend Yield: {_r((info.get('dividendYield') or 0) * 100 if info.get('dividendYield') else None, 2, '%')}
- ROE: {_r(roe, 1, '%')} | ROA: {_r(roa, 1, '%')} | Beta: {_r(info.get('beta'))}
- Sector: {info.get('sector') or '—'} | Industry: {info.get('industry') or '—'}
- Shares Out: {info.get("sharesOutstanding") and f"{info["sharesOutstanding"] / 1e7:.2f} Cr shares" or "—"}

NOTE: Financial statement data is annual (Indian FY ends March). Verify promoter
shareholding, pledges and auditor notes from NSE/BSE filings — Yahoo doesn't carry them."""

    return {
        "fundamentals_block": block,
        "key": {
            "revenue": revenue, "net_income": net_income, "market_cap": mcap,
            "pe": info.get("trailingPE"), "pb": info.get("priceToBook"),
            "roe": roe, "de_ratio": de_ratio, "fcf": fcf,
        },
    }
