"""
Report builder — ultra-premium Hinglish report.
Markdown (GitHub-ready) + standalone HTML with hero banner, KPI cards,
embedded price chart, verdict dashboard, model-battle scoreboard.
All styling is inline CSS (preview-safe, zero external assets).
"""
from __future__ import annotations

import html as _html
from datetime import datetime, timedelta, timezone

from .config import REPORTS_DIR

IST = timezone(timedelta(hours=5, minutes=30))

DISCLAIMER_MD = (
    "> ⚠️ **Disclaimer:** Ye report ek AI research simulation hai — **financial/investment "
    "advice NAHI**. Ye SEBI-registered advisor ki salah ka replacement nahi hai. Stock "
    "market mein risk hota hai; apna paisa lagane se pehle khud research karo aur zaroorat "
    "ho toh licensed advisor se baat karo. Historical performance future returns ki guarantee "
    "nahi hai. Free-tier AI models use hue hain, isliye accuracy ki koi guarantee nahi."
)

PROVIDER_STYLES = {
    "gemini":     ("#3b82f6", "#dbeafe", "Gemini"),
    "nvidia":     ("#22c55e", "#dcfce7", "NVIDIA"),
    "mistral":    ("#f97316", "#ffedd5", "Mistral"),
    "openrouter": ("#a855f7", "#f3e8ff", "OpenRouter"),
    "groq":       ("#ef4444", "#fee2e2", "Groq"),
    "mock":       ("#64748b", "#e2e8f0", "DEMO"),
}


def _verdict_emoji(d: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(d, "⚪")


def rnd(v, nd=2):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "—"


def indian_units(v):
    """market cap (raw ₹) -> ₹xx,xx,xxx Cr / L"""
    if not v:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    from .data.market import _indian_group
    if v >= 1e7:
        return f"₹{_indian_group(v / 1e7, 0)} Cr"
    if v >= 1e5:
        return f"₹{_indian_group(v / 1e5, 0)} L"
    return f"₹{_indian_group(v, 0)}"


def _md(text: str) -> str:
    """Markdown -> HTML for section bodies. LLM output ko pehle HTML-sanitize
    karta hai (script/iframe tags escape) — XSS safe render."""
    import re as _re
    t = str(text or "")
    # escape '<' only when it starts an HTML-looking tag (keeps math like "5 < 10" intact)
    escaped = _re.sub(r"<(?=[a-zA-Z/!])", "&lt;", t)
    try:
        import markdown as _m
        rendered = _m.markdown(escaped, extensions=["tables", "fenced_code", "sane_lists"])
        # Markdown links can still manufacture javascript:/data: URLs even after
        # raw tags are escaped. Allow only web/fragment links in LLM-authored text.
        rendered = _re.sub(
            r'''\s(href|src)=(['"])(?!https?://|#)[^'"]*\2''',
            r' \1="#"',
            rendered,
            flags=_re.IGNORECASE,
        )
        return rendered
    except ImportError:
        # markdown lib na ho to original text pe ek hi baar escape karo
        # (escaped text pe dobara escape karne se &amp;lt; double-escape ho jata)
        return f"<pre style='white-space:pre-wrap'>{_html.escape(t)}</pre>"


def _esc(x) -> str:
    return _html.escape(str(x if x is not None else "—"))


def _provider_badge(p: str) -> str:
    color, bg, label = PROVIDER_STYLES.get(p, ("#64748b", "#e2e8f0", p or "?"))
    return (f"<span class='pbadge' style='color:{color};background:{bg};"
            f"border:1px solid {color}40'>{_esc(label)}</span>")


def _deterministic_view(r: dict) -> dict:
    """New schema with a legacy-report fallback for saved/fixture reports."""
    if r.get("deterministic"):
        return r["deterministic"]
    dec = r.get("decision") or {}
    return {
        "action": dec.get("detailed_action") or dec.get("decision", "HOLD"),
        "legacy_action": dec.get("decision", "HOLD"), "setup_name": "Legacy plan",
        "signal_state": "unavailable", "trigger": dec.get("entry_zone", "—"),
        "entry_zone": None, "initial_stop": None, "stop_reason": "legacy output",
        "target_1": None, "target_2": None,
        "reward_risk": (dec.get("trade_validation") or {}).get("rr"),
        "quantity": dec.get("quantity", 0), "allocation_pct": dec.get("position_size_pct", 0),
        "allocation_rupees": 0, "max_loss_rupees": 0, "max_portfolio_loss_pct": 0,
        "invalidation": "—", "trailing_rule": "—", "time_stop_sessions": 0,
        "early_exit_rules": [], "confirmations": [], "missing_confirmations": [],
        "deterministic_reasons": [], "limitations": [], "support_zones": [],
        "resistance_zones": [], "relative_strength": {}, "weekly": {}, "daily": {},
        "evidence": {"status": "BACKTEST NOT AVAILABLE", "validated_edge": False,
                     "trades": 0, "walk_forward_windows": 0},
    }


def _zone_text(zone: dict | None) -> str:
    return (f"₹{float(zone['low']):,.2f}–₹{float(zone['high']):,.2f}"
            if zone and zone.get("low") is not None and zone.get("high") is not None else "—")


def _zones_text(zones: list[dict]) -> str:
    return "; ".join(
        f"₹{float(z['low']):,.2f}–₹{float(z['high']):,.2f} "
        f"({z.get('touches', 1)} touch, {z.get('source', 'structure')})"
        for z in zones[:4]
    ) or "unavailable"


def _rs_text(rs: dict) -> str:
    parts = []
    for key, label in (("nifty", "NIFTY"), ("sector", "Sector"), ("peer", "Peer")):
        item = rs.get(key) or {}
        if item.get("status") != "available":
            parts.append(f"{label}: unavailable")
        else:
            parts.append(
                f"{label}: 1M {item.get('1m_pct')}%, 3M {item.get('3m_pct')}%, "
                f"6M {item.get('6m_pct')}%, slope {item.get('slope_ann_pct')}% ({item.get('trend')})"
            )
    return " · ".join(parts) or "unavailable"


def _backtest_markdown(r: dict) -> str:
    bt = r.get("backtest")
    if not bt:
        return ("## B. Historical Evidence\n\n**BACKTEST NOT AVAILABLE** — current setup ko "
                "historical edge claim na samjhein. Explicit walk-forward run required.\n")
    m, gate = bt.get("metrics", {}), bt.get("acceptance", {})
    costs = (bt.get("aggregate") or {}).get("cost_config", {})
    rows = "\n".join(
        f"| {w.get('number')} | {w.get('train_start')} → {w.get('train_end')} | "
        f"{w.get('validation_start')} → {w.get('validation_end')} | "
        f"{w.get('test_start')} → {w.get('test_end')} |"
        for w in bt.get("windows", [])
    ) or "| — | — | — | — |"
    return f"""## B. Historical Evidence

**{gate.get('status', 'NO VALIDATED EDGE')}** · Scope: {gate.get('scope', 'stock-specific occurrences only')}

| Metric | Unseen OOS result | Metric | Unseen OOS result |
|---|---:|---|---:|
| Trades | {m.get('trades', 0)} | Win rate | {m.get('win_rate_pct', 0)}% |
| Profit factor | {m.get('profit_factor', '—')} | Expectancy | {m.get('expectancy_r', 0)}R |
| Net return after costs | {m.get('net_total_return_pct', 0)}% | CAGR | {m.get('cagr_pct', '—')}% |
| Max drawdown | {m.get('max_drawdown_pct', 0)}% | Sharpe / Sortino | {m.get('sharpe', '—')} / {m.get('sortino', '—')} |
| NIFTY-relative alpha | {m.get('nifty_relative_alpha_pct', '—')}% | Exposure | {m.get('exposure_pct', 0)}% |
| Stop hit / gap loss | {m.get('stop_loss_hit_rate_pct', 0)}% / {m.get('gap_loss_frequency_pct', 0)}% | Longest losing streak | {m.get('longest_losing_streak', 0)} |

**Bootstrap uncertainty:** {m.get('bootstrap', {}).get('status', 'unavailable')} · expectancy 95% CI {m.get('bootstrap', {}).get('expectancy_r', '—')}

**Costs:** brokerage {costs.get('brokerage_pct', '—')}%, STT buy/sell {costs.get('stt_buy_pct', '—')}%/{costs.get('stt_sell_pct', '—')}%, exchange {costs.get('exchange_pct', '—')}%, GST {costs.get('gst_pct', '—')}%, stamp buy {costs.get('stamp_buy_pct', '—')}%, slippage {costs.get('slippage_bps', '—')} bps, impact {costs.get('impact_bps', '—')} bps.

| Window | Training | Validation | Unseen test |
|---:|---|---|---|
{rows}

Failed acceptance checks: {', '.join(gate.get('failed_reasons') or []) or 'none'}.
"""


# ===========================================================================
# MARKDOWN REPORT
# ===========================================================================

def build_markdown(r: dict) -> str:
    dec = r["decision"]
    det = _deterministic_view(r)
    snap = r["snapshot"]
    price = r["price"]
    ev = det.get("evidence") or {}
    bt_md = _backtest_markdown(r)

    stats = r.get("stats", {})
    scoreboard_rows = "\n".join(
        f"| {_provider_badge_md(p)} | {', '.join(d.get('models', []))} | "
        f"{d.get('ok', 0)} ✅ / {d.get('fail', 0)} ❌ | "
        f"{', '.join(sorted(set(d.get('roles', [])))[:8])} |"
        for p, d in stats.items()
    ) or "| — | — | — | — |"

    _reg = (r.get('decision') or {}).get('regime')
    _regband = (r.get('decision') or {}).get('regime_band')
    _q = r.get("quant") or {}
    qline = (f"**{_q['score']:.0f}/100** (model-implied 10-day signal {_q.get('exp_ret_10d_pct', 0):+.2f}%, "
             f"model val IC {_q.get('val_ic', '—')})" if _q.get("score") is not None else "—")
    _ds = r.get("data_sources") or {}
    ds_text = _ds.get("text") or "—"
    ds_quality = _ds.get("data_quality") or ""
    _nr = r.get("next_results")
    _dq = r.get("data_quality") or {}
    _tv = dec.get("trade_validation") or {}
    _rr = f"1:{_tv['rr']:.2f}" if _tv.get("rr") is not None else "unverified"
    md = f"""# 📊 {r['name']} ({r['ticker']}) — AI Trading Desk Research Report

*Generated: {datetime.now(IST).strftime('%d %b %Y, %H:%M')} IST · Analysis date: {r['trade_date']} · {r['exchange']}*
*Engine: TradingAgents India — free multi-model battle (inspired by TauricResearch/TradingAgents)*
{("*🎮 DEMO MODE — data real hai, AI text mock hai.*" if r.get("mock") else "")}

---

## 🎯 FINAL VERDICT — Deterministic Code Authority

**{det.get('action', 'REVIEW')} · {det.get('setup_name', '—')} · Signal {det.get('signal_state', '—')}**

| | | | |
|---|---|---|---|
| **Price** | ₹{price:,.2f} | **Entry zone** | {_zone_text(det.get('entry_zone'))} |
| **Trigger** | {det.get('trigger', '—')} | **Initial stop** | {('₹' + format(float(det['initial_stop']), ',.2f')) if det.get('initial_stop') is not None else '—'} |
| **T1 / T2** | {det.get('target_1', '—')} / {det.get('target_2', '—')} | **R:R (to T2)** | {det.get('reward_risk', '—')} |
| **Quantity** | {det.get('quantity', 0)} | **Allocation** | ₹{float(det.get('allocation_rupees', 0)):,.2f} ({det.get('allocation_pct', 0)}%) |
| **Maximum loss** | ₹{float(det.get('max_loss_rupees', 0)):,.2f} | **Portfolio loss** | {det.get('max_portfolio_loss_pct', 0)}% |
| **Evidence** | {ev.get('status', 'BACKTEST NOT AVAILABLE')} | **OOS sample/windows** | {ev.get('trades', 0)} / {ev.get('walk_forward_windows', 0)} |
| **Market Regime** | {_reg or det.get('weekly', {}).get('trend_state', '—')} | **Position band** | {_regband or '—'} |
| **Data quality** | {_dq.get('score', '—')}/100 ({_dq.get('level', '—')}) | **Time stop** | {det.get('time_stop_sessions', 0)} sessions |

**Setup invalidation:** {det.get('invalidation', '—')}

**Stop reason:** {det.get('stop_reason', '—')}

**Trailing:** {det.get('trailing_rule', '—')}

**Support zones:** {_zones_text(det.get('support_zones') or [])}

**Resistance zones:** {_zones_text(det.get('resistance_zones') or [])}

**Relative strength:** {_rs_text(det.get('relative_strength') or {})}

**Confirmed:** {'; '.join(det.get('confirmations') or []) or 'none'}

**Missing confirmations:** {'; '.join(det.get('missing_confirmations') or []) or 'none'}

**Deterministic reasons:** {'; '.join(det.get('deterministic_reasons') or []) or '—'}

**Data/integrity limitations:** {'; '.join(det.get('limitations') or _dq.get('issues') or []) or 'none reported'}

> 🔒 Entry, exit, stop, targets, size, action aur backtest numbers deterministic code-owned hain. LLM inhe override nahi kar sakta.

---

{bt_md}

---

## C. Why This Action / Separate AI Commentary

**AI-proposed legacy call (non-authoritative):** {(r.get('ai_decision') or {}).get('decision', '—')} · AI prose confidence is not a strategy statistic and is not displayed as trade confidence.

**AI rationale:** {(r.get('ai_decision') or dec).get('rationale', '—')}

**AI key risks:** {', '.join(str(k) for k in (r.get('ai_decision') or dec).get('key_risks', [])) or '—'}

**⚔️ AI battle notes:** {(r.get('ai_decision') or dec).get('battle_notes', '—')}

---

## 🤖 Model Battle Scoreboard

| Provider | Model(s) | Calls | Roles |
|---|---|---|---|
{scoreboard_rows}

---

## I. Company Snapshot

- **Company:** {r['name']} ({r['ticker']}, {r['exchange']})
- **Sector:** {snap.get('sector') or '—'} / {snap.get('industry') or '—'}
- **Market Cap:** {indian_units(snap.get('market_cap'))}
- **P/E:** {rnd(snap.get('pe'))} · **P/B:** {rnd(snap.get('pb'))} · **Beta:** {rnd(snap.get('beta'))}
- **Price:** ₹{price:,.2f} (52w-high se {snap.get('from_52w_high')}% neeche, 52w-low se {snap.get('from_52w_low')}% upar)
- **ML Quant Score:** {qline}
- **RSI(14):** {snap.get('rsi')} · **1M:** {snap.get('ret_1m')}% · **1Y:** {snap.get('ret_1y')}%
- **🔌 Data sources:** {ds_text}{' · ' + ds_quality if ds_quality else ''}

{r['market_context_block']}

---

## II. Analyst Team Reports

### 📈 A. Technical / Market Analyst
{r['analyst_reports'].get('market', '—')}

### 💰 B. Fundamentals Analyst
{r['analyst_reports'].get('fundamentals', '—')}

### 📰 C. News & Macro Analyst
{r['analyst_reports'].get('news', '—')}

### 💬 D. Sentiment / Social Analyst
{r['analyst_reports'].get('social', '—')}

---

## III. Research Team — Bull 🐂 vs Bear 🐻 Debate

{r['debate'] or '*(debate unavailable)*'}

### ⚖️ Research Manager Verdict (draft)
{r['draft_verdict'] or '—'}

---

## IV. ⚔️ Model Battle Round (Cross-AI Red Team)

{r['battle_critiques'] or '*(battle mode off tha is run mein)*'}

### 🔬 Final Research Verdict (post-battle, synthesized)
{r['final_research'] or '—'}

---

## V. Trading Team Plan

{r['trader_plan'] or '—'}

---

## VI. Risk Management Team

{r['risk_views'] or '—'}

---

## VII. Past Decisions & Memory

{r.get('memory', '—')}

---

## Appendix: Raw Data

<details><summary>Technical data block</summary>

```
{r['indicator_block']}
```

</details>

<details><summary>Fundamentals data block</summary>

```
{r['fundamentals_block']}
```

</details>

<details><summary>Company news headlines</summary>

```
{r['news_block']}
```

</details>

<details><summary>India macro news</summary>

```
{r['macro_news_block']}
```

</details>

<details><summary>Global macro (FRED)</summary>

```
{r.get('fred_block', '—')}
```

</details>

<details><summary>Social chatter</summary>

```
{r['social_block']}
```

</details>

---

{DISCLAIMER_MD}
"""
    return md


def _provider_badge_md(p: str) -> str:
    return f"`{p}`"


# ===========================================================================
# PREMIUM HTML REPORT
# ===========================================================================

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#070d1a;--card:#0e1626;--card2:#111c30;--line:#1c2a44;--txt:#e6edf7;
--muted:#8b9bb8;--accent:#38bdf8;--good:#22c55e;--bad:#ef4444;--warn:#eab308}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:
radial-gradient(1200px 600px at 80% -10%,#0f2038 0%,var(--bg) 55%) fixed;color:var(--txt);
line-height:1.65;font-size:15px}
.wrap{max-width:1060px;margin:0 auto;padding:26px 18px 70px}
.card{background:linear-gradient(180deg,var(--card) 0%,var(--card2) 100%);
border:1px solid var(--line);border-radius:18px;padding:24px 28px;margin:16px 0;
box-shadow:0 8px 30px rgba(0,0,0,.35)}
.hero{position:relative;overflow:hidden;border-radius:20px;padding:30px 34px;margin-bottom:16px;
background:linear-gradient(135deg,#0b1c33 0%,#0d2742 55%,#123252 100%);
border:1px solid #24406b}
.hero::after{content:'';position:absolute;inset:0;background:
radial-gradient(600px 200px at 15% -30%,rgba(56,189,248,.18),transparent),
radial-gradient(500px 220px at 95% 130%,rgba(34,197,94,.12),transparent);pointer-events:none}
.hero .brand{font-size:11px;letter-spacing:3px;color:var(--accent);text-transform:uppercase;
font-weight:700;margin-bottom:10px}
.hero h1{font-size:30px;font-weight:800;letter-spacing:.3px}
.hero .meta{color:var(--muted);font-size:13px;margin-top:6px}
.tkr{display:inline-block;background:rgba(56,189,248,.12);border:1px solid rgba(56,189,248,.4);
color:#7dd3fc;border-radius:8px;padding:2px 10px;font-weight:700;font-size:13px;margin-left:8px}
.verdict-row{display:flex;flex-wrap:wrap;align-items:center;gap:18px;margin-top:20px}
.vpill{font-size:34px;font-weight:900;letter-spacing:2px;padding:10px 30px;border-radius:14px;
display:inline-flex;align-items:center;gap:10px}
.v-buy{color:#4ade80;background:rgba(34,197,94,.12);border:2px solid #22c55e;
box-shadow:0 0 34px rgba(34,197,94,.25)}
.v-sell{color:#f87171;background:rgba(239,68,68,.12);border:2px solid #ef4444;
box-shadow:0 0 34px rgba(239,68,68,.25)}
.v-hold{color:#fde047;background:rgba(234,179,8,.10);border:2px solid #eab308;
box-shadow:0 0 34px rgba(234,179,8,.2)}
.vmeta{color:var(--txt)}
.vmeta .rating{font-size:17px;font-weight:700}
.confwrap{flex:1;min-width:220px}
.conflabel{display:flex;justify-content:space-between;font-size:12px;color:var(--muted);
margin-bottom:5px}
.confbar{height:12px;background:#0a1526;border-radius:8px;border:1px solid var(--line);
overflow:hidden}
.conffill{height:100%;border-radius:8px;background:linear-gradient(90deg,#38bdf8,#22c55e)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:16px 0}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.kpi .l{font-size:11px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);
font-weight:700}
.kpi .v{font-size:19px;font-weight:800;margin-top:3px}
.kpi .s{font-size:11.5px;color:var(--muted)}
.pos{color:#4ade80}.neg{color:#f87171}.neu{color:#fde047}
h2.sec{display:flex;align-items:center;gap:12px;font-size:19px;font-weight:800;
margin:34px 0 6px;letter-spacing:.3px}
.secnum{background:linear-gradient(135deg,#1d4ed8,#38bdf8);color:#fff;font-size:12px;
font-weight:800;border-radius:9px;padding:4px 11px;letter-spacing:1px}
.chartwrap{margin:8px 0 4px;border-radius:14px;overflow:hidden;border:1px solid var(--line)}
.chartwrap img{width:100%;display:block}
.trade-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:14px 0}
.tg{background:#0a1526;border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.tg .l{font-size:10.5px;text-transform:uppercase;letter-spacing:1.2px;color:var(--muted);font-weight:700}
.tg .v{font-size:15.5px;font-weight:700;margin-top:3px}
.risks{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.risk{background:rgba(239,68,68,.08);border:1px solid rgba(239,68,68,.35);color:#fca5a5;
border-radius:999px;padding:4px 13px;font-size:12.5px}
.pbadge{display:inline-block;border-radius:999px;padding:2px 11px;font-size:11.5px;
font-weight:800;letter-spacing:.5px;margin:0 4px 6px 0}
table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}
th,td{border:1px solid var(--line);padding:8px 12px;text-align:left}
th{background:#0a1526;color:#93c5fd;font-size:12px;text-transform:uppercase;letter-spacing:1px}
tr:nth-child(even){background:rgba(28,42,68,.25)}
blockquote{border-left:4px solid #f59e0b;background:rgba(245,158,11,.07);padding:12px 18px;
border-radius:0 10px 10px 0;margin:12px 0;font-size:13.5px}
code,pre{background:#0a1526;border-radius:8px;font-size:.92em}
pre{padding:14px;overflow-x:auto;border:1px solid var(--line)}
a{color:#7dd3fc}
hr{border:none;border-top:1px solid var(--line);margin:26px 0}
h3{color:#a5b4fc;margin:18px 0 8px;font-size:16px}
h4{color:#c4b5fd;margin:14px 0 6px;font-size:14.5px}
details{background:#0a1526;border:1px solid var(--line);border-radius:12px;padding:10px 16px;
margin:10px 0}
summary{cursor:pointer;color:#93c5fd;font-weight:700;font-size:13.5px}
.footer{color:var(--muted);font-size:12px;text-align:center;margin-top:34px}
.modelnote{font-size:12px;color:var(--muted);margin-top:4px}
@media print{body{background:#fff;color:#111}.card,.hero{background:#fff;border-color:#ccc;
box-shadow:none}h2,h3,.kpi .v{color:#111}}
"""


def build_html(r: dict) -> str:
    dec = r["decision"]
    det = _deterministic_view(r)
    snap = r["snapshot"]
    price = r["price"]
    d = str(det.get("action") or dec["decision"]).upper()
    vclass = {"BUY": "v-buy", "ENTER": "v-buy", "ADD": "v-buy",
              "SELL": "v-sell", "TRIM": "v-sell", "EXIT": "v-sell",
              "HOLD": "v-hold", "WAIT": "v-hold", "REVIEW": "v-hold"}.get(d, "v-hold")
    vicon = {"BUY": "🟢", "ENTER": "🟢", "ADD": "🟢", "SELL": "🔴",
             "TRIM": "🟠", "EXIT": "🔴", "HOLD": "🟡", "WAIT": "🟡",
             "REVIEW": "⚠️"}.get(d, "⚪")
    conf = int(dec.get("confidence", 0) or 0)
    _reg = (r.get("decision") or {}).get("regime")
    _regband = (r.get("decision") or {}).get("regime_band")
    _q = r.get("quant") or {}
    _ds = r.get("data_sources") or {}
    ds_text = _ds.get("text") or "—"
    ds_quality = _ds.get("data_quality") or ""
    _dq = r.get("data_quality") or {}
    _tv = dec.get("trade_validation") or {}
    _rr = f"1:{float(_tv['rr']):.2f}" if _tv.get("rr") is not None else "unverified"
    if _q.get("score") is not None:
        _qs = float(_q["score"])
        _qcol = "pos" if _qs >= 60 else "neg" if _qs < 40 else ""
        quant_kpi = (f"<div class='kpi'><div class='l'>ML Quant Score</div>"
                     f"<div class='v {_qcol}'>{_qs:.0f}/100</div>"
                     f"<div class='s'>model signal 10d {_q.get('exp_ret_10d_pct', 0):+.2f}% · IC {_q.get('val_ic', '—')}</div></div>")
    else:
        quant_kpi = ""

    def cls(v):
        try:
            return "pos" if float(v) > 0 else "neg" if float(v) < 0 else "neu"
        except (TypeError, ValueError):
            return "neu"

    kpis = f"""
    <div class='kpis'>
      <div class='kpi'><div class='l'>Price</div><div class='v'>₹{price:,.2f}</div>
        <div class='s'>{snap.get('date','')} · {r['exchange']}</div></div>
      <div class='kpi'><div class='l'>Market Cap</div><div class='v'>{indian_units(snap.get('market_cap'))}</div>
        <div class='s'>{_esc(snap.get('sector') or '—')}</div></div>
      <div class='kpi'><div class='l'>P/E · P/B</div><div class='v'>{rnd(snap.get('pe'))} · {rnd(snap.get('pb'))}</div>
        <div class='s'>Beta {rnd(snap.get('beta'))}</div></div>
      <div class='kpi'><div class='l'>RSI (14)</div><div class='v'>{rnd(snap.get('rsi'), 1)}</div>
        <div class='s'>{'Overbought' if (snap.get('rsi') or 50) > 70 else 'Oversold' if (snap.get('rsi') or 50) < 30 else 'Neutral'}</div></div>
      {quant_kpi}
      <div class='kpi'><div class='l'>Data Quality</div><div class='v'>{_esc(_dq.get('score', '—'))}/100</div>
        <div class='s'>{_esc(_dq.get('level', '—'))} · R:R {_esc(_rr)}</div></div>
      <div class='kpi'><div class='l'>Market Regime</div><div class='v'>{_esc((_reg or '—').replace('_', ' '))}</div>
        <div class='s'>position band {_esc(_regband or '—')} · hard discipline</div></div>
      <div class='kpi'><div class='l'>1M Return</div><div class='v {cls(snap.get('ret_1m'))}'>{rnd(snap.get('ret_1m'), 1)}%</div>
        <div class='s'>1Y: <span class='{cls(snap.get('ret_1y'))}'>{rnd(snap.get('ret_1y'), 1)}%</span></div></div>
      <div class='kpi'><div class='l'>From 52W High</div><div class='v {cls(snap.get('from_52w_high'))}'>{rnd(snap.get('from_52w_high'), 1)}%</div>
        <div class='s'>Low se +{rnd(abs(snap.get('from_52w_low') or 0), 1)}% upar</div></div>
    </div>"""

    chart_html = ""
    if r.get("chart_b64"):
        chart_html = (f"<div class='chartwrap'><img alt='price chart' "
                      f"src='data:image/png;base64,{r['chart_b64']}'></div>")

    risks = "".join(f"<span class='risk'>⚠️ {_esc(k)}</span>"
                    for k in ((r.get('ai_decision') or dec).get("key_risks") or [])) or "<span class='risk'>—</span>"
    _ev = det.get("evidence") or {}
    _confirm_text = ("Confirmed: " + ("; ".join(det.get("confirmations") or []) or "none")
                     + "\n\nMissing: " + ("; ".join(det.get("missing_confirmations") or []) or "none"))
    _zone_summary = ("Support: " + _zones_text(det.get("support_zones") or [])
                     + "\n\nResistance: " + _zones_text(det.get("resistance_zones") or []))
    _exit_summary = (str(det.get("trailing_rule", "—")) + "\n\n"
                     + "; ".join(det.get("early_exit_rules") or []))
    _relative_summary = _rs_text(det.get("relative_strength") or {})
    det_card = f"""
    <div class='trade-grid'>
      <div class='tg'><div class='l'>Setup / state</div><div class='v'>{_esc(det.get('setup_name'))} · {_esc(det.get('signal_state'))}</div></div>
      <div class='tg'><div class='l'>Entry zone</div><div class='v'>{_esc(_zone_text(det.get('entry_zone')))}</div></div>
      <div class='tg'><div class='l'>Initial stop</div><div class='v'>{('₹' + format(float(det['initial_stop']), ',.2f')) if det.get('initial_stop') is not None else '—'}</div></div>
      <div class='tg'><div class='l'>T1 / T2</div><div class='v'>{_esc(det.get('target_1'))} / {_esc(det.get('target_2'))}</div></div>
      <div class='tg'><div class='l'>R:R</div><div class='v'>{_esc(det.get('reward_risk'))}</div></div>
      <div class='tg'><div class='l'>Quantity / allocation</div><div class='v'>{_esc(det.get('quantity', 0))} · {_esc(det.get('allocation_pct', 0))}%</div></div>
      <div class='tg'><div class='l'>Maximum loss</div><div class='v'>₹{float(det.get('max_loss_rupees', 0)):,.2f} ({_esc(det.get('max_portfolio_loss_pct', 0))}%)</div></div>
      <div class='tg'><div class='l'>Historical evidence</div><div class='v'>{_esc(_ev.get('status', 'BACKTEST NOT AVAILABLE'))}</div></div>
      <div class='tg'><div class='l'>Market Regime</div><div class='v'>{_esc(_reg or (det.get('weekly') or {}).get('trend_state', '—'))} · {_esc(_regband or '—')}</div></div>
    </div>
    <h3>Trigger</h3>{_md(det.get('trigger', '—'))}
    <h3>Stop reason / invalidation</h3>{_md(str(det.get('stop_reason', '—')) + ' · ' + str(det.get('invalidation', '—')))}
    <h3>Confirmed / missing</h3>{_md(_confirm_text)}
    <h3>Support / resistance zones</h3>{_md(_zone_summary)}
    <h3>Relative strength</h3>{_md(_relative_summary)}
    <h3>Exit discipline</h3>{_md(_exit_summary)}
    <h3>Limitations</h3>{_md('; '.join(det.get('limitations') or []) or 'None reported')}
    <blockquote>🔒 LLM cannot override code-owned action, entry, stop, targets, quantity or backtest statistics.</blockquote>
    """
    backtest_html = _md(_backtest_markdown(r))

    score_rows = ""
    for p, s in (r.get("stats") or {}).items():
        models = ", ".join(f"<code>{_esc(m)}</code>" for m in s.get("models", []))
        roles = ", ".join(sorted(set(s.get("roles", [])))[:9])
        score_rows += (f"<tr><td>{_provider_badge(p)}</td><td>{models}</td>"
                       f"<td style='white-space:nowrap'>{s.get('ok',0)} ✅ / "
                       f"{s.get('fail',0)} ❌</td><td style='font-size:12px'>{_esc(roles)}</td></tr>")

    def sec(num, icon, title, body, sub=""):
        subh = f"<div class='modelnote'>{_esc(sub)}</div>" if sub else ""
        return (f"<h2 class='sec'><span class='secnum'>{num}</span>{icon} {_esc(title)}</h2>"
                f"{subh}<div class='card'>{body}</div>")

    ar = r["analyst_reports"]
    analysts_html = "".join(
        f"<h3>{icon} {t}</h3>{_md(ar.get(k, '—'))}<hr>"
        for (icon, t, k) in [
            ("📈", "Technical / Market Analyst", "market"),
            ("💰", "Fundamentals Analyst", "fundamentals"),
            ("📰", "News & Macro Analyst", "news"),
            ("💬", "Sentiment / Social Analyst", "social"),
        ])

    demo_banner = ("<div class='card' style='border-color:#eab308'>🎮 <b>DEMO MODE</b> — "
                   "data (price, financials, news) 100% real hai; sirf AI text mock hai. "
                   "Real AI analysis ke liye keys configure karo.</div>") if r.get("mock") else ""

    html_doc = f"""<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(r['name'])} ({_esc(r['ticker'])}) — AI Research Report</title>
<style>{CSS}</style>
</head>
<body>
<div class='wrap'>

<div class='hero'>
  <div class='brand'>⚡ TradingAgents India · Multi-Model AI Research Desk</div>
  <h1>{_esc(r['name'])}<span class='tkr'>{_esc(r['ticker'])}</span></h1>
  <div class='meta'>Generated {datetime.now(IST).strftime('%d %b %Y, %H:%M')} IST ·
  Analysis date: {_esc(r['trade_date'])} · Free-tier multi-model battle engine
  {('(DEMO)' if r.get('mock') else '')}</div>
  <div class='verdict-row'>
    <div class='vpill {vclass}'>{vicon} {d}</div>
    <div class='vmeta'>
      <div class='rating'>{_esc(det.get('setup_name', '—'))}</div>
      <div class='modelnote'>Signal {_esc(det.get('signal_state', '—'))} · deterministic-v1</div>
    </div>
    <div class='confwrap'>
      <div class='conflabel'><span>Historical evidence</span><span>{_esc(_ev.get('status', 'BACKTEST NOT AVAILABLE'))}</span></div>
      <div class='modelnote'>AI prose confidence is not used as strategy confidence.</div>
    </div>
  </div>
</div>

{demo_banner}
{kpis}
{chart_html}

<h2 class='sec'><span class='secnum'>A</span>🎯 Current Deterministic Setup</h2>
<div class='card'>{det_card}</div>

<h2 class='sec'><span class='secnum'>B</span>📊 Historical Evidence</h2>
<div class='card'>{backtest_html}</div>

<h2 class='sec'><span class='secnum'>C</span>🧠 Why This Action / Separate AI Commentary</h2>
<div class='card'>
  <h3>Deterministic reasons</h3>{_md('; '.join(det.get('deterministic_reasons') or []) or '—')}
  <h3>AI rationale (non-authoritative)</h3>{_md((r.get('ai_decision') or dec).get('rationale', '—'))}
  <h3>AI key risks</h3><div class='risks'>{risks}</div>
  <h3>⚔️ AI battle notes</h3>{_md((r.get('ai_decision') or dec).get('battle_notes', '—'))}
</div>

<h2 class='sec'><span class='secnum'>AI</span>🤖 Model Battle Scoreboard</h2>
<div class='card'>
  <table><tr><th>Provider</th><th>Model</th><th>Calls</th><th>Roles played</th></tr>
  {score_rows or '<tr><td colspan=4>—</td></tr>'}</table>
  <div class='modelnote'>Alag-alag AI families (Gemini / NVIDIA Nemotron / Mistral / OpenRouter)
  ne alag-alag roles nibhaye aur ek dusre ki research red-team ki.</div>
</div>

{sec('I', '📊', 'Company Snapshot & Market Context',
     f"<div class='modelnote'>Sector: {_esc(snap.get('sector') or '—')} · Industry: {_esc(snap.get('industry') or '—')}</div>"
     + (f"<div class='modelnote'>🔌 Data sources: {_esc(ds_text)}"
        + (f" · {_esc(ds_quality)}" if ds_quality else "") + "</div>")
     + _md(r['market_context_block']))}

{sec('II', '🔍', 'Analyst Team Reports', analysts_html,
     '4 specialists: technicals, fundamentals, news, social sentiment')}

{sec('III', '⚖️', 'Bull 🐂 vs Bear 🐻 Debate + Research Manager', _md(r['debate'] or '—')
     + '<hr><h3>⚖️ Research Manager (draft verdict)</h3>' + _md(r['draft_verdict'] or '—'))}

{sec('IV', '⚔️', 'Model Battle — Cross-AI Red Team', _md(r['battle_critiques'] or '*(battle off)*')
     + '<hr><h3>🔬 Final Research Verdict (post-battle)</h3>' + _md(r['final_research'] or '—'),
     'Har model ne baaki sab ki research ka factual audit, logic audit, blind spots, agree/disagree kiya')}

{sec('V', '💸', 'Trader Execution Plan', _md(r['trader_plan'] or '—'))}

{sec('VI', '🛡️', 'Risk Management Team', _md(r['risk_views'] or '—'),
     'Aggressive vs Conservative vs Neutral — 3-way debate')}

{sec('VII', '🧠', 'Past Decisions & Memory', _md(r.get('memory', '—')))}

<h2 class='sec'><span class='secnum'>DATA</span>📎 Raw Data Appendix</h2>
<div class='card'>
<details><summary>📈 Technical data</summary><pre>{_esc(r['indicator_block'])}</pre></details>
<details><summary>💰 Fundamentals data</summary><pre>{_esc(r['fundamentals_block'])}</pre></details>
<details><summary>📰 Company news</summary><pre>{_esc(r['news_block'])}</pre></details>
<details><summary>🇮🇳 India macro news</summary><pre>{_esc(r['macro_news_block'])}</pre></details>
<details><summary>🌍 Global macro (FRED)</summary><pre>{_esc(r.get('fred_block', '—'))}</pre></details>
<details><summary>💬 Social chatter</summary><pre>{_esc(r['social_block'])}</pre></details>
</div>

<div class='card' style='border-color:#f59e0b55'>
<blockquote>{DISCLAIMER_MD[2:]}</blockquote>
</div>

<div class='footer'>
  TradingAgents India · Free-tier multi-agent research (Gemini × NVIDIA × Mistral × OpenRouter)<br>
  Architecture inspired by TauricResearch/TradingAgents (Apache-2.0) · Data: Yahoo Finance,
  Google News India, Reddit, FRED · Report self-contained — koi external asset nahi
</div>

</div>
</body>
</html>"""
    return html_doc


# ===========================================================================
# SAVE
# ===========================================================================

def build_report(r: dict) -> dict:
    """Save markdown + premium HTML + chart; return paths."""
    out_dir = REPORTS_DIR / f"{r['ticker'].replace('.', '_').replace('^', 'IDX_')}_{r['trade_date']}"
    out_dir.mkdir(parents=True, exist_ok=True)
    md = build_markdown(r)
    if r.get("chart_png"):
        (out_dir / "chart.png").write_bytes(r["chart_png"])
        md = md.replace("## 🤖 Model Battle Scoreboard",
                        "![Price Chart](chart.png)\n\n## 🤖 Model Battle Scoreboard")
    md_path = out_dir / "report.md"
    md_path.write_text(md, encoding="utf-8")
    html_path = out_dir / "report.html"
    html_path.write_text(build_html(r), encoding="utf-8")
    return {"dir": str(out_dir), "md": str(md_path), "html": str(html_path)}
