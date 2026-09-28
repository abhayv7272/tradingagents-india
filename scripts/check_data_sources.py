#!/usr/bin/env python3
"""Live provider reachability/health check (separate from offline tests).

This command never prints API keys and never disables TLS verification. It is an
operator diagnostic, not a CI/core-test dependency.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indiaagents.data.adapters import YahooOHLCVSource
from indiaagents.data.fundamentals import get_fundamentals_data
from indiaagents.data.health import classify_exception, health, india_today
from indiaagents.data.macro import get_fred_global_macro, get_market_context
from indiaagents.data.news import get_company_news, get_india_macro_news
from indiaagents.data.social import get_social_chatter
from indiaagents.data.sources import (
    get_alpha_vantage_history,
    get_alpha_vantage_quote,
    get_nse_quote,
    get_screener_fundamentals,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live market-data providers")
    parser.add_argument("--ticker", default="RELIANCE.NS")
    parser.add_argument("--name", default="Reliance Industries")
    parser.add_argument("--date", default=india_today().isoformat())
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    records: list[dict] = []
    end = args.date
    start = (date.fromisoformat(end) - timedelta(days=400)).isoformat()
    try:
        result = YahooOHLCVSource().fetch(args.ticker, start, end, adjusted=True)
        records.append(health(
            "yahoo", "ohlcv-primary", "available" if len(result.data) else "empty",
            "live diagnostic adjusted history", rows=len(result.data),
            as_of=result.provenance.end,
        ).to_dict())
    except Exception as exc:
        status, detail = classify_exception(exc)
        records.append(health("yahoo", "ohlcv-primary", status, detail).to_dict())

    for fetcher, category in (
        (get_alpha_vantage_history, "ohlcv-fallback"),
        (get_alpha_vantage_quote, "live-quote"),
        (get_nse_quote, "live-quote"),
    ):
        result = fetcher(args.ticker, with_health=True)
        records.append(result.health.to_dict())

    screener = get_screener_fundamentals(
        args.ticker, args.name, with_health=True,
    )
    records.append(screener.health.to_dict())

    payloads = [
        get_fundamentals_data(args.ticker, args.date),
        get_company_news(args.name, args.ticker, 6, args.date),
        get_india_macro_news(6, args.date),
        get_social_chatter(args.name, args.ticker, args.date),
        get_market_context(args.date),
        get_fred_global_macro(args.date),
    ]
    for payload in payloads:
        records.extend(payload.get("source_health") or [])

    counts: dict[str, int] = {}
    for record in records:
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    output = {
        "ticker": args.ticker,
        "analysis_date": args.date,
        "tls_verification_disabled": False,
        "status_counts": counts,
        "sources": records,
    }
    if args.as_json:
        print(json.dumps(output, indent=2, default=str))
    else:
        print(f"Live source diagnostic — {args.ticker} as of {args.date}")
        print("TLS verification: ON (never bypassed)")
        print("-" * 110)
        print(f"{'SOURCE':18} {'CATEGORY':34} {'STATUS':18} {'ROWS':>6}  DETAIL")
        print("-" * 110)
        for record in records:
            print(f"{record['source'][:18]:18} {record['category'][:34]:34} "
                  f"{record['status'][:18]:18} {record.get('rows') or '—'!s:>6}  "
                  f"{record.get('detail') or ''}")
        print("-" * 110)
        print("Counts:", ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
        print("empty does not mean market silence; inspect status and detail.")
    # Reachability issues are diagnostic output, not command failure. A malformed
    # invocation still exits non-zero through argparse/date parsing.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
