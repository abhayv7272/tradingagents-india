"""Transparent Indian cash-equity transaction-cost assumptions.

Defaults approximate NSE delivery trades and are deliberately configurable.
Broker/exchange schedules and tax law change; users must update these values for
actual broker invoices.  Rates are percentages of turnover, not basis points.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class IndiaCostConfig:
    brokerage_pct: float = 0.03
    brokerage_cap_per_order: float = 20.0
    stt_buy_pct: float = 0.10
    stt_sell_pct: float = 0.10
    exchange_pct: float = 0.00297
    sebi_pct: float = 0.00010
    gst_pct: float = 18.0
    stamp_buy_pct: float = 0.015
    slippage_bps: float = 5.0
    impact_bps: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CostBreakdown:
    turnover: float
    brokerage: float
    stt: float
    exchange: float
    sebi: float
    gst: float
    stamp: float
    cash_charges: float
    slippage_impact: float
    economic_cost: float

    def to_dict(self) -> dict:
        return asdict(self)


def execution_price(raw_price: float, side: str, config: IndiaCostConfig) -> tuple[float, float]:
    rate = (config.slippage_bps + config.impact_bps) / 10_000
    sign = 1 if side.upper() == "BUY" else -1
    adjusted = float(raw_price) * (1 + sign * rate)
    amount_per_share = abs(adjusted - float(raw_price))
    return adjusted, amount_per_share


def transaction_cost(price: float, quantity: int, side: str, config: IndiaCostConfig,
                     slippage_impact: float = 0.0) -> CostBreakdown:
    turnover = max(0.0, float(price) * max(0, int(quantity)))
    brokerage = min(turnover * config.brokerage_pct / 100,
                    config.brokerage_cap_per_order) if config.brokerage_pct > 0 else 0.0
    stt_rate = config.stt_buy_pct if side.upper() == "BUY" else config.stt_sell_pct
    stt = turnover * stt_rate / 100
    exchange = turnover * config.exchange_pct / 100
    sebi = turnover * config.sebi_pct / 100
    gst = (brokerage + exchange + sebi) * config.gst_pct / 100
    stamp = turnover * config.stamp_buy_pct / 100 if side.upper() == "BUY" else 0.0
    cash = brokerage + stt + exchange + sebi + gst + stamp
    return CostBreakdown(
        round(turnover, 6), round(brokerage, 6), round(stt, 6), round(exchange, 6),
        round(sebi, 6), round(gst, 6), round(stamp, 6), round(cash, 6),
        round(slippage_impact, 6), round(cash + slippage_impact, 6),
    )
