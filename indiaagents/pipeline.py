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
import pandas as pd
import yfinance as yf
import re
import threading
from datetime import datetime, timedelta, timezone
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
from .validation import (
    apply_quality_guard, apply_trade_guard, assess_data_quality, quality_block,
)
from .strategy import (
    DetailedAction, DeterministicStrategyEngine, PortfolioInputs, sector_index_for,
)


logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# TradeHive schemas.filter_reversal_signals se adapted — LLM kabhi-kabhi list mein
# "NOT FOUND" / "None" / "N/A" type placeholder entries likh deta hai; drop karo.
# DO-tier design (deep-diagnosis fix): SUBSTRING sirf un phrases par jo kabhi real
# risk-text nahi ban sakte; "not met"/"not detected" jaisi phrases legit risk
# ("Q2 guidance not met") ka hissa ho sakti hain — wo sirf FULL-match mein drop hongi.
_NEG_ENTRY_SUB_RE = re.compile(
    r"not found|not present|not applicable|does not apply|"
    r"no specific risk|no major risk|not available", re.IGNORECASE)
_NEG_ENTRY_FULL_RE = re.compile(
    r"^(n/?a|none|nil|no risks?|no key risks?|nothing|not applicable|not met|"
    r"not detected|no signal|[-\u2014\u2013]+|[?.!]+)$", re.IGNORECASE)


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
        self.settings = (settings or Settings.from_env()).validate()
        self.progress = Progress(progress_cb)
        self.engine = LLMEngine(self.settings)
        self.lang = language_instruction(self.settings.report_language)
        self.decision_log = mem.DecisionLog()

    # ------------------------------------------------------------------
    def run(self, user_input: str, trade_date: str | None = None,
            portfolio_inputs: PortfolioInputs | dict | None = None) -> dict:
        s = self.settings
        P = self.progress.emit
        if isinstance(portfolio_inputs, dict):
            allowed = PortfolioInputs.__dataclass_fields__
            portfolio = PortfolioInputs(**{k: v for k, v in portfolio_inputs.items() if k in allowed}).validated()
        else:
            portfolio = (portfolio_inputs or PortfolioInputs()).validated()

        # 1) resolve ticker -------------------------------------------------
        P("ticker", f"'{user_input}' resolve kar rahe hain (NSE/BSE)...")
        inst = resolve_ticker(user_input)
        ticker, name = inst["ticker"], inst["name"]
        P("ticker", f"✅ {name} ({ticker}) — {inst['exchange']}", "ok")
        today = datetime.now(IST).date()
        if trade_date:
            try:
                requested_date = datetime.strptime(trade_date, "%Y-%m-%d").date()
            except (TypeError, ValueError) as exc:
                raise ValueError("Analysis date YYYY-MM-DD format mein honi chahiye.") from exc
        else:
            requested_date = today
        if requested_date > today:
            requested_date = today
            P("ticker", "⚠️ Future date diya tha — aaj ki IST date par clamp kar diya", "warn")
        trade_date = requested_date.isoformat()

        # 2) data -----------------------------------------------------------
        P("data", "Price, indicators, fundamentals, news, social, macro fetch ho raha hai...")
        from .data.macro import get_fred_global_macro
        from .data import quant as _quant
        mkt = get_market_data(ticker, trade_date, s.lookback_months)
        fund = get_fundamentals_data(ticker, trade_date)
        news = get_company_news(name, ticker, s.news_article_limit, trade_date)
        macro_news = get_india_macro_news(s.macro_news_limit, trade_date)
        social = get_social_chatter(name, ticker, trade_date)
        mctx = get_market_context(trade_date)
        fred = get_fred_global_macro(trade_date)
        # Qlib-style quant evidence (deterministic) + earnings date
        try:
            qblock = _quant.quant_block(mkt["df"])
            qinfo = _quant.ml_score(mkt["df"])
        except Exception as e:
            logger.warning("quant engine skip: %s", e)
            qblock, qinfo = "", None
        try:
            regime = _quant.regime_state(mkt["df"])
        except Exception as e:
            logger.warning("regime skip: %s", e)
            lo, hi, _ = _quant.REGIME_BANDS["consolidation"]
            regime = {"regime": "consolidation", "band_lo": lo, "band_hi": hi,
                      "intent": "regime engine unavailable"}
        next_result = None
        # Yahoo calendar is a latest snapshot, not point-in-time. Injecting it into
        # historical runs would leak future knowledge into the backtest.
        if requested_date == today:
            try:
                cal = yf.Ticker(ticker).calendar
                ev = (cal.get("Earnings Date") or []) if isinstance(cal, dict) else []
                next_result = str(ev[0])[:10] if ev else None
            except Exception:
                next_result = None
        P("data", f"✅ Data ready: price ₹{mkt['price']:,.2f} ({mkt['snapshot']['date']}), "
                  f"{len(news['items'])} news, {social['count']} social posts", "ok")
        # multi-source data-quality line (sources used + cross-check)
        src_bits = []
        src_bits.append("Yahoo ✓" if mkt.get("data_source") == "yahoo" else
                        f"Yahoo ✗ (fallback: {mkt.get('data_source', '?').upper()})")
        src_bits.append("Screener.in ✓" if fund.get("screener") else "Screener.in ✗")
        src_bits.append("NSE quote ✓" if "NSE" in (mkt.get("price_sources") or []) else "NSE quote ✗")
        src_bits.append("AlphaVantage ✓" if "AlphaVantage" in (mkt.get("price_sources") or [])
                        else "AlphaVantage —")
        src_bits.append("Google News ✓" if news.get("items") else "Google News ✗")
        _fred_text = str(fred.get("fred_block") or "").lower()
        _fred_ok = bool(_fred_text) and "not configured" not in _fred_text and "<unavailable" not in _fred_text
        src_bits.append("FRED ✓" if _fred_ok else "FRED ✗")
        data_sources_text = " | ".join(src_bits)
        quality = assess_data_quality(
            trade_date=trade_date, market=mkt, fundamentals=fund, news=news,
            macro_news=macro_news, social=social, market_context=mctx, fred=fred,
        )
        quality_text = quality_block(quality)
        quality_status = "ok" if quality["score"] >= 80 else "warn"
        P("data", f"🔌 Data sources: {data_sources_text}", "ok")
        P("data", f"Evidence quality: {quality['score']}/100 ({quality['level']})",
          quality_status)

        # Deterministic strategy is computed before any final LLM decision.  The
        # result is later locked over the PM's entry/stop/target/size fields.
        sector_symbol = sector_index_for(ticker, mkt["snapshot"].get("sector"))
        sector_df = None
        if sector_symbol:
            try:
                _start = mkt["df"].index[0].date().isoformat()
                _end = (mkt["df"].index[-1] + pd.Timedelta(days=1)).date().isoformat()
                sector_df = yf.Ticker(sector_symbol).history(
                    start=_start, end=_end, interval="1d", auto_adjust=True,
                )
                if not sector_df.empty:
                    sector_df.index = sector_df.index.tz_localize(None)
            except Exception as e:
                logger.warning("sector relative-strength source unavailable: %s", e)
                sector_df = None
        _strategy_limits = list(quality.get("issues") or [])
        _strategy_limits.extend([
            "Yahoo adjusted history is a current data vintage, not immutable point-in-time data",
            "current-universe survivorship, delistings and historical sector membership are unresolved",
        ])
        strategy_plan = None
        try:
            strategy_plan = DeterministicStrategyEngine().analyze(
                mkt["df"], as_of=trade_date, portfolio=portfolio,
                nifty=mkt.get("benchmark_df"), sector=sector_df,
                sector_symbol=sector_symbol, evidence=None,
                data_limitations=_strategy_limits, event_date=next_result,
            )
            if quality.get("hard_block"):
                _apply_deterministic_quality_block(strategy_plan)
            P("strategy", f"Deterministic {strategy_plan.action.value}: "
                          f"{strategy_plan.setup_name} ({strategy_plan.signal_state.value})", "ok")
        except Exception as e:
            logger.exception("deterministic strategy failed closed")
            P("strategy", f"Deterministic engine unavailable — REVIEW: {str(e)[:100]}", "error")

        price = mkt["price"]
        company_block = (
            f"COMPANY: {name} | Ticker: {ticker} ({inst['exchange']}) | "
            f"Sector: {mkt['snapshot'].get('sector') or '?'} | "
            f"Analysis date: {trade_date} | Current price: ₹{price:,.2f}"
            + (f" | Next results: ~{next_result}" if next_result else "")
            + f"\n{quality_text}"
        )
        strategy_prompt = _deterministic_prompt(strategy_plan)

        # memory ------------------------------------------------------------
        past = self.decision_log.past_decisions(ticker)
        past_ctx = mem.memory_context_text(past, mkt["df"][["Close"]])

        # 3) analysts (parallel, different providers => real diversity) ------
        analysts = {}
        if "market" in s.selected_analysts:
            analysts["market"] = (MARKET_ANALYST, company_block + "\n\n" +
                                  mkt["indicator_block"] +
                                  (f"\n\n{qblock}" if qblock else "") +
                                  "\n\n" + mctx["market_context_block"])
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
                user = (f"{company_block}\n\n"
                        + (f"=== QUANT SNAPSHOT (deterministic — reversal-signal dates/"
                           f"volume is data se cite karo) ===\n{qblock}\n\n" if qblock else "")
                        + f"{analyst_evidence}\n\n"
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
        if s.battle_mode != "off" and len(providers) >= 2 and draft_verdict:
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
        else:
            P("battle", "Battle ke liye kam se kam 2 independent providers chahiye — skip", "warn")

        # 7) trader ------------------------------------------------------------
        P("trader", "Trader execution plan bana raha hai...")
        trader_plan = ""
        try:
            trader_plan, prov = self.engine.call(
                "trader", TRADER + self.lang,
                f"{company_block}\n\n"
                f"MARKET REGIME (deterministic): {regime['regime']} | allowed position "
                f"band: {regime['band_lo']}-{regime['band_hi']}% — plan is regime se "
                f"aligned hona chahiye.\n\n"
                f"=== FINAL RESEARCH VERDICT ===\n{final_research}\n\n"
                f"{strategy_prompt}\n\n"
                f"=== KEY PRICE DATA ===\n{mkt['indicator_block'][:1500]}\n\n"
                + (f"=== QUANT SNAPSHOT ===\n{qblock}\n\n" if qblock else "")
                + f"{past_ctx}")
            P("trader", f"✅ Trader ({prov}) plan ready", "ok")
        except ProviderError as e:
            P("trader", f"❌ Trader fail: {str(e)[:80]}", "error")

        # 8) risk team (3-way, parallel) ----------------------------------------
        P("risk", "Risk team (Aggressive / Conservative / Neutral) debate kar rahi hai...")
        _regime_ctx = (f"MARKET REGIME (deterministic): {regime['regime']} | allowed "
                       f"position/sizing band: {regime['band_lo']}-{regime['band_hi']}% | "
                       f"realistic transitions: "
                       f"{', '.join(_quant.LEGAL_TRANSITIONS.get(regime['regime'], []))}"
                       "\n(Debate mein aggressive bhi is band ke against sizing propose "
                       "nahi kar sakta — regime hard constraint hai.)\n\n")
        risk_jobs = [
            {"role": "aggressive_analyst", "system": AGGRESSIVE_ANALYST + self.lang,
             "user": f"{company_block}\n\n{_regime_ctx}TRADER PLAN:\n{trader_plan or '<unavailable>'}"},
            {"role": "conservative_analyst", "system": CONSERVATIVE_ANALYST + self.lang,
             "user": f"{company_block}\n\n{_regime_ctx}{mkt['indicator_block'][:2000]}\n\n"
                     + (f"=== QUANT SNAPSHOT ===\n{qblock}\n\n" if qblock else "")
                     + f"TRADER PLAN:\n{trader_plan or '<unavailable>'}"},
            {"role": "neutral_analyst", "system": NEUTRAL_ANALYST + self.lang,
             "user": f"{company_block}\n\n{_regime_ctx}TRADER PLAN:\n{trader_plan or '<unavailable>'}"},
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
        pm_user = (f"{company_block}\n\n{strategy_prompt}\n\n"
                   f"=== FINAL RESEARCH VERDICT (post-battle) ===\n"
                   f"{final_research}\n\n=== TRADER PLAN ===\n{trader_plan}\n\n"
                   f"=== RISK TEAM VIEWS ===\n{risk_block}\n\n{past_ctx}\n\n"
                   + (f"=== QUANT SNAPSHOT (deterministic anchor) ===\n{qblock}\n\n" if qblock else "")
                   + (f"=== MARKET REGIME (hard discipline layer) ===\n"
                      f"Regime: {regime['regime']} | Allowed position band: "
                      f"{regime['band_lo']}-{regime['band_hi']}% | {regime['intent']}\n"
                      f"(Bull-conditions: {regime.get('bull_of6', '?')}/6 | "
                      f"Bear-conditions: {regime.get('bear_of6', '?')}/6 — 5/6 = confirmed)\n"
                      f"Realistic next transitions: "
                      f"{', '.join(_quant.LEGAL_TRANSITIONS.get(regime['regime'], []))}\n\n")
                   + f"=== PRICE SNAPSHOT ===\nCurrent: ₹{price:,.2f} | "
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
                pm_user += (f"\n\n(PARSE ERROR: {str(e)[:150]} — "
                            "ONLY output the valid JSON object, nothing else.")

        # --- TradeHive-style regime discipline (hard backstop) --------------
        if decision is not None:
            _pre_pos = decision.get("position_size_pct")
            decision = _apply_regime_discipline(decision, regime)
            _bn = decision.get("battle_notes") or ""
            if "REGIME CLAMP" in _bn:
                P("final", f"⚠️ Regime clamp: position {_pre_pos}% → "
                           f"{decision['position_size_pct']}% ({regime['regime']})", "warn")
            if "REGIME LOCK" in _bn:
                P("final", f"🚫 Regime lock: BUY → HOLD ({regime['regime']} band "
                           f"{regime['band_lo']}-{regime['band_hi']}%)", "warn")
            elif (decision["decision"] == "BUY"
                  and int(decision.get("position_size_pct") or 0) < regime["band_lo"]
                  and regime["band_hi"] > 0):
                P("final", f"ℹ️ PM conservative: {decision['position_size_pct']}% vs "
                           f"regime band {regime['band_lo']}-{regime['band_hi']}%", "info")

            before_guard = (decision["decision"], decision["position_size_pct"],
                            decision["confidence"])
            decision = apply_trade_guard(decision, price)
            decision = apply_quality_guard(decision, quality)
            after_guard = (decision["decision"], decision["position_size_pct"],
                           decision["confidence"])
            if after_guard != before_guard:
                P("final", f"🧮 Code guards: action/size/conf {before_guard} → {after_guard}",
                  "warn")

        if decision is None:
            decision = {"decision": "HOLD", "confidence": 0, "rating": "Hold",
                        "rationale": "Portfolio Manager call failed — data par bharosa "
                                     "karte hue ye neutral HOLD hai. Dobara run karo.",
                        "key_risks": ["LLM call failure"], "entry_zone": "—",
                        "target": "—", "stop_loss": "—", "position_size_pct": 0,
                        "timeframe": "—", "battle_notes": "—"}
            decision = apply_quality_guard(decision, quality)
            decision["trade_validation"] = {
                "verified": False, "valid": False, "rr": None, "levels": {},
                "max_loss_pct": 1.0, "notes": ["PM unavailable"],
            }
            P("final", "❌ PM fail — safe HOLD fallback used", "error")

        # LLM rationale is preserved separately, but deterministic economics and
        # the detailed action are immutable from this point onward.
        ai_decision = json.loads(json.dumps(decision, ensure_ascii=False, default=str))
        deterministic = strategy_plan.to_dict() if strategy_plan is not None else {
            "as_of": trade_date, "action": "REVIEW", "legacy_action": "HOLD",
            "setup_name": "Unavailable", "signal_state": "INVALID",
            "trigger": "Deterministic engine failed; do not trade", "trigger_price": None,
            "entry_zone": None, "confirmations": [],
            "missing_confirmations": ["deterministic engine output unavailable"],
            "invalidation": "not available", "initial_stop": None,
            "stop_reason": "not available", "target_1": None, "target_2": None,
            "reward_risk": None, "quantity": 0, "allocation_rupees": 0,
            "allocation_pct": 0, "max_loss_rupees": 0,
            "max_portfolio_loss_pct": 0, "trailing_rule": "not available",
            "early_exit_rules": [], "time_stop_sessions": 0,
            "support_zones": [], "resistance_zones": [], "relative_strength": {},
            "weekly": {}, "daily": {}, "deterministic_reasons": ["fail-closed REVIEW"],
            "limitations": _strategy_limits,
            "evidence": {"status": "BACKTEST NOT AVAILABLE", "validated_edge": False,
                         "trades": 0, "walk_forward_windows": 0, "reasons": []},
            "config_version": "deterministic-v1",
        }
        decision = _lock_deterministic_decision(decision, deterministic, portfolio)

        # 10) report ------------------------------------------------------------
        P("report", "Report generate ho rahi hai...")
        result = {
            "ticker": ticker, "name": name, "exchange": inst["exchange"],
            "trade_date": trade_date, "price": price,
            "snapshot": mkt["snapshot"], "analyst_reports": reports,
            "debate": debate_history, "draft_verdict": draft_verdict,
            "battle_critiques": battle_section, "final_research": final_research,
            "trader_plan": trader_plan, "risk_views": risk_block,
            "decision": decision, "ai_decision": ai_decision,
            "deterministic": deterministic, "portfolio_inputs": portfolio.__dict__,
            "backtest": None, "memory": past_ctx,
            "quant": qinfo, "next_results": next_result,
            "data_quality": quality,
            "news_block": news["news_block"], "macro_news_block": macro_news["macro_news_block"],
            "social_block": social["social_block"],
            "indicator_block": mkt["indicator_block"],
            "fundamentals_block": fund["fundamentals_block"],
            "market_context_block": mctx["market_context_block"],
            "fred_block": fred["fred_block"],
            "models": self.engine.provider_models(), "stats": self.engine.stats.by_provider(),
            "settings": self.settings.as_dict(), "mock": self.settings.mock_llm,
            "progress_events": self.progress.events,
            "data_sources": {
                "text": data_sources_text,
                "price_sources": mkt.get("price_sources", []),
                "data_quality": mkt.get("data_quality", ""),
                "screener_note": fund.get("screener_note", ""),
                "quality_score": quality["score"],
                "quality_level": quality["level"],
                "quality_issues": quality["issues"],
            },
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
        # reflection lesson (learning loop — original TradingAgents se inspired)
        lesson = None
        if past and not s.mock_llm:
            try:
                from .agents.prompts import REFLECTION
                lesson, _lp = self.engine.call(
                    "reflection", REFLECTION + self.lang,
                    f"PAST DECISIONS:\n{past_ctx}\n\nCURRENT DECISION (just made):\n"
                    f"{decision['decision']}/{decision['rating']} conf={decision['confidence']}% "
                    f"@ ₹{price:,.2f}\nRationale: {(decision.get('rationale') or '')[:400]}\n\n"
                    f"2-3 line ka imandaar Hinglish lesson likho.", temperature=0.2)
                lesson = lesson.strip()[:500]
                P("report", "🧠 Reflection lesson saved (agli report mein use hoga)", "ok")
            except Exception as e:
                logger.warning("reflection skip: %s", e)
        self.decision_log.append(ticker, decision, price, lesson)
        P("report", f"✅ Report save ho gayi: {paths['md']}", "ok")
        result["paths"] = paths
        return result


def _apply_deterministic_quality_block(plan) -> None:
    """Fail closed without leaving a REVIEW action paired with a trade size."""
    plan.action = DetailedAction.REVIEW
    plan.legacy_action = "HOLD"
    plan.quantity = 0
    plan.allocation_rupees = 0.0
    plan.allocation_pct = 0.0
    plan.max_loss_rupees = 0.0
    plan.max_portfolio_loss_pct = 0.0
    plan.deterministic_reasons.append(
        "data-quality hard block forces REVIEW; no fresh deterministic trade"
    )


def _deterministic_prompt(plan) -> str:
    if plan is None:
        return ("DETERMINISTIC STRATEGY: unavailable — action REVIEW. "
                "You may explain risks only; do not invent levels or statistics.")
    z = plan.entry_zone
    zone = f"₹{z.low:,.2f}–₹{z.high:,.2f}" if z else "unavailable"
    return (
        "=== DETERMINISTIC STRATEGY (CODE AUTHORITY — DO NOT OVERRIDE) ===\n"
        f"Detailed action: {plan.action.value} | setup: {plan.setup_name} | "
        f"state: {plan.signal_state.value}\n"
        f"Trigger: {plan.trigger}\nEntry zone: {zone} | stop: "
        f"{('₹' + format(plan.initial_stop, ',.2f')) if plan.initial_stop else 'unavailable'} | "
        f"T1/T2: {plan.target_1}/{plan.target_2} | quantity: {plan.quantity}\n"
        f"Evidence: {plan.evidence.status}. LLM role is explanation/bull-bear critique only; "
        "entry, stop, targets, size, action and backtest statistics are immutable code output."
    )


def _lock_deterministic_decision(decision: dict, plan: dict,
                                 portfolio: PortfolioInputs) -> dict:
    """Legacy decision compatibility with deterministic fields as authority."""
    d = dict(decision)
    d["ai_proposed_decision"] = decision.get("decision")
    d["ai_confidence"] = decision.get("confidence")
    d["confidence_kind"] = "legacy_ai_commentary_only_not_strategy_confidence"
    d["detailed_action"] = plan["action"]
    d["decision"] = plan["legacy_action"]
    d["rating"] = plan["action"].title()
    zone = plan.get("entry_zone")
    d["entry_zone"] = (f"₹{zone['low']:,.2f}–₹{zone['high']:,.2f}" if zone else "—")
    t1, t2 = plan.get("target_1"), plan.get("target_2")
    d["target"] = (f"T1 ₹{t1:,.2f} · T2 ₹{t2:,.2f}" if t1 is not None and t2 is not None else "—")
    stop = plan.get("initial_stop")
    d["stop_loss"] = f"₹{stop:,.2f}" if stop is not None else "—"
    d["position_size_pct"] = int(float(plan.get("allocation_pct") or 0))
    d["quantity"] = int(plan.get("quantity") or 0)
    d["timeframe"] = portfolio.horizon
    d["rationale"] = "; ".join(plan.get("deterministic_reasons") or [])
    d["trade_validation"] = {
        "verified": all(x is not None for x in (stop, t1, t2)) and zone is not None,
        "valid": plan.get("signal_state") != "INVALID",
        "rr": plan.get("reward_risk"),
        "levels": {"entry": zone, "target_1": t1, "target_2": t2, "stop": stop},
        "max_loss_pct": portfolio.max_risk_pct,
        "notes": ["locked by deterministic-v1; LLM proposal cannot override"],
    }
    d["battle_notes"] = ((d.get("battle_notes") or "").rstrip()
                         + " | 🔒 DETERMINISTIC LOCK: AI proposal retained only as commentary; "
                           "action/entry/stop/targets/quantity are code-owned.").strip(" |")
    return d


def _condense(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...(truncated for length)..."


# --- TradeHive-style regime discipline (hard backstop) ----------------------
def _apply_regime_discipline(decision: dict, regime: dict) -> dict:
    """Position band clamp + decision-label consistency (TradeHive Trader/PM
    code-layer fallback se adapted). Upper-side hard clamp; BUY jiske liye koi
    allowed position hi nahi bacha use HOLD/WAIT lock kar do (BUY-0% inconsistent
    output hai — user ko lagega "kharido par 0%")."""
    _lo, _hi = regime["band_lo"], regime["band_hi"]
    _pos = decision.get("position_size_pct")
    try:
        _pos = int(float(str(_pos).replace("%", "").strip()))   # "40%" → 40, None → 0
    except (TypeError, ValueError):
        _pos = 0
    _pos = max(0, min(100, _pos))
    decision["position_size_pct"] = _pos          # normalize ALWAYS
    if _pos > _hi:                      # risk cap — upper side hard clamp
        decision["position_size_pct"] = _hi
        decision["battle_notes"] = (
            (decision.get("battle_notes") or "") +
            f" | ⚠️ REGIME CLAMP: PM ne {_pos}% bola, {regime['regime']} "
            f"band {_lo}-{_hi}% hai → {_hi}% pe clamp kiya (code discipline).")
    # Action-label consistency (TradeHive: clamp ke baad action re-derive hota hai)
    if decision.get("decision") == "BUY" and int(decision.get("position_size_pct") or 0) == 0:
        decision["decision"] = "HOLD"
        if str(decision.get("rating", "")).strip().lower() in ("buy", "strong buy"):
            decision["rating"] = "Hold"
        decision["battle_notes"] = (
            (decision.get("battle_notes") or "") +
            f" | 🚫 REGIME LOCK: {regime['regime']} band {_lo}-{_hi}% — BUY ka koi "
            "allowed position nahi bacha, isliye decision HOLD/WAIT lock kiya gaya "
            "(fresh entry abhi nahi).")
    decision["regime"] = regime["regime"]
    decision["regime_band"] = f"{_lo}-{_hi}%"
    return decision


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
    kr = [x for x in kr
          if x.strip()
          and not _NEG_ENTRY_FULL_RE.match(x.strip())
          and not _NEG_ENTRY_SUB_RE.search(x.strip())]
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
