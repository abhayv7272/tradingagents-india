#!/usr/bin/env python3
"""
TradingAgents India — CLI
Usage:
    python run.py RELIANCE
    python run.py TCS --date 2026-09-01 --rounds 2 --lang hinglish
    python run.py INFY --mock          # demo without keys
    python run.py BEL --battle off     # single-provider mode
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

from indiaagents.config import Settings, available_providers  # noqa: E402
from indiaagents.pipeline import TradingAgentsIndiaPipeline  # noqa: E402
from indiaagents.strategy import PortfolioInputs, sector_index_for  # noqa: E402

COLORS = {"ok": "\033[92m", "warn": "\033[93m", "error": "\033[91m",
          "info": "\033[96m", "end": "\033[0m", "bold": "\033[1m"}


def cli_progress(ev: dict):
    c = COLORS.get(ev["status"], COLORS["info"])
    print(f"{c}[{ev['time']}] {ev['stage'].upper():10s} | {ev['detail']}{COLORS['end']}",
          flush=True)


def main():
    ap = argparse.ArgumentParser(description="TradingAgents India — free AI stock research")
    ap.add_argument("ticker", help="Stock name / NSE ticker (e.g. RELIANCE, TCS.NS)")
    ap.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    ap.add_argument("--rounds", type=int, default=None, help="Bull-Bear debate rounds")
    ap.add_argument("--risk-rounds", type=int, default=None)
    ap.add_argument("--battle", choices=["auto", "off"], default=None)
    ap.add_argument("--lang", choices=["hinglish", "english", "hindi"], default=None)
    ap.add_argument("--mock", action="store_true", help="Demo mode without API keys")
    holding = ap.add_mutually_exclusive_group()
    holding.add_argument("--existing-holding", action="store_true", help="You already own this stock")
    holding.add_argument("--fresh", action="store_true", help="Fresh investor (default)")
    ap.add_argument("--average-buy-price", type=float)
    ap.add_argument("--quantity", type=int, default=0)
    ap.add_argument("--capital", type=float, default=100000.0)
    ap.add_argument("--max-risk", type=float, default=1.0, help="Maximum portfolio risk per trade, percent")
    ap.add_argument("--max-allocation", type=float, default=20.0, help="Maximum single-stock allocation, percent")
    ap.add_argument("--horizon", choices=["swing", "positional", "long-term"], default="positional")
    ap.add_argument("--risk-profile", choices=["conservative", "balanced", "aggressive"], default="balanced")
    ap.add_argument("--walk-forward", action="store_true",
                    help="Explicitly run a cost-aware walk-forward backtest after research")
    ap.add_argument("--backtest-years", type=int, default=10)
    args = ap.parse_args()

    s = Settings.from_env()
    if args.rounds:
        s.debate_rounds = args.rounds
    if args.risk_rounds:
        s.risk_rounds = args.risk_rounds
    if args.battle:
        s.battle_mode = args.battle
    if args.lang:
        s.report_language = args.lang
    if args.mock:
        s.mock_llm = True

    print(f"{COLORS['bold']}🇮🇳 TradingAgents India — {args.ticker} "
          f"({args.date}){COLORS['end']}")
    print(f"Providers: {', '.join(available_providers()) or 'NONE (mock mode)'} | "
          f"Battle: {s.battle_mode} | Rounds: {s.debate_rounds} | "
          f"Lang: {s.report_language}\n")

    try:
        pipe = TradingAgentsIndiaPipeline(s, progress_cb=cli_progress)
    except Exception as e:
        print(f"\n❌ {e}")
        sys.exit(1)

    portfolio = PortfolioInputs(
        existing_holding=args.existing_holding or args.quantity > 0,
        average_buy_price=args.average_buy_price, current_quantity=args.quantity,
        portfolio_capital=args.capital, max_risk_pct=args.max_risk,
        max_single_stock_pct=args.max_allocation, horizon=args.horizon,
        risk_profile=args.risk_profile,
    ).validated()
    try:
        res = pipe.run(args.ticker, args.date, portfolio)
    except Exception as e:
        print(f"\n❌ Run failed: {e}")
        sys.exit(1)

    dec = res["decision"]
    det = res["deterministic"]
    print(f"""
{COLORS['bold']}{'=' * 72}
🎯 DETERMINISTIC ACTION: {det['action']}  |  {det['setup_name']}  |  {det['signal_state']}
{'=' * 72}{COLORS['end']}
Trigger:  {det['trigger']}
Entry:    {dec.get('entry_zone')}
T1 / T2: ₹{det.get('target_1') or 0:,.2f} / ₹{det.get('target_2') or 0:,.2f}
Stop:     {dec.get('stop_loss')} — {det.get('stop_reason')}
Quantity: {det.get('quantity')} | Allocation: {det.get('allocation_pct')}%
Max loss: ₹{det.get('max_loss_rupees'):,.2f} ({det.get('max_portfolio_loss_pct')}% portfolio)
R:R:      {det.get('reward_risk') or 'unavailable'}
Evidence: {det.get('evidence', {}).get('status', 'BACKTEST NOT AVAILABLE')}
Sources:  {(res.get('data_sources') or {}).get('text', 'no diagnostics')}

AI commentary is separate and cannot override the code-owned plan.

📄 Full report:
   {res['paths']['md']}
   {res['paths']['html']}
⚠️  Educational research only; historical performance future returns guarantee nahi karti.
""")

    if args.walk_forward:
        try:
            import json
            from indiaagents.backtest import run_walk_forward
            from indiaagents.data.adapters import fetch_strategy_history
            from indiaagents.report import build_report
            hist = fetch_strategy_history(res["ticker"], args.backtest_years, end=args.date)
            bench = fetch_strategy_history("^NSEI", args.backtest_years, end=args.date)
            sector_symbol = sector_index_for(res["ticker"], res["snapshot"].get("sector"))
            sector = (fetch_strategy_history(sector_symbol, args.backtest_years, end=args.date)
                      if sector_symbol else None)
            wf = run_walk_forward(
                hist.data, nifty=bench.data, sector=sector.data if sector else None,
                sector_symbol=sector_symbol, sector_name=res["snapshot"].get("sector"),
                data_limitations=hist.provenance.limitations,
            )
            res["backtest"] = wf.to_dict(include_curve=True)
            res["deterministic"]["evidence"] = {
                "status": wf.acceptance["status"],
                "validated_edge": wf.acceptance["validated_edge"],
                "trades": wf.metrics["trades"],
                "walk_forward_windows": len(wf.windows),
                "profit_factor": wf.metrics["profit_factor"],
                "expectancy_r": wf.metrics["expectancy_r"],
                "max_drawdown_pct": wf.metrics["max_drawdown_pct"],
                "reasons": wf.acceptance["failed_reasons"], "metrics": wf.metrics,
            }
            paths = build_report(res)
            Path(paths["dir"], "backtest.json").write_text(
                json.dumps(wf.to_dict(include_curve=False), indent=2, default=str), encoding="utf-8")
            print(f"\n📊 OOS: {wf.metrics['trades']} trades | PF {wf.metrics['profit_factor']} | "
                  f"Expectancy {wf.metrics['expectancy_r']}R | {wf.acceptance['status']}")
            print(f"Walk-forward windows: {len(wf.windows)} | Scope: {wf.acceptance['scope']}")
        except Exception as e:
            print(f"\n⚠️ Backtest unavailable: {e}")


if __name__ == "__main__":
    main()
