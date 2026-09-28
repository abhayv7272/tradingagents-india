"""Typed contracts for deterministic strategy decisions.

The strategy layer intentionally contains no LLM/provider types.  Dataclasses are
used instead of a validation framework so Streamlit Cloud keeps a small runtime.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DetailedAction(str, Enum):
    ENTER = "ENTER"
    ADD = "ADD"
    HOLD = "HOLD"
    WAIT = "WAIT"
    TRIM = "TRIM"
    EXIT = "EXIT"
    REVIEW = "REVIEW"


class SignalState(str, Enum):
    ACTIVE = "ACTIVE"
    WAITING = "WAITING"
    INVALID = "INVALID"


@dataclass(frozen=True)
class PortfolioInputs:
    existing_holding: bool = False
    average_buy_price: float | None = None
    current_quantity: int = 0
    portfolio_capital: float = 100_000.0
    max_risk_pct: float = 1.0
    max_single_stock_pct: float = 20.0
    horizon: str = "positional"  # swing | positional | long-term
    risk_profile: str = "balanced"  # conservative | balanced | aggressive

    def validated(self) -> PortfolioInputs:
        horizon = self.horizon if self.horizon in {"swing", "positional", "long-term"} else "positional"
        profile = self.risk_profile if self.risk_profile in {"conservative", "balanced", "aggressive"} else "balanced"
        capital = max(0.0, float(self.portfolio_capital or 0.0))
        risk = min(2.0, max(0.1, float(self.max_risk_pct or 1.0)))
        allocation = min(30.0, max(1.0, float(self.max_single_stock_pct or 20.0)))
        quantity = max(0, int(self.current_quantity or 0))
        average = self.average_buy_price
        average = float(average) if average is not None and float(average) > 0 else None
        holding = bool(self.existing_holding or quantity > 0)
        return PortfolioInputs(holding, average, quantity, capital, risk, allocation, horizon, profile)


@dataclass(frozen=True)
class StrategyConfig:
    pivot_left: int = 3
    pivot_right: int = 3
    zone_atr_tolerance: float = 0.35
    breakout_volume_ratio: float = 1.5
    min_stop_atr: float = 1.0
    stop_atr_buffer: float = 0.25
    max_stop_distance_pct: float = 12.0
    min_reward_risk: float = 1.5
    trailing_atr: float = 2.0
    time_stop_sessions: int = 30
    event_review_days: int = 7
    minimum_history: int = 220
    stale_calendar_days: int = 7
    liquidity_participation_pct: float = 1.0
    require_validated_edge: bool = True

    def validated(self) -> StrategyConfig:
        return StrategyConfig(
            pivot_left=max(1, min(10, int(self.pivot_left))),
            pivot_right=max(1, min(10, int(self.pivot_right))),
            zone_atr_tolerance=max(0.05, min(1.5, float(self.zone_atr_tolerance))),
            breakout_volume_ratio=max(1.0, min(4.0, float(self.breakout_volume_ratio))),
            min_stop_atr=max(0.5, min(3.0, float(self.min_stop_atr))),
            stop_atr_buffer=max(0.0, min(1.0, float(self.stop_atr_buffer))),
            max_stop_distance_pct=max(3.0, min(25.0, float(self.max_stop_distance_pct))),
            min_reward_risk=max(1.0, min(4.0, float(self.min_reward_risk))),
            trailing_atr=max(1.0, min(5.0, float(self.trailing_atr))),
            time_stop_sessions=max(5, min(252, int(self.time_stop_sessions))),
            event_review_days=max(0, min(30, int(self.event_review_days))),
            minimum_history=max(100, min(500, int(self.minimum_history))),
            stale_calendar_days=max(2, min(30, int(self.stale_calendar_days))),
            liquidity_participation_pct=max(0.01, min(5.0, float(self.liquidity_participation_pct))),
            require_validated_edge=bool(self.require_validated_edge),
        )


@dataclass(frozen=True)
class PriceZone:
    low: float
    high: float
    kind: str
    touches: int = 1
    last_touch: str | None = None
    source: str = "confirmed_pivot"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StrategyEvidence:
    status: str = "BACKTEST NOT AVAILABLE"
    validated_edge: bool = False
    trades: int = 0
    walk_forward_windows: int = 0
    profit_factor: float | None = None
    expectancy_r: float | None = None
    max_drawdown_pct: float | None = None
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeterministicPlan:
    as_of: str
    action: DetailedAction
    legacy_action: str
    setup_name: str
    signal_state: SignalState
    trigger: str
    trigger_price: float | None
    entry_zone: PriceZone | None
    confirmations: list[str]
    missing_confirmations: list[str]
    invalidation: str
    initial_stop: float | None
    stop_reason: str
    target_1: float | None
    target_2: float | None
    reward_risk: float | None
    quantity: int
    allocation_rupees: float
    allocation_pct: float
    max_loss_rupees: float
    max_portfolio_loss_pct: float
    trailing_rule: str
    early_exit_rules: list[str]
    time_stop_sessions: int
    support_zones: list[PriceZone] = field(default_factory=list)
    resistance_zones: list[PriceZone] = field(default_factory=list)
    relative_strength: dict[str, Any] = field(default_factory=dict)
    weekly: dict[str, Any] = field(default_factory=dict)
    daily: dict[str, Any] = field(default_factory=dict)
    deterministic_reasons: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    evidence: StrategyEvidence = field(default_factory=StrategyEvidence)
    config_version: str = "deterministic-v1"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["action"] = self.action.value
        data["signal_state"] = self.signal_state.value
        return data
