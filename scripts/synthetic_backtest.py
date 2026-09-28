#!/usr/bin/env python3
"""Reproducible, network-free walk-forward smoke test.

This is a mechanics check, not evidence of a profitable strategy.  Synthetic
prices cannot validate a market edge.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from indiaagents.backtest import WalkForwardConfig, run_walk_forward  # noqa: E402
from indiaagents.strategy import DeterministicStrategyEngine, PortfolioInputs  # noqa: E402


def fixture(rows: int = 1000, seed: int = 20260928) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2022-01-03", periods=rows)
    close = 100 * np.exp(np.cumsum(rng.normal(0.00045, 0.011, rows)))
    stock = pd.DataFrame({
        "Open": close * (1 + rng.normal(0, 0.002, rows)),
        "High": close * 1.012, "Low": close * 0.988, "Close": close,
        "Volume": rng.integers(200_000, 2_000_000, rows),
    }, index=idx)
    benchmark_close = 100 * np.exp(np.cumsum(rng.normal(0.00025, 0.008, rows)))
    benchmark = pd.DataFrame({
        "Open": benchmark_close, "High": benchmark_close * 1.008,
        "Low": benchmark_close * 0.992, "Close": benchmark_close,
        "Volume": 2_000_000,
    }, index=idx)
    return stock, benchmark


def main() -> None:
    stock, benchmark = fixture()
    engine = DeterministicStrategyEngine()
    first = engine.analyze(stock, nifty=benchmark, portfolio=PortfolioInputs()).to_dict()
    second = engine.analyze(stock.copy(), nifty=benchmark.copy(), portfolio=PortfolioInputs()).to_dict()
    if first != second:
        raise AssertionError("Repeated deterministic analysis differs")
    wf = run_walk_forward(
        stock, nifty=benchmark,
        walk_config=WalkForwardConfig(
            train_sessions=300, validation_sessions=100, test_sessions=100,
            step_sessions=100, embargo_sessions=5,
        ),
        data_limitations=["synthetic fixture; not investable evidence"],
    )
    summary = {
        "fixture_seed": 20260928, "same_output": True,
        "action": first["action"], "setup": first["setup_name"],
        "walk_forward_windows": len(wf.windows), "oos_trades": wf.metrics["trades"],
        "net_return_pct": wf.metrics["net_total_return_pct"],
        "acceptance": wf.acceptance["status"],
        "warning": "Synthetic output validates mechanics only, never market edge.",
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
