#!/usr/bin/env python3
"""
PART B — REAL AI REPORT BACKTEST (LLM calls, user-authorized)
==============================================================
6 stocks par PURI pipeline chalata hai trade_date=2026-07-15 pe
(point-in-time), phir hum verdict ko actual outcome se compare karenge.

Memory isolated hai (reports/_backtest_memory) taaki backtest runs
real usage ki memory ko pollute na karein.
"""
import json
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

# ---- memory isolation (pipeline import se PEHLE patch) ----
import indiaagents.memory as mem  # noqa: E402
_BT_MEM = ROOT / "reports" / "_backtest_memory"
_orig_log = mem.DecisionLog
mem.DecisionLog = lambda *a, **k: _orig_log(memory_dir=_BT_MEM)

from indiaagents.config import Settings  # noqa: E402
from indiaagents.pipeline import TradingAgentsIndiaPipeline  # noqa: E402

STOCKS = ["RELIANCE", "TCS", "HDFBANK", "INFY", "SBIN", "TATASTEEL"]
TRADE_DATE = "2026-07-15"          # ~2.5 mahine pehle → 20d window settled
OUT = ROOT / "reports" / "_backtest_llm_results.json"


def main():
    settings = Settings()           # battle auto, real LLM
    results = []
    t0 = time.time()
    for i, s in enumerate(STOCKS, 1):
        print(f"\n[{i}/{len(STOCKS)}] {s} @ {TRADE_DATE} — "
              f"elapsed {time.time()-t0:.0f}s", flush=True)
        try:
            pipe = TradingAgentsIndiaPipeline(settings)

            def cb(stage, msg, level="info", _s=s):
                print(f"    [{_s}] {stage}: {msg[:90]}", flush=True)

            out = pipe.run(s, trade_date=TRADE_DATE)
            d = out["decision"]
            rec = {
                "ticker": s, "trade_date": TRADE_DATE,
                "decision": d.get("decision"), "rating": d.get("rating"),
                "confidence": d.get("confidence"),
                "entry_zone": d.get("entry_zone"), "target": d.get("target"),
                "stop_loss": d.get("stop_loss"), "timeframe": d.get("timeframe"),
                "rationale": (d.get("rationale") or "")[:300],
                "report_path": str(out.get("report_path", "")),
                "ok": True,
            }
            print(f"    >>> VERDICT: {rec['decision']} ({rec['rating']}) "
                  f"conf={rec['confidence']}%", flush=True)
        except Exception as e:
            rec = {"ticker": s, "trade_date": TRADE_DATE, "ok": False,
                   "error": f"{type(e).__name__}: {str(e)[:200]}"}
            print(f"    !!! FAILED: {rec['error']}", flush=True)
            traceback.print_exc()
        results.append(rec)
        OUT.write_text(json.dumps(results, indent=1))   # incremental save
    print(f"\nDONE — {sum(1 for r in results if r['ok'])}/{len(results)} ok "
          f"in {time.time()-t0:.0f}s → {OUT}", flush=True)


if __name__ == "__main__":
    main()
