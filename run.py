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

    try:
        res = pipe.run(args.ticker, args.date)
    except Exception as e:
        print(f"\n❌ Run failed: {e}")
        sys.exit(1)

    dec = res["decision"]
    print(f"""
{COLORS['bold']}{'=' * 62}
🎯 FINAL DECISION: {dec['decision']}  |  {dec.get('rating')}  |  Confidence: {dec.get('confidence')}%
{'=' * 62}{COLORS['end']}
Entry:    {dec.get('entry_zone')}
Target:   {dec.get('target')}
Stop:     {dec.get('stop_loss')}
Size:     {dec.get('position_size_pct')}% of capital
Timeframe:{dec.get('timeframe')}

{dec.get('rationale')}

📄 Full report:
   {res['paths']['md']}
   {res['paths']['html']}
⚠️  Ye AI research hai, financial advice nahi.
""")


if __name__ == "__main__":
    main()
