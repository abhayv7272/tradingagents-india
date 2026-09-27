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

import streamlit as st

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from indiaagents.config import REPORTS_DIR, Settings, available_providers, get_api_keys  # noqa: E402
from indiaagents.pipeline import TradingAgentsIndiaPipeline  # noqa: E402

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
    "mock": ("b-mock", "DEMO"),
}


def provider_badge(p):
    css, label = PROVIDER_BADGE.get(p, ("b-mock", p))
    return f"<span class='badge {css}'>{label}</span>"


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
    st.caption("🆓 **Free budget**: 1 run ≈ 22 calls. App sirf button "
               "dabane par API use karta hai.")
    st.caption("⚠️ Educational research only — financial advice nahi.")

# ============================================================ header
st.markdown(CSS, unsafe_allow_html=True)
st.markdown("<h1 class='big-title'>📈 TradingAgents India</h1>", unsafe_allow_html=True)
st.markdown(
    "<p class='sub'>Stock ka naam dalo — <b>4 Analysts</b> + 🐂🐻 debate + "
    "⚔️ <b>Multi-Model Battle</b> + Risk Team + Portfolio Manager = poori "
    "research report. <b>100% free</b> tier pe (Gemini · NVIDIA · Mistral · OpenRouter).</p>",
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

    status_box = st.status(f"🔍 '{ticker_in}' — AI research desk start ho rahi hai…",
                           expanded=True)
    with status_box:
        progress_slot = st.empty()
        events: list[str] = []

        def on_progress(ev):
            # NOTE: called from worker threads — only touch the plain list,
            # never st.* from here (Streamlit is not thread-safe).
            icon = {"ok": "✅", "warn": "⚠️", "error": "❌"}.get(ev["status"], "▶️")
            events.append(f"{icon} [{ev['time']}] <b>{ev['stage'].upper()}</b> — {ev['detail']}")

        result_holder: dict = {}

        def _run():
            try:
                pipe = TradingAgentsIndiaPipeline(settings, progress_cb=on_progress)
                result_holder["result"] = pipe.run(
                    ticker_in, analysis_date.strftime("%Y-%m-%d"))
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

# ============================================================ result
res = st.session_state.result
if res:
    dec = res["decision"]
    d = dec["decision"]
    vh = {"BUY": "vh-buy", "SELL": "vh-sell", "HOLD": "vh-hold"}.get(d, "vh-hold")
    icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(d, "⚪")
    conf = int(dec.get("confidence", 0) or 0)
    provs_used = " ".join(provider_badge(p) for p in (res.get("stats") or {}))

    st.markdown(
        f"""<div class='verdict-hero {vh}'>
        <div style='display:flex;flex-wrap:wrap;align-items:center;gap:20px'>
          <div>
            <div class='vh-decision'>{icon} {d}</div>
            <div class='vh-sub'>{_e(dec.get('rating'))} · {_e(res['name'])}
            <span class='ticker-pill'>{_e(res['ticker'])}</span> @ ₹{res['price']:,.2f}</div>
          </div>
          <div style='flex:1;min-width:200px'>
            <div style='display:flex;justify-content:space-between;font-size:.8rem;color:#94a3b8'>
              <b>Confidence</b><span>{conf}%</span></div>
            <div style='height:11px;background:rgba(0,0,0,.35);border-radius:8px;margin-top:4px'>
              <div style='height:100%;width:{min(conf,100)}%;border-radius:8px;
              background:linear-gradient(90deg,#38bdf8,#22c55e)'></div></div>
            <div style='margin-top:8px'>{provs_used}</div>
          </div>
        </div></div>""",
        unsafe_allow_html=True)

    if res.get("mock"):
        st.info("🎮 **DEMO run** — data real hai, AI text mock hai. "
                "Real battle ke liye keys + Demo Mode off karo.")

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Entry", (dec.get("entry_zone") or "—")[:22])
    m2.metric("Target", (dec.get("target") or "—")[:22])
    m3.metric("Stop loss", (dec.get("stop_loss") or "—")[:22])
    m4.metric("Size", f"{dec.get('position_size_pct', 0)}% capital")
    m5.metric("Timeframe", (dec.get("timeframe") or "—")[:20])

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["🧠 Summary", "⚔️ Model Battle", "📈 Chart", "📄 Full Report", "📊 Data"])

    with tab1:
        st.markdown(f"**Rationale (Hinglish):**")
        st.markdown(f"> {dec.get('rationale', '—')}")
        st.markdown("**Key risks:**")
        for k in dec.get("key_risks", []):
            st.markdown(f"- ⚠️ {k}")
        st.markdown(f"**AI models ke beech disagreement:** {dec.get('battle_notes', '—')}")
        st.markdown("---")
        st.markdown("**Model usage is run mein:**")
        for p, s in (res.get("stats") or {}).items():
            st.markdown(f"- {provider_badge(p)} `{', '.join(s.get('models', []))}` — "
                        f"{s.get('ok', 0)} calls ✅, {s.get('fail', 0)} fail")

    with tab2:
        st.markdown("### 🔴 Har AI ne baaki sab ki research red-team ki:")
        if res.get("battle_critiques"):
            st.markdown(res["battle_critiques"])
            st.markdown("---\n### 🔬 Synthesizer ka improved final verdict:")
            st.markdown(res["final_research"])
        else:
            st.info("Is run mein battle critiques available nahi (mode off tha ya fail hua).")

    with tab3:
        if res.get("chart_png"):
            st.image(res["chart_png"], use_container_width=True)
            st.caption("Price + Bollinger + SMA | Volume | RSI — last 180 sessions")
        else:
            st.info("Chart generate nahi hua.")

    with tab4:
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

    with tab5:
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

