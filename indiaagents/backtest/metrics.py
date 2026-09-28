"""Net-of-cost performance metrics, uncertainty and acceptance gate."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .execution import BacktestResult, Trade


def _finite(value: float | None) -> float | None:
    try:
        x = float(value)
        return round(x, 4) if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _group(trades: list[Trade], field: str) -> dict[str, dict]:
    groups: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        groups[str(getattr(t, field) or "unavailable")].append(t)
    return {
        key: {
            "trades": len(values),
            "net_pnl": round(sum(x.net_pnl for x in values), 2),
            "win_rate_pct": round(sum(x.net_pnl > 0 for x in values) / len(values) * 100, 2),
            "expectancy_r": round(float(np.mean([x.r_multiple for x in values])), 3),
        }
        for key, values in sorted(groups.items())
    }


def bootstrap_intervals(trades: list[Trade], samples: int = 1000, seed: int = 42) -> dict:
    """Non-parametric trade bootstrap. Deterministic seed makes reports reproducible."""
    if len(trades) < 5:
        return {"status": "insufficient sample (<5 trades)", "samples": 0}
    pnl = np.asarray([t.net_pnl for t in trades], dtype=float)
    r = np.asarray([t.r_multiple for t in trades], dtype=float)
    wins = (pnl > 0).astype(float)
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(trades), size=(samples, len(trades)))
    total = pnl[indices].sum(axis=1)
    expectancy = r[indices].mean(axis=1)
    win_rate = wins[indices].mean(axis=1) * 100

    def ci(x):
        return [round(float(np.percentile(x, 2.5)), 4), round(float(np.percentile(x, 97.5)), 4)]
    return {
        "status": "percentile 95% trade-bootstrap CI (serial dependence not modelled)",
        "samples": samples, "seed": seed,
        "net_pnl": ci(total), "expectancy_r": ci(expectancy), "win_rate_pct": ci(win_rate),
    }


def calculate_metrics(result: BacktestResult, benchmark: pd.DataFrame | pd.Series | None = None,
                      bootstrap_samples: int = 1000) -> dict:
    trades = result.trades
    n = len(trades)
    pnl = np.asarray([x.net_pnl for x in trades], dtype=float)
    r_mult = np.asarray([x.r_multiple for x in trades], dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]
    gross_profit = float(wins.sum()) if len(wins) else 0.0
    gross_loss = abs(float(losses.sum())) if len(losses) else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    curve = result.equity_curve
    if len(curve):
        eq = curve["equity"].astype(float)
        daily = eq.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna()
        peak = eq.cummax()
        # Report drawdown as a positive loss magnitude (e.g. 12.1%), matching
        # common portfolio reporting and the acceptance threshold semantics.
        max_drawdown = abs(float((eq / peak - 1).min() * 100))
        periods = max(1, len(eq) - 1)
        years = periods / 252
        total_return = result.final_equity / result.initial_capital - 1
        cagr = (result.final_equity / result.initial_capital) ** (1 / years) - 1 if years >= 0.5 and result.final_equity > 0 else None
        vol = float(daily.std(ddof=1)) if len(daily) > 1 else 0.0
        sharpe = float(daily.mean() / vol * math.sqrt(252)) if vol > 1e-12 else None
        downside = daily[daily < 0]
        downside_dev = float(np.sqrt(np.mean(np.square(downside)))) if len(downside) else 0.0
        sortino = float(daily.mean() / downside_dev * math.sqrt(252)) if downside_dev > 1e-12 else None
        exposure = float(curve["exposed"].astype(bool).mean() * 100)
    else:
        total_return = 0.0; cagr = None; max_drawdown = 0.0; sharpe = None; sortino = None; exposure = 0.0
    benchmark_return = None
    if benchmark is not None and len(curve):
        series = benchmark["Close"] if isinstance(benchmark, pd.DataFrame) else benchmark
        series = series.loc[curve.index.min():curve.index.max()].dropna()
        if len(series) >= 2 and float(series.iloc[0]) > 0:
            benchmark_return = float(series.iloc[-1] / series.iloc[0] - 1)
    alpha = total_return - benchmark_return if benchmark_return is not None else None
    longest = streak = 0
    for value in pnl:
        streak = streak + 1 if value <= 0 else 0
        longest = max(longest, streak)
    turnover_value = sum(f.price * f.quantity for f in result.fills)
    avg_equity = float(result.equity_curve["equity"].mean()) if len(curve) else result.initial_capital
    return {
        "trades": n,
        "win_rate_pct": round(float((pnl > 0).mean() * 100), 2) if n else 0.0,
        "average_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "average_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else None,
        "profit_factor_note": "infinite (no losing trades)" if math.isinf(profit_factor) else None,
        "expectancy_r": round(float(r_mult.mean()), 3) if n else 0.0,
        "net_total_return_pct": round(total_return * 100, 3),
        "net_pnl": round(result.final_equity - result.initial_capital, 2),
        "cagr_pct": round(cagr * 100, 3) if cagr is not None else None,
        "nifty_return_pct": round(benchmark_return * 100, 3) if benchmark_return is not None else None,
        "nifty_relative_alpha_pct": round(alpha * 100, 3) if alpha is not None else None,
        "max_drawdown_pct": round(max_drawdown, 3),
        "sharpe": _finite(sharpe), "sortino": _finite(sortino),
        "average_holding_sessions": round(float(np.mean([x.holding_sessions for x in trades])), 2) if n else 0.0,
        "turnover_pct": round(turnover_value / avg_equity * 100, 2) if avg_equity > 0 else 0.0,
        "stop_loss_hit_rate_pct": round(sum(x.stop_hit for x in trades) / n * 100, 2) if n else 0.0,
        "gap_loss_frequency_pct": round(sum(x.gap_loss for x in trades) / n * 100, 2) if n else 0.0,
        "longest_losing_streak": longest, "exposure_pct": round(exposure, 2),
        "total_economic_costs": round(sum(x.costs for x in trades), 2),
        "regime_performance": _group(trades, "regime"),
        "setup_performance": _group(trades, "setup"),
        "sector_performance": _group(trades, "sector"),
        "bootstrap": bootstrap_intervals(trades, bootstrap_samples),
    }


@dataclass(frozen=True)
class AcceptanceConfig:
    minimum_trades: int = 50
    minimum_windows: int = 3
    minimum_profit_factor: float = 1.20
    minimum_expectancy_r: float = 0.0
    maximum_drawdown_pct: float = 25.0
    minimum_stocks: int = 3
    minimum_regimes: int = 2
    maximum_stock_trade_share: float = 0.70
    maximum_regime_trade_share: float = 0.80


def acceptance_gate(metrics: dict, walk_forward_windows: int, *, stock_count: int = 1,
                    stock_trade_counts: dict[str, int] | None = None,
                    config: AcceptanceConfig | None = None) -> dict:
    cfg = config or AcceptanceConfig()
    pf = metrics.get("profit_factor")
    regime_counts = {
        key: int(value.get("trades", 0) or 0)
        for key, value in (metrics.get("regime_performance") or {}).items()
        if key != "unavailable" and int(value.get("trades", 0) or 0) > 0
    }
    regimes = len(regime_counts)
    regime_total = sum(regime_counts.values())
    largest_regime_share = (max(regime_counts.values()) / regime_total
                            if regime_total and regime_counts else 1.0)
    supplied_stocks = {k: int(v) for k, v in (stock_trade_counts or {}).items() if int(v) > 0}
    stock_total = sum(supplied_stocks.values())
    largest_stock_share = (max(supplied_stocks.values()) / stock_total
                           if stock_total and supplied_stocks else 1.0)
    verified_stock_count = len(supplied_stocks)
    checks = {
        "minimum_oos_trades": int(metrics.get("trades", 0)) >= cfg.minimum_trades,
        "minimum_test_windows": int(walk_forward_windows) >= cfg.minimum_windows,
        "positive_net_expectancy": float(metrics.get("expectancy_r", 0) or 0) > cfg.minimum_expectancy_r,
        "profit_factor": pf is not None and float(pf) >= cfg.minimum_profit_factor,
        "drawdown_limit": abs(float(metrics.get("max_drawdown_pct", 0) or 0)) <= cfg.maximum_drawdown_pct,
        # A caller-supplied integer alone is not evidence. Per-stock OOS trade
        # counts are mandatory before the universe diversity check can pass.
        "stock_diversity": (int(stock_count) >= cfg.minimum_stocks
                            and verified_stock_count >= cfg.minimum_stocks),
        "stock_count_reconciliation": stock_total == int(metrics.get("trades", 0)),
        "stock_concentration": largest_stock_share <= cfg.maximum_stock_trade_share,
        "regime_diversity": regimes >= cfg.minimum_regimes,
        "regime_count_reconciliation": regime_total == int(metrics.get("trades", 0)),
        "regime_concentration": largest_regime_share <= cfg.maximum_regime_trade_share,
    }
    reasons = [name.replace("_", " ") for name, passed in checks.items() if not passed]
    validated = all(checks.values())
    return {
        "validated_edge": validated,
        "status": "VALIDATED EDGE" if validated else "NO VALIDATED EDGE",
        "checks": checks, "failed_reasons": reasons,
        "thresholds": asdict(cfg), "stock_count": stock_count,
        "verified_stock_count": verified_stock_count, "regime_count": regimes,
        "largest_stock_trade_share": round(largest_stock_share, 4),
        "largest_regime_trade_share": round(largest_regime_share, 4),
        "scope": ("universe-level" if verified_stock_count >= cfg.minimum_stocks
                  else "stock-specific occurrences only"),
    }
