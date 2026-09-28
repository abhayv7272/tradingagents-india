"""
📈 TradingAgents India — Premium Web Dashboard
Stock ka naam dalo → free AI models ki multi-agent team poori research report banayegi.

Run:  streamlit run app.py
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from indiaagents.config import REPORTS_DIR, Settings, available_providers, get_api_keys  # noqa: E402
from indiaagents.pipeline import TradingAgentsIndiaPipeline  # noqa: E402
from indiaagents.strategy import PortfolioInputs  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def _e(x):
    """HTML-escape helper."""
    import html as _h
    return _h.escape(str(x if x is not None else "—"))

st.set_page_config(page_title="TradingAgents India", page_icon="📈",
                   layout="wide", initial_sidebar_state="expanded")

if "result" not in st.session_state:
    st.session_state.result = None

CSS = """
<style>
    .big-title{font-size:2.6rem;font-weight:800;letter-spacing:-.5px;margin-bottom:0;
        background:linear-gradient(90deg,#22c55e,#38bdf8 55%,#a78bfa);
        -webkit-background-clip:text;-webkit-text-fill-color:transparent}
    .sub{color:#8b9bb8;margin-top:.15rem;font-size:1.02rem}
    .glass{background:rgba(240,244,255,.045);border:1px solid rgba(148,163,184,.18);
        border-radius:16px;padding:18px 22px;margin:10px 0;backdrop-filter:blur(6px)}
    .verdict-hero{border-radius:18px;padding:22px 28px;margin:14px 0;color:#fff}
    .vh-buy{background:linear-gradient(120deg,rgba(34,197,94,.16),rgba(34,197,94,.04));
        border:1.5px solid #22c55e88;box-shadow:0 0 40px rgba(34,197,94,.15)}
    .vh-sell{background:linear-gradient(120deg,rgba(239,68,68,.16),rgba(239,68,68,.04));
        border:1.5px solid #ef444488;box-shadow:0 0 40px rgba(239,68,68,.15)}
    .vh-hold{background:linear-gradient(120deg,rgba(234,179,8,.14),rgba(234,179,8,.04));
        border:1.5px solid #eab30877;box-shadow:0 0 40px rgba(234,179,8,.12)}
    .vh-decision{font-size:2.6rem;font-weight:900;letter-spacing:3px}
    .vh-sub{color:#cbd5e1;font-size:.95rem}
    .badge{display:inline-block;border-radius:999px;padding:2px 12px;font-size:.78rem;
        font-weight:700;margin:0 5px 6px 0}
    .b-gemini{background:rgba(59,130,246,.15);color:#93c5fd;border:1px solid #3b82f666}
    .b-nvidia{background:rgba(34,197,94,.15);color:#86efac;border:1px solid #22c55e66}
    .b-mistral{background:rgba(249,115,22,.15);color:#fdba74;border:1px solid #f9731666}
    .b-openrouter{background:rgba(168,85,247,.15);color:#d8b4fe;border:1px solid #a855f766}
    .b-groq{background:rgba(249,115,22,.15);color:#fdba74;border:1px solid #f9731666}
    .b-cerebras{background:rgba(239,68,68,.15);color:#fca5a5;border:1px solid #ef444466}
    .b-github{background:rgba(148,163,184,.15);color:#e2e8f0;border:1px solid #94a3b866}
    .b-sambanova{background:rgba(20,184,166,.15);color:#5eead4;border:1px solid #14b8a666}
    .b-mock{background:rgba(100,116,139,.15);color:#cbd5e1;border:1px solid #64748b66}
    .b-dead{background:rgba(100,116,139,.08);color:#94a3b8;border:1px dashed #64748b55}
    .prog{font-family:ui-monospace,Consolas,monospace;font-size:.82rem;line-height:1.75;
        color:#a5f3fc;white-space:pre-wrap}
    .section-h{font-size:1.15rem;font-weight:800;color:#e2e8f0;margin:1.2rem 0 .4rem}
    .ticker-pill{background:rgba(56,189,248,.12);border:1px solid rgba(56,189,248,.35);
        color:#7dd3fc;border-radius:9px;padding:2px 11px;font-weight:700}
</style>
"""

PROVIDER_BADGE = {
    "gemini": ("b-gemini", "Gemini"),
    "nvidia": ("b-nvidia", "NVIDIA Nemotron"),
    "mistral": ("b-mistral", "Mistral"),
    "openrouter": ("b-openrouter", "OpenRouter"),
    "groq": ("b-groq", "Groq GPT-OSS"),
    "cerebras": ("b-cerebras", "Cerebras GPT-OSS"),
    "sambanova": ("b-sambanova", "SambaNova"),
    "mock": ("b-mock", "DEMO"),
}


def provider_badge(p):
    css, label = PROVIDER_BADGE.get(p, ("b-mock", p))
    return f"<span class='badge {css}'>{label}</span>"


@st.cache_data(ttl=3600, show_spinner=False)
def _cached_walk_forward(ticker: str, end: str, years: int, capital: float,
                         risk_pct: float, max_allocation: float, risk_profile: str,
                         horizon: str, slippage_bps: float, impact_bps: float,
                         train: int, validation: int, test: int, embargo: int,
                         setup_names: tuple[str, ...], sector_name: str | None) -> dict:
    """Explicit-button backtest cache, keyed by every economically relevant input."""
    from indiaagents.backtest import (
        BacktestConfig, IndiaCostConfig, WalkForwardConfig, run_walk_forward,
    )
    from indiaagents.data.adapters import fetch_strategy_history
    from indiaagents.strategy import sector_index_for

    stock = fetch_strategy_history(ticker, years, end=end)
    nifty = fetch_strategy_history("^NSEI", years, end=end)
    sector_symbol = sector_index_for(ticker, sector_name)
    sector = fetch_strategy_history(sector_symbol, years, end=end) if sector_symbol else None
    bt = BacktestConfig(
        initial_capital=capital, max_risk_pct=risk_pct,
        max_single_stock_pct=max_allocation, risk_profile=risk_profile,
        horizon=horizon, setup_names=setup_names,
    )
    costs = IndiaCostConfig(slippage_bps=slippage_bps, impact_bps=impact_bps)
    wf = WalkForwardConfig(train_sessions=train, validation_sessions=validation,
                           test_sessions=test, step_sessions=test,
                           embargo_sessions=embargo, expanding=True)
    result = run_walk_forward(
        stock.data, nifty=nifty.data, sector=sector.data if sector else None,
        sector_symbol=sector_symbol, sector_name=sector_name,
        backtest_config=bt, cost_config=costs, walk_config=wf,
        data_limitations=stock.provenance.limitations,
    )
    return result.to_dict(include_curve=True)


# ============================================================ sidebar
with st.sidebar:
    st.markdown("## ⚙️ Control Panel")
    providers = available_providers()
    n_gem = len(get_api_keys("gemini"))

    st.markdown("#### 🔑 AI Model Keys")
    hints = {
        "gemini": f"Gemini ×{n_gem} key pool" if n_gem > 1 else "Gemini",
        "nvidia": "NVIDIA Nemotron 550B",
        "mistral": "Mistral Ministral",
        "groq": "Groq GPT-OSS 120B",
        "openrouter": "OpenRouter backup",
    }
    rows = ""
    for p, label in hints.items():
        if p in providers:
            rows += provider_badge(p) + " ✅\n\n"
        else:
            rows += f"<span class='badge b-dead'>{label}</span> ❌\n\n"
    rows += (f"<span class='badge b-gemini'>FRED macro</span> "
             f"{'✅' if os.environ.get('FRED_API_KEY') else '❌'}")
    st.markdown(rows, unsafe_allow_html=True)
    if n_gem > 1:
        st.caption(f"🚀 Gemini pool: **{n_gem} keys** rotate → ~{n_gem * 1500:,} calls/day free")
    if not providers:
        st.info("Keys `.env` (ya Streamlit Secrets) mein daalo. Ya **Demo Mode** on karo.")

    st.markdown("---")
    st.markdown("#### 🎛️ Run Settings")
    demo = st.toggle("🎮 Demo Mode (zero API use)", value=False,
                     help="LLM mock answers, data real — flow test karne ke liye. Koi key use nahi hoti.")
    battle = st.selectbox(
        "⚔️ Battle Mode", ["auto", "off"],
        format_func=lambda x: "Auto — saare models ladenge" if x == "auto"
        else "Off — ek model sab karega")
    rounds = st.slider("🐂🐻 Debate rounds", 1, 3, 2,
                       help="Zyada rounds = gehri debate (thoda zyada time + calls)")
    lang = st.selectbox("🌐 Report language", ["hinglish", "english", "hindi"],
                        format_func=lambda x: {"hinglish": "Hinglish 🇮🇳",
                                               "english": "English",
                                               "hindi": "हिंदी"}[x])
    st.markdown("---")
    st.markdown("#### 💼 Portfolio & Risk")
    existing_holding = st.toggle("Existing holding?", value=False)
    average_buy_price = st.number_input("Average buy price (₹)", min_value=0.0, value=0.0,
                                        disabled=not existing_holding)
    current_quantity = st.number_input("Current quantity", min_value=0, value=0, step=1,
                                       disabled=not existing_holding)
    portfolio_capital = st.number_input("Portfolio capital (₹)", min_value=1000.0,
                                        value=100000.0, step=10000.0)
    max_risk_pct = st.number_input("Maximum risk per trade (%)", min_value=0.1,
                                   max_value=2.0, value=1.0, step=0.1)
    max_allocation_pct = st.number_input("Maximum single-stock allocation (%)", min_value=1.0,
                                         max_value=30.0, value=20.0, step=1.0)
    horizon = st.selectbox("Trading horizon", ["swing", "positional", "long-term"], index=1)
    risk_profile = st.selectbox("Risk profile", ["conservative", "balanced", "aggressive"], index=1)
    st.markdown("---")
    st.caption("🆓 **Free budget**: 1 run ≈ 22 calls. App sirf button "
               "dabane par API use karta hai.")
    st.caption("⚠️ Educational research only — financial advice nahi.")

# ============================================================ header
st.markdown(CSS, unsafe_allow_html=True)
st.markdown("<h1 class='big-title'>📈 TradingAgents India</h1>", unsafe_allow_html=True)
st.markdown(
    "<p class='sub'>Stock ka naam dalo — <b>4 Analysts</b> + 🐂🐻 debate + "
    "⚔️ <b>Multi-Model Battle</b> + Risk Team + Portfolio Manager = poori "
    "research report. <b>100% free</b> tier pe (Gemini · NVIDIA · Mistral · Groq · OpenRouter).</p>",
    unsafe_allow_html=True)

c1, c2, c3 = st.columns([2.4, 1, 1.1])
with c1:
    ticker_in = st.text_input(
        "Stock ka naam / NSE ticker", placeholder="RELIANCE, TCS, HDFC Bank, INFY, Tata Motors…",
        label_visibility="collapsed")
with c2:
    analysis_date = st.date_input("Analysis date", datetime.now(IST).date(),
                                  max_value=datetime.now(IST).date())
with c3:
    st.write("")
    run_btn = st.button("🚀 Research Banao", type="primary", use_container_width=True)

st.markdown("**Quick picks:** " + " · ".join(
    f"[{e}](#)" for e in ["RELIANCE", "TCS", "HDFCBANK", "INFY", "TATAMOTORS", "SBIN", "ITC", "BEL"]))

# ============================================================ run (thread-safe)
if run_btn and ticker_in:
    settings = Settings()
    settings.mock_llm = demo or not providers
    settings.battle_mode = battle
    settings.debate_rounds = rounds
    settings.report_language = lang
    if not providers and not demo:
        st.warning("⚠️ Koi API key nahi mili — **Demo Mode** mein chala raha hoon "
                   "(zero API use). Real ke liye keys daalo.")
    portfolio = PortfolioInputs(
        existing_holding=existing_holding, average_buy_price=average_buy_price or None,
        current_quantity=int(current_quantity), portfolio_capital=portfolio_capital,
        max_risk_pct=max_risk_pct, max_single_stock_pct=max_allocation_pct,
        horizon=horizon, risk_profile=risk_profile,
    ).validated()

    status_box = st.status(f"🔍 '{ticker_in}' — AI research desk start ho rahi hai…",
                           expanded=True)
    with status_box:
        progress_slot = st.empty()
        events: list[str] = []

        def on_progress(ev):
            # NOTE: called from worker threads — only touch the plain list,
            # never st.* from here (Streamlit is not thread-safe).
            icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(ev["status"], "▶️")
            # This list is later rendered with unsafe_allow_html; all external/API
            # strings must be escaped before entering it.
            events.append(
                f"{icon} [{_e(ev['time'])}] <b>{_e(str(ev['stage']).upper())}</b> — "
                f"{_e(ev['detail'])}"
            )

        result_holder: dict = {}

        def _run():
            try:
                pipe = TradingAgentsIndiaPipeline(settings, progress_cb=on_progress)
                result_holder["result"] = pipe.run(
                    ticker_in, analysis_date.strftime("%Y-%m-%d"), portfolio)
            except Exception as e:  # noqa: BLE001
                import traceback
                result_holder["error"] = f"{e}\n{traceback.format_exc()[-400:]}"

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t0 = time.time()
        while t.is_alive():
            if events:
                progress_slot.markdown(
                    "<div class='prog'>" + "<br>".join(events[-16:]) + "</div>",
                    unsafe_allow_html=True)
            time.sleep(1.0)
        t.join()
        if events:
            progress_slot.markdown(
                "<div class='prog'>" + "<br>".join(events[-16:]) + "</div>",
                unsafe_allow_html=True)

        elapsed = time.time() - t0
        if "error" in result_holder and "result" not in result_holder:
            status_box.update(label=f"❌ Run failed ({elapsed:.0f}s)",
                              state="error", expanded=False)
            st.error(f"Kuch galat ho gaya:\n\n```\n{result_holder['error'][:600]}\n```")
            st.session_state.result = None
            st.stop()
        status_box.update(label=f"✅ Research complete — {elapsed:.0f} seconds mein!",
                          state="complete", expanded=False)
        st.session_state.result = result_holder.get("result")
        st.session_state.backtest_result = None
        st.session_state.backtest_key = None

# ============================================================ result
res = st.session_state.result
if res:
    dec = res["decision"]
    det = res.get("deterministic") or {}
    d = det.get("action") or dec.get("detailed_action") or dec["decision"]
    vh = {"ENTER": "vh-buy", "ADD": "vh-buy", "BUY": "vh-buy",
          "TRIM": "vh-sell", "EXIT": "vh-sell", "SELL": "vh-sell"}.get(d, "vh-hold")
    icon = {"ENTER": "🟢", "ADD": "🟢", "BUY": "🟢", "TRIM": "🟠",
            "EXIT": "🔴", "SELL": "🔴", "HOLD": "🟡", "WAIT": "🟡",
            "REVIEW": "⚠️"}.get(d, "⚪")
    provs_used = " ".join(provider_badge(p) for p in (res.get("stats") or {}))

    st.markdown(
        f"""<div class='verdict-hero {vh}'>
        <div style='display:flex;flex-wrap:wrap;align-items:center;gap:20px'>
          <div>
            <div class='vh-decision'>{icon} {d}</div>
            <div class='vh-sub'>{_e(det.get('setup_name', '—'))} · {_e(det.get('signal_state', '—'))} · {_e(res['name'])}
            <span class='ticker-pill'>{_e(res['ticker'])}</span> @ ₹{res['price']:,.2f}</div>
          </div>
          <div style='flex:1;min-width:200px'>
            <div style='font-size:.85rem;color:#94a3b8'><b>Evidence:</b>
              {_e((det.get('evidence') or {}).get('status', 'BACKTEST NOT AVAILABLE'))}</div>
            <div style='font-size:.78rem;color:#94a3b8;margin-top:4px'>AI confidence is not a strategy statistic.</div>
            <div style='margin-top:8px'>{provs_used}</div>
          </div>
        </div></div>""",
        unsafe_allow_html=True)

    if res.get("mock"):
        st.info("🎮 **DEMO run** — data real hai, AI text mock hai. "
                "Real battle ke liye keys + Demo Mode off karo.")
    dq = res.get("data_quality") or {}
    if dq.get("score", 100) < 80:
        st.warning(f"🔌 Evidence quality: **{dq.get('score', '—')}/100 "
                   f"({dq.get('level', '—')})** — "
                   + "; ".join((dq.get("issues") or [])[:4]))

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Entry", (dec.get("entry_zone") or "—")[:22])
    m2.metric("T1 / T2", f"{det.get('target_1', '—')} / {det.get('target_2', '—')}")
    m3.metric("Stop", dec.get("stop_loss") or "—")
    m4.metric("Quantity", int(det.get("quantity", 0) or 0),
              f"max loss ₹{float(det.get('max_loss_rupees', 0)):,.0f}")
    m5.metric("R:R", det.get("reward_risk") or "—",
              f"{det.get('allocation_pct', 0)}% allocation")

    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
        ["🎯 Current setup", "📊 Historical evidence", "🧠 Why this action",
         "⚔️ AI commentary", "📈 Chart", "📄 Full Report", "📎 Data"])

    with tab1:
        st.markdown(f"### {icon} {d} — {_e(det.get('setup_name', '—'))}")
        st.markdown(f"**Signal state:** `{det.get('signal_state', '—')}`")
        st.markdown(f"**Trigger:** {det.get('trigger', '—')}")
        st.markdown(f"**Invalidation:** {det.get('invalidation', '—')}")
        st.markdown(f"**Stop reason:** {det.get('stop_reason', '—')}")
        st.markdown(f"**Trailing:** {det.get('trailing_rule', '—')}")
        st.markdown("**Confirmations:**")
        for text in det.get("confirmations") or []:
            st.markdown(f"- ✅ {text}")
        st.markdown("**Missing confirmations:**")
        for text in det.get("missing_confirmations") or []:
            st.markdown(f"- ⏳ {text}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**Support zones**")
            for z in det.get("support_zones") or []:
                st.markdown(f"- ₹{z['low']:,.2f}–₹{z['high']:,.2f} · {z.get('touches', 1)} touch · {z.get('source')}")
        with c2:
            st.markdown("**Resistance zones**")
            for z in det.get("resistance_zones") or []:
                st.markdown(f"- ₹{z['low']:,.2f}–₹{z['high']:,.2f} · {z.get('touches', 1)} touch · {z.get('source')}")

    with tab2:
        st.markdown("### Out-of-sample walk-forward evidence")
        st.info("Backtest expensive hai, isliye widget change par auto-run nahi hota. Settings choose karke explicit button dabayein.")
        b1, b2, b3, b4 = st.columns(4)
        years = b1.selectbox("Period", [5, 8, 10, 12, 15], index=2, key="bt_years")
        train = b2.number_input("Training sessions", 252, 1260, 504, 126, key="bt_train")
        validation = b3.number_input("Validation sessions", 63, 504, 126, 21, key="bt_val")
        test = b4.number_input("Test sessions", 63, 504, 126, 21, key="bt_test")
        c1, c2, c3 = st.columns(3)
        slippage = c1.number_input("Slippage (bps/side)", 0.0, 50.0, 5.0, 1.0, key="bt_slip")
        impact = c2.number_input("Impact estimate (bps/side)", 0.0, 100.0, 0.0, 1.0, key="bt_impact")
        embargo = c3.number_input("Embargo sessions", 0, 30, 5, 1, key="bt_embargo")
        setup_options = ["Weekly-trend breakout", "Breakout retest", "Trend pullback",
                         "Range breakout / volatility contraction", "Bottoming reversal probe"]
        selected_setups = st.multiselect("Setups (empty = all)", setup_options, key="bt_setups")
        current_bt_key = (
            res["ticker"], res["trade_date"], int(years), float(slippage), float(impact),
            int(train), int(validation), int(test), int(embargo), tuple(selected_setups),
            float((res.get("portfolio_inputs") or {}).get("portfolio_capital", 100000)),
            float((res.get("portfolio_inputs") or {}).get("max_risk_pct", 1.0)),
            float((res.get("portfolio_inputs") or {}).get("max_single_stock_pct", 20.0)),
            str((res.get("portfolio_inputs") or {}).get("risk_profile", "balanced")),
            str((res.get("portfolio_inputs") or {}).get("horizon", "positional")),
        )
        run_backtest = st.button("▶ Run explicit walk-forward backtest", type="primary", key="run_bt")
        if run_backtest:
            try:
                with st.spinner("Downloading bounded history and evaluating unseen windows..."):
                    bt = _cached_walk_forward(
                        res["ticker"], res["trade_date"], years,
                        float((res.get("portfolio_inputs") or {}).get("portfolio_capital", 100000)),
                        float((res.get("portfolio_inputs") or {}).get("max_risk_pct", 1.0)),
                        float((res.get("portfolio_inputs") or {}).get("max_single_stock_pct", 20.0)),
                        str((res.get("portfolio_inputs") or {}).get("risk_profile", "balanced")),
                        str((res.get("portfolio_inputs") or {}).get("horizon", "positional")),
                        slippage, impact, int(train), int(validation), int(test), int(embargo),
                        tuple(selected_setups), res.get("snapshot", {}).get("sector"),
                    )
                st.session_state.backtest_result = bt
                st.session_state.backtest_key = current_bt_key
                res["backtest"] = bt
                metrics, gate = bt["metrics"], bt["acceptance"]
                res["deterministic"]["evidence"] = {
                    "status": gate["status"], "validated_edge": gate["validated_edge"],
                    "trades": metrics["trades"],
                    "walk_forward_windows": len(bt.get("windows") or []),
                    "profit_factor": metrics.get("profit_factor"),
                    "expectancy_r": metrics.get("expectancy_r"),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                    "reasons": gate.get("failed_reasons") or [], "metrics": metrics,
                }
                from indiaagents.report import build_report
                res["paths"] = build_report(res)
            except Exception as exc:
                st.error(f"BACKTEST NOT AVAILABLE: {exc}")
        stored_bt = st.session_state.get("backtest_result")
        stored_key = st.session_state.get("backtest_key")
        if stored_bt is not None and stored_key != current_bt_key:
            st.warning(
                "Backtest settings change ho gaye hain. Purana result new settings ke "
                "naam par show nahi kiya ja raha; explicit button dobara dabayein."
            )
        bt = stored_bt if stored_key == current_bt_key else None
        if bt:
            metrics, gate = bt["metrics"], bt["acceptance"]
            st.success(gate["status"]) if gate["validated_edge"] else st.warning(gate["status"])
            x1, x2, x3, x4 = st.columns(4)
            x1.metric("OOS trades", metrics["trades"])
            x2.metric("Profit factor", metrics["profit_factor"] or "—")
            x3.metric("Expectancy", f"{metrics['expectancy_r']}R")
            x4.metric("Max drawdown", f"{metrics['max_drawdown_pct']}%")
            curve = pd.DataFrame(bt["aggregate"].get("equity_curve") or [])
            if not curve.empty:
                curve["date"] = pd.to_datetime(curve["date"])
                st.line_chart(curve.set_index("date")["equity"])
                peak = curve["equity"].cummax()
                drawdown = pd.DataFrame(
                    {"date": curve["date"].to_numpy(),
                     "drawdown_pct": ((curve["equity"] / peak - 1) * 100).to_numpy()}
                ).set_index("date")
                st.area_chart(drawdown)
            st.dataframe(pd.DataFrame(bt["aggregate"].get("trades") or []), use_container_width=True)
            st.markdown("**Setup-wise performance**")
            st.dataframe(pd.DataFrame(metrics.get("setup_performance") or {}).T)
            st.markdown("**Regime-wise performance**")
            st.dataframe(pd.DataFrame(metrics.get("regime_performance") or {}).T)
            st.caption("Acceptance failures: " + ", ".join(gate.get("failed_reasons") or ["none"]))
        else:
            st.warning("BACKTEST NOT AVAILABLE — no validated edge is claimed.")

    with tab3:
        st.markdown("### Deterministic reasons")
        for reason in det.get("deterministic_reasons") or []:
            st.markdown(f"- {reason}")
        st.markdown("### Data-quality / integrity limitations")
        for item in det.get("limitations") or []:
            st.markdown(f"- ⚠️ {item}")
        st.markdown("### Relative strength")
        st.json(det.get("relative_strength") or {})
        st.info("AI explanation below is separate. It cannot alter the plan or backtest statistics.")

    with tab4:
        st.markdown("### 🔴 Har AI ne baaki sab ki research red-team ki:")
        if res.get("battle_critiques"):
            st.markdown(res["battle_critiques"])
            st.markdown("---\n### 🔬 Synthesizer ka improved final verdict:")
            st.markdown(res["final_research"])
        else:
            st.info("Is run mein battle critiques available nahi (mode off tha ya fail hua).")

    with tab5:
        if res.get("chart_png"):
            st.image(res["chart_png"], use_container_width=True)
            st.caption("Price + Bollinger + SMA | Volume | RSI — last 180 sessions")
        else:
            st.info("Chart generate nahi hua.")

    with tab6:
        md_path = Path(res["paths"]["md"])
        html_path = Path(res["paths"]["html"])
        st.markdown(md_path.read_text(encoding="utf-8"))
        try:
            st.download_button("⬇️ Download premium report.html",
                               html_path.read_bytes(), file_name=html_path.name,
                               mime="text/html", type="primary")
        except FileNotFoundError:
            st.caption("HTML file missing")
        st.download_button("⬇️ Download report.md",
                           md_path.read_text(encoding="utf-8"),
                           file_name=md_path.name, mime="text/markdown")

    with tab7:
        health_rows = (res.get("data_sources") or {}).get("health") or []
        with st.expander("🔌 Source health / provenance", expanded=True):
            if health_rows:
                health_frame = pd.DataFrame(health_rows)
                visible = [column for column in
                           ("source", "category", "status", "rows", "as_of", "detail", "cached")
                           if column in health_frame.columns]
                st.dataframe(health_frame[visible], use_container_width=True, hide_index=True)
                st.caption("empty ≠ market silence. Network/config/rate/parse/stale/PIT-suppressed states are separate.")
            else:
                st.caption("No structured source diagnostics in this legacy result.")
        for title, key in [("📈 Technical data", "indicator_block"),
                           ("💰 Fundamentals", "fundamentals_block"),
                           ("📰 Company news", "news_block"),
                           ("🇮🇳 India macro news", "macro_news_block"),
                           ("🌍 Global macro (FRED)", "fred_block"),
                           ("💬 Social chatter", "social_block"),
                           ("🏦 Market context", "market_context_block")]:
            with st.expander(title):
                st.code(res.get(key) or "—", language="text")

# ============================================================ history
st.markdown("---")
st.markdown("### 📁 Report History")
if REPORTS_DIR.exists():
    reports = sorted(REPORTS_DIR.glob("*/report.md"), reverse=True)[:12]
    if reports:
        for rp in reports:
            name = rp.parent.name
            c1, c2, c3 = st.columns([3.2, 1, 1])
            c1.markdown(f"📄 **{name}**")
            html_file = rp.parent / "report.html"
            if html_file.exists():
                c2.download_button("⬇️ HTML", html_file.read_bytes(),
                                   key=f"dlh_{name}", file_name=f"{name}.html",
                                   mime="text/html")
            chart_file = rp.parent / "chart.png"
            if chart_file.exists():
                c3.download_button("⬇️ Chart", chart_file.read_bytes(),
                                   key=f"dlc_{name}", file_name=f"{name}_chart.png")
    else:
        st.caption("Abhi koi report nahi — pehli research run karo! 🚀")
else:
    st.caption("Abhi koi report nahi — pehli research run karo! 🚀")

st.markdown("---")
st.caption("⚠️ **Disclaimer:** AI research simulation — financial advice NAHI. SEBI-registered "
           "advisor ki salah ka replacement nahi. Architecture inspired by "
           "TauricResearch/TradingAgents (Apache-2.0) · Free-tier pe India ke liye rebuild.")

