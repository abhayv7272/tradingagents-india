"""
Decision memory + reflection — adapted from TradingAgents' trading_memory concept.
Logs every decision; on the next run for the same ticker, computes the realized
return (raw + alpha vs NIFTY) so the Portfolio Manager learns from past calls.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .config import MEMORY_DIR


class DecisionLog:
    def __init__(self, memory_dir: Path | None = None):
        self.dir = Path(memory_dir) if memory_dir else MEMORY_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "decision_log.jsonl"

    def append(self, ticker: str, decision: dict, price: float | None,
               lesson: str | None = None) -> None:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "ticker": ticker,
            "decision": decision.get("decision"),
            "rating": decision.get("rating"),
            "confidence": decision.get("confidence"),
            "price": price,
            "rationale": (decision.get("rationale") or "")[:400],
            "lesson": (lesson or None),
        }
        with open(self.file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def past_decisions(self, ticker: str, limit: int = 3) -> list[dict]:
        if not self.file.exists():
            return []
        out = []
        for line in self.file.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("ticker") == ticker:
                out.append(e)
        return out[-limit:]

    def recent_lessons(self, limit: int = 5) -> list[dict]:
        """Recent decisions across all tickers (cross-ticker context)."""
        if not self.file.exists():
            return []
        try:
            lines = self.file.read_text(encoding="utf-8").splitlines()
            items = []
            for line in lines:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return items[-limit:]
        except Exception:
            return []


def realized_return(close_hist, ticker: str, decision_date: str) -> dict | None:
    """Stock return since a past decision date + alpha vs NIFTY (deterministic)."""
    import pandas as pd
    import yfinance as yf
    try:
        after = close_hist[close_hist.index >= pd.Timestamp(decision_date)]
        if after.empty:
            return None
        then = float(after["Close"].iloc[0]) if "Close" in after else float(after.iloc[0])
        now = float(close_hist["Close"].iloc[-1]) if "Close" in close_hist else float(close_hist.iloc[-1])
        if not then:
            return None
        stock_ret = (now - then) / then * 100

        nifty = yf.Ticker("^NSEI").history(start=decision_date)["Close"]
        n_then = float(nifty.iloc[0]) if not nifty.empty else None
        n_now = float(nifty.iloc[-1]) if not nifty.empty else None
        n_ret = ((n_now - n_then) / n_then * 100) if (n_then and n_now) else None
        alpha = (stock_ret - n_ret) if n_ret is not None else None
        return {"stock_ret": round(stock_ret, 1), "nifty_ret": round(n_ret, 1) if n_ret is not None else None,
                "alpha": round(alpha, 1) if alpha is not None else None,
                "from": decision_date}
    except Exception:
        return None


def memory_context_text(past: list[dict], close_hist) -> str:
    """Render past decisions + realized returns for the Portfolio Manager prompt."""
    if not past:
        return "PAST DECISIONS: Is ticker par pehle koi decision nahi liya gaya."
    lines = []
    for p in past:
        rr = realized_return(close_hist, p["ticker"], p["ts"][:10]) if p.get("price") else None
        perf = ""
        if rr:
            perf = (f" | Result: stock {rr['stock_ret']}% vs NIFTY {rr['nifty_ret']}% "
                    f"(alpha {rr['alpha']:+.1f}%)") if rr.get("nifty_ret") is not None else \
                   f" | Result: stock {rr['stock_ret']}%"
        lines.append(f"- {p['ts'][:10]}: {p['decision']} ({p['rating']}, conf {p['confidence']}%) "
                     f"@ ₹{p['price']}{perf}")
        if p.get("lesson"):
            lines.append(f"  LESSON (reflection): {p['lesson']}")
    return ("PAST DECISIONS for this ticker (learn from these — were we right?):\n"
            + "\n".join(lines))
