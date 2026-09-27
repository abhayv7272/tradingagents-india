"""
TradingAgents India — orchestration pipeline.

Flow (mirrors TauricResearch/TradingAgents, upgraded with Battle Mode):

  1. Resolve ticker (NSE/BSE) + fetch real data (yfinance, Google News India, Reddit)
  2. 4 Analysts run in PARALLEL across different free models
  3. Bull vs Bear debate (different model families on each side!)
  4. Research Manager judges
  5. ⚔️ BATTLE: 3 models red-team the verdict in parallel, Synthesizer improves it
  6. Trader writes the execution plan
  7. Risk team: Aggressive / Conservative / Neutral (parallel, mixed models)
  8. Portfolio Manager -> final JSON decision (+ past-decision memory)
  9. Report saved (markdown + HTML) + decision logged
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from typing import Callable

from . import memory as mem
from .config import Settings
from .data import (
    get_company_news, get_fundamentals_data, get_india_macro_news,
    get_market_context, get_market_data, get_social_chatter, resolve_ticker,
)
from .llm import LLMEngine, ProviderError
from .agents.prompts import (
    AGGRESSIVE_ANALYST, BEAR_RESEARCHER, BATTLE_CRITIC, BATTLE_SYNTHESIZER,
    CONSERVATIVE_ANALYST, FUNDAMENTALS_ANALYST, MARKET_ANALYST, NEWS_ANALYST,
    NEUTRAL_ANALYST, PORTFOLIO_MANAGER, BULL_RESEARCHER, RESEARCH_MANAGER,
    SOCIAL_ANALYST, TRADER,
)
from .config import language_instruction
from .report import build_report


logger = logging.getLogger(__name__)


class Progress:
    """Thread-safe progress events for UI/CLI."""

    def __init__(self, cb: Callable | None = None):
        self.cb = cb
        self.lock = threading.Lock()
        self.events: list[dict] = []
        self.stage = ""

    def emit(self, stage: str, detail: str = "", status: str = "info"):
        ev = {"time": datetime.now().strftime("%H:%M:%S"), "stage": stage,
              "detail": detail, "status": status}
        with self.lock:
            self.events.append(ev)
            self.stage = stage
        if self.cb:
            try:
                self.cb(ev)
            except Exception:
                pass


class TradingAgentsIndiaPipeline:
    def __init__(self, settings: Settings | None = None, progress_cb: Callable | None = None):
        self.settings = settings or Settings.from_env()
        self.progress = Progress(progress_cb)
        self.engine = LLMEngine(self.settings)
        self.lang = language_instruction(self.settings.report_language)
        self.decision_log = mem.DecisionLog()

    # ------------------------------------------------------------------
    def run(self, user_input: str, trade_date: str | None = None) -> dict:
        s = self.settings
        P = self.progress.emit

        # 1) resolve ticker -------------------------------------------------
        P("ticker", f"'{user_input}' resolve kar rahe hain (NSE/BSE)...")
        inst = resolve_ticker(user_input)
        ticker, name = inst["ticker"], inst["name"]
        P("ticker", f"✅ {name} ({ticker}) — {inst['exchange']}", "ok")
        trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
        if trade_date > datetime.now().strftime("%Y-%m-%d"):
            trade_date = datetime.now().strftime("%Y-%m-%d")
            P("ticker", "⚠️ Future date diya tha — aaj ki date par clamp kar diya", "warn")

        # 2) data -----------------------------------------------------------
        P("data", "Price, indicators, fundamentals, news, social, macro fetch ho raha hai...")
        from .data.macro import get_fred_global_macro
        mkt = get_market_data(ticker, trade_date, s.lookback_months)
        fund = get_fundamentals_data(ticker, trade_date)
        news = get_company_news(name, ticker, s.news_article_limit, trade_date)
        macro_news = get_india_macro_news(s.macro_news_limit, trade_date)
        social = get_social_chatter(name, ticker, trade_date)
        mctx = get_market_context()
        fred = get_fred_global_macro()
        P("data", f"✅ Data ready: price ₹{mkt['price']:,.2f} ({mkt['snapshot']['date']}), "
                  f"{len(news['items'])} news, {social['count']} social posts", "ok")

        price = mkt["price"]
        company_block = (
            f"COMPANY: {name} | Ticker: {ticker} ({inst['exchange']}) | "
            f"Sector: {mkt['snapshot'].get('sector') or '?'} | "
            f"Analysis date: {trade_date} | Current price: ₹{price:,.2f}"
        )

        # memory ------------------------------------------------------------
        past = self.decision_log.past_decisions(ticker)
        past_ctx = mem.memory_context_text(past, mkt["df"][["Close"]])

        # 3) analysts (parallel, different providers => real diversity) ------
        analysts = {}
        if "market" in s.selected_analysts:
            analysts["market"] = (MARKET_ANALYST, company_block + "\n\n" +
                                  mkt["indicator_block"] + "\n\n" + mctx["market_context_block"])
        if "fundamentals" in s.selected_analysts:
            analysts["fundamentals"] = (FUNDAMENTALS_ANALYST, company_block + "\n\n" +
                                        fund["fundamentals_block"])
        if "news" in s.selected_analysts:
            analysts["news"] = (NEWS_ANALYST, company_block + "\n\n" + news["news_block"] +
                                "\n\n" + macro_news["macro_news_block"])
        if "social" in s.selected_analysts:
            analysts["social"] = (SOCIAL_ANALYST, company_block + "\n\n" + social["social_block"])

        role_map = {"market": "market_analyst", "fundamentals": "fundamentals_analyst",
                    "news": "news_analyst", "social": "social_analyst"}
        P("analysts", f"{len(analysts)} analysts parallel mein kaam kar rahe hain "
                      f"({', '.join(self.engine.provider_names())} models)...")
        jobs = [{"role": role_map[k], "system": v[0] + self.lang, "user": v[1]}
                for k, v in analysts.items()]
        results = self.engine.call_parallel(jobs)
        reports = {}
        for (k, _), (text, prov, err) in zip(analysts.items(), results):
            if err:
                P("analysts", f"⚠️ {k} analyst fail: {err[:80]}", "warn")
                reports[k] = f"<{k} analyst unavailable: {err[:120]}>"
            else:
                P("analysts", f"✅ {k} analyst done ({prov})", "ok")
                reports[k] = text

        analyst_evidence = "\n\n".join(
            f"=== {k.upper()} REPORT ===\n{v}" for k, v in reports.items())

        # 4) bull-bear debate ------------------------------------------------
        P("debate", f"🐂 Bull vs 🐻 Bear debate shuru ({s.debate_rounds} rounds)...")
        debate_history = ""
        bull_arg, bear_arg = "", ""
        for rnd in range(s.debate_rounds):
            for side, role, prompt in (
                ("Bull", "bull_researcher", BULL_RESEARCHER),
                ("Bear", "bear_researcher", BEAR_RESEARCHER),
            ):
                opponent = bear_arg if side == "Bull" else bull_arg
                user = (f"{company_block}\n\n{analyst_evidence}\n\n"
                        f"DEBATE SO FAR:\n{debate_history or '(opening round)'}\n\n"
                        f"{'Last BEAR argument to rebut:' if side == 'Bull' else 'Last BULL argument to rebut:'}\n"
                        f"{opponent or '(opening statement — no opponent argument yet)'}\n\n"
                        f"This is round {rnd + 1} of {s.debate_rounds}. "
                        f"{'Deliver your OPENING statement.' if not opponent else 'Rebut and strengthen.'}")
                try:
                    text, prov = self.engine.call(role, prompt + self.lang, user)
                    arg = f"{side} Analyst [{prov}]: {text}"
                    debate_history += "\n\n" + arg
                    if side == "Bull":
                        bull_arg = text
                    else:
                        bear_arg = text
                    P("debate", f"{side} ({prov}) round {rnd + 1} ✅", "ok")
                except ProviderError as e:
                    P("debate", f"⚠️ {side} round {rnd + 1} fail: {str(e)[:80]}", "warn")

        # 5) research manager -------------------------------------------------
        P("manager", "Research Manager verdict likh raha hai...")
        draft_verdict = ""
        try:
            draft_verdict, prov = self.engine.call(
                "research_manager", RESEARCH_MANAGER + self.lang,
                f"{company_block}\n\n{analyst_evidence}\n\n=== DEBATE TRANSCRIPT ===\n{debate_history}")
            P("manager", f"✅ Research Manager ({prov}) ne draft verdict diya", "ok")
        except ProviderError as e:
            P("manager", f"❌ Research Manager fail: {str(e)[:80]}", "error")

        # 6) BATTLE MODE — cross-model red team --------------------------------
        battle_section = ""
        final_research = draft_verdict
        critics_input = (f"{company_block}\n\n=== ANALYST EVIDENCE (condensed) ===\n"
                         + _condense(analyst_evidence, 3500)
                         + f"\n\n=== DEBATE (condensed) ===\n{_condense(debate_history, 2500)}"
                         + f"\n\n=== RESEARCH MANAGER DRAFT VERDICT ===\n{draft_verdict}")
        providers = self.engine.provider_names()
        if s.battle_mode != "off" and len(providers) >= 1 and draft_verdict:
            P("battle", f"⚔️ MODEL BATTLE: {len(providers)} models ek dusre ki research "
                        f"critique kar rahe hain...")
            prov_cycle = [p for p in providers] or ["gemini"]
            jobs = [{"role": "battle_critic", "system": BATTLE_CRITIC + self.lang,
                     "user": critics_input + f"\n\n(You are the critic representing: {p})",
                     "provider": p} for p in prov_cycle]
            crit_results = self.engine.call_parallel(jobs)
            critiques = []
            for p, (text, used, err) in zip(prov_cycle, crit_results):
                if err:
                    P("battle", f"⚠️ critic {p}: {err[:60]}", "warn")
                    continue
                tag = used or p
                critiques.append((tag, text))
                P("battle", f"✅ critic {tag} done", "ok")
            if critiques:
                crit_block = "\n\n".join(
                    f"=== CRITIQUE from model family: {p} ===\n{t}" for p, t in critiques)
                try:
                    final_research, prov = self.engine.call(
                        "battle_synthesizer", BATTLE_SYNTHESIZER + self.lang,
                        critics_input + f"\n\n=== RED-TEAM CRITIQUES ===\n{crit_block}")
                    battle_section = crit_block
                    P("battle", f"✅ Synthesizer ({prov}) ne improved final verdict banaya", "ok")
                except ProviderError as e:
                    P("battle", f"⚠️ synthesizer fail ({e}); draft verdict use hoga", "warn")
                    battle_section = crit_block
        elif s.battle_mode == "off":
            P("battle", "Battle mode OFF — single-provider mode", "info")

        # 7) trader ------------------------------------------------------------
        P("trader", "Trader execution plan bana raha hai...")
        trader_plan = ""
        try:
            trader_plan, prov = self.engine.call(
                "trader", TRADER + self.lang,
                f"{company_block}\n\n=== FINAL RESEARCH VERDICT ===\n{final_research}\n\n"
                f"=== KEY PRICE DATA ===\n{mkt['indicator_block'][:1500]}\n\n"
                f"{past_ctx}")
            P("trader", f"✅ Trader ({prov}) plan ready", "ok")
        except ProviderError as e:
            P("trader", f"❌ Trader fail: {str(e)[:80]}", "error")

        # 8) risk team (3-way, parallel) ----------------------------------------
        P("risk", "Risk team (Aggressive / Conservative / Neutral) debate kar rahi hai...")
        risk_jobs = [
            {"role": "aggressive_analyst", "system": AGGRESSIVE_ANALYST + self.lang,
             "user": f"{company_block}\n\nTRADER PLAN:\n{trader_plan or '<unavailable>'}"},
            {"role": "conservative_analyst", "system": CONSERVATIVE_ANALYST + self.lang,
             "user": f"{company_block}\n\n{mkt['indicator_block'][:2000]}\n\n"
                     f"TRADER PLAN:\n{trader_plan or '<unavailable>'}"},
            {"role": "neutral_analyst", "system": NEUTRAL_ANALYST + self.lang,
             "user": f"{company_block}\n\nTRADER PLAN:\n{trader_plan or '<unavailable>'}"},
        ]
        risk_results = self.engine.call_parallel(risk_jobs)
        risk_views = []
        for label, (text, prov, err) in zip(
                ("Aggressive", "Conservative", "Neutral"), risk_results):
            if err:
                P("risk", f"⚠️ {label} risk analyst fail", "warn")
                continue
            risk_views.append(f"=== {label} Risk Analyst [{prov}] ===\n{text}")
            P("risk", f"✅ {label} ({prov}) done", "ok")
        risk_block = "\n\n".join(risk_views)

        # 9) portfolio manager — FINAL DECISION --------------------------------
        P("final", "Portfolio Manager final decision le raha hai...")
        decision = None
        pm_user = (f"{company_block}\n\n=== FINAL RESEARCH VERDICT (post-battle) ===\n"
                   f"{final_research}\n\n=== TRADER PLAN ===\n{trader_plan}\n\n"
                   f"=== RISK TEAM VIEWS ===\n{risk_block}\n\n{past_ctx}\n\n"
                   f"=== PRICE SNAPSHOT ===\nCurrent: ₹{price:,.2f} | "
                   f"RSI: {mkt['snapshot']['rsi']} | 1M return: {mkt['snapshot']['ret_1m']}% | "
                   f"52w-high se {mkt['snapshot']['from_52w_high']}% neeche")
        for attempt in range(2):
            try:
                raw, prov = self.engine.call("portfolio_manager",
                                             PORTFOLIO_MANAGER + self.lang, pm_user,
                                             temperature=0.15)
                decision = _parse_decision(raw)
                P("final", f"✅ Final decision ({prov}): {decision['decision']} — "
                           f"{decision['rating']} (confidence {decision['confidence']}%)", "ok")
                break
            except ProviderError as e:
                P("final", f"⚠️ PM attempt {attempt + 1} fail: {str(e)[:80]}", "warn")
            except Exception as e:  # parse issues etc — retry once, never kill the run
                P("final", f"⚠️ PM output parse issue, retry... ({type(e).__name__}: {e})",
                  "warn")
                pm_user += "\n\n(REMINDER: ONLY output the JSON object, nothing else.)"

        if decision is None:
            decision = {"decision": "HOLD", "confidence": 0, "rating": "Hold",
                        "rationale": "Portfolio Manager call failed — data par bharosa "
                                     "karte hue ye neutral HOLD hai. Dobara run karo.",
                        "key_risks": ["LLM call failure"], "entry_zone": "—",
                        "target": "—", "stop_loss": "—", "position_size_pct": 0,
                        "timeframe": "—", "battle_notes": "—"}
            P("final", "❌ PM fail — safe HOLD fallback used", "error")

        # 10) report ------------------------------------------------------------
        P("report", "Report generate ho rahi hai...")
        result = {
            "ticker": ticker, "name": name, "exchange": inst["exchange"],
            "trade_date": trade_date, "price": price,
            "snapshot": mkt["snapshot"], "analyst_reports": reports,
            "debate": debate_history, "draft_verdict": draft_verdict,
            "battle_critiques": battle_section, "final_research": final_research,
            "trader_plan": trader_plan, "risk_views": risk_block,
            "decision": decision, "memory": past_ctx,
            "news_block": news["news_block"], "macro_news_block": macro_news["macro_news_block"],
            "social_block": social["social_block"],
            "indicator_block": mkt["indicator_block"],
            "fundamentals_block": fund["fundamentals_block"],
            "market_context_block": mctx["market_context_block"],
            "fred_block": fred["fred_block"],
            "models": self.engine.provider_models(), "stats": self.engine.stats.by_provider(),
            "settings": self.settings.as_dict(), "mock": self.settings.mock_llm,
            "progress_events": self.progress.events,
        }
        # price chart for report + dashboard
        try:
            from .charts import build_price_chart
            chart = build_price_chart(mkt["df"], name, ticker, decision.get("decision", ""))
            result["chart_b64"] = chart["b64"]
            result["chart_png"] = chart["png"]
        except Exception as e:
            logger.warning("chart generation failed: %s", e)
            result["chart_b64"] = None
            result["chart_png"] = None

        paths = build_report(result)
        self.decision_log.append(ticker, decision, price)
        P("report", f"✅ Report save ho gayi: {paths['md']}", "ok")
        result["paths"] = paths
        return result


def _condense(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...(truncated for length)..."


def _parse_decision(raw: str) -> dict:
    """Robust JSON extraction from LLM output."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if not m:
        m = re.search(r"(\{.*\})", raw, re.DOTALL)
    if not m:
        raise ValueError("No JSON found in PM output")
    txt = m.group(1)
    txt = re.sub(r",\s*([}\]])", r"\1", txt)  # trailing commas
    try:
        d = json.loads(txt)
    except json.JSONDecodeError:
        # last resort: strip newlines inside strings
        txt2 = re.sub(r"\n", " ", txt)
        d = json.loads(txt2)
    valid = {"BUY", "SELL", "HOLD"}
    if str(d.get("decision", "")).upper() not in valid:
        d["decision"] = "HOLD"
    d["decision"] = d["decision"].upper()
    for k in ("rationale", "entry_zone", "target", "stop_loss", "timeframe", "battle_notes"):
        d.setdefault(k, "—")
        d[k] = str(d[k])
    # key_risks: LLM kabhi string deta hai — list mein coerce karo (char-iteration bug se bacho)
    kr = d.get("key_risks")
    if kr is None:
        kr = []
    elif isinstance(kr, str):
        kr = [x.strip() for x in kr.split(",") if x.strip()][:6]
    elif isinstance(kr, list):
        kr = [str(x) for x in kr][:6]
    else:
        kr = []
    d["key_risks"] = kr
    # position_size_pct: safe int coercion (strings like "3", "3%", None)
    try:
        d["position_size_pct"] = max(0, min(100, int(float(str(d.get("position_size_pct", 0) or 0)
                                                        .replace("%", "").strip()))))
    except (TypeError, ValueError):
        d["position_size_pct"] = 0
    # confidence: safe clamp
    try:
        d["confidence"] = max(0, min(100, int(d.get("confidence", 50))))
    except (TypeError, ValueError):
        d["confidence"] = 50
    return d
