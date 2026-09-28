"""Deterministic multi-timeframe long-side strategy engine.

All levels, actions and sizes originate here.  An LLM may explain the returned
plan, but cannot modify it in the pipeline/report contracts.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pandas as pd

from .features import daily_features, finite_or_none, normalize_ohlcv, weekly_features
from .levels import (
    ConfirmedPivot,
    breakout_retest_state,
    build_level_context,
    confirmed_pivots,
)
from .relative_strength import relative_strength
from .schemas import (
    DetailedAction,
    DeterministicPlan,
    PortfolioInputs,
    PriceZone,
    SignalState,
    StrategyConfig,
    StrategyEvidence,
)


@dataclass
class PreparedStrategyData:
    stock: pd.DataFrame
    daily: pd.DataFrame
    weekly: pd.DataFrame
    pivots: list[ConfirmedPivot]
    nifty: pd.DataFrame | None = None
    sector: pd.DataFrame | None = None
    peer: pd.DataFrame | None = None
    sector_symbol: str | None = None


@dataclass
class _Candidate:
    name: str
    active: bool
    trigger_price: float
    confirmations: list[str]
    missing: list[str]
    invalidation: str
    entry_style: str = "breakout"
    allocation_cap: float | None = None


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _fmt(price: float | None) -> str:
    return "unavailable" if price is None else f"₹{price:,.2f}"


def _evidence(value: StrategyEvidence | dict | None) -> StrategyEvidence:
    if isinstance(value, StrategyEvidence):
        return value
    if not value:
        return StrategyEvidence()
    fields = StrategyEvidence.__dataclass_fields__
    return StrategyEvidence(**{k: v for k, v in value.items() if k in fields})


class DeterministicStrategyEngine:
    def __init__(self, config: StrategyConfig | None = None):
        self.config = (config or StrategyConfig()).validated()

    def prepare(self, stock: pd.DataFrame, nifty: pd.DataFrame | None = None,
                sector: pd.DataFrame | None = None, peer: pd.DataFrame | None = None,
                sector_symbol: str | None = None) -> PreparedStrategyData:
        d = normalize_ohlcv(stock)
        daily = daily_features(d)
        weekly = weekly_features(d, d.index[-1] if len(d) else None)
        pivots = confirmed_pivots(d, self.config.pivot_left, self.config.pivot_right)
        if len(weekly):
            pivots.extend(confirmed_pivots(weekly, 2, 2, timeframe="weekly"))
        return PreparedStrategyData(
            d, daily, weekly, pivots,
            normalize_ohlcv(nifty) if nifty is not None and not nifty.empty else None,
            normalize_ohlcv(sector) if sector is not None and not sector.empty else None,
            normalize_ohlcv(peer) if peer is not None and not peer.empty else None,
            sector_symbol,
        )

    def analyze(self, stock: pd.DataFrame, *, as_of: str | pd.Timestamp | None = None,
                portfolio: PortfolioInputs | None = None,
                nifty: pd.DataFrame | None = None, sector: pd.DataFrame | None = None,
                peer: pd.DataFrame | None = None, sector_symbol: str | None = None,
                evidence: StrategyEvidence | dict | None = None,
                data_limitations: list[str] | None = None,
                event_date: str | pd.Timestamp | None = None) -> DeterministicPlan:
        prepared = self.prepare(stock, nifty, sector, peer, sector_symbol)
        return self.on_date(prepared, as_of=as_of, portfolio=portfolio,
                            evidence=evidence, data_limitations=data_limitations,
                            event_date=event_date)

    def on_date(self, prepared: PreparedStrategyData, *,
                as_of: str | pd.Timestamp | None = None,
                portfolio: PortfolioInputs | None = None,
                evidence: StrategyEvidence | dict | None = None,
                data_limitations: list[str] | None = None,
                event_date: str | pd.Timestamp | None = None) -> DeterministicPlan:
        cfg = self.config
        p = (portfolio or PortfolioInputs()).validated()
        cutoff = pd.Timestamp(as_of) if as_of is not None else prepared.stock.index[-1]
        d = prepared.stock.loc[:cutoff]
        f = prepared.daily.loc[:cutoff]
        w = prepared.weekly.loc[:cutoff]
        ev = _evidence(evidence)
        limitations = list(data_limitations or [])
        if d.empty:
            raise ValueError("No OHLCV bar is available on/before analysis date")
        actual_date = d.index[-1]
        if len(d) < cfg.minimum_history:
            limitations.append(f"only {len(d)} sessions; minimum {cfg.minimum_history} required")
        stale = max(0, (cutoff.date() - actual_date.date()).days)
        if stale > cfg.stale_calendar_days:
            limitations.append(f"last bar is {stale} calendar days stale")
        event_imminent = False
        if event_date is not None:
            try:
                event_gap = (pd.Timestamp(event_date).date() - cutoff.date()).days
                event_imminent = 0 <= event_gap <= cfg.event_review_days
                if event_imminent:
                    limitations.append(
                        f"known results/event in {event_gap} days ({pd.Timestamp(event_date).date().isoformat()}); REVIEW required"
                    )
            except (TypeError, ValueError):
                limitations.append("event date could not be validated")

        row = f.loc[actual_date]
        weekly_row = w.iloc[-1] if len(w) else pd.Series(dtype=object)
        weekly_state = str(weekly_row.get("trend_state", "unavailable"))
        levels = build_level_context(
            d, actual_date, left=cfg.pivot_left, right=cfg.pivot_right,
            atr_tolerance=cfg.zone_atr_tolerance, pivots=prepared.pivots,
        )
        atr = float(row.get("atr14")) if pd.notna(row.get("atr14")) else float(levels["atr"])
        current = float(row["Close"])
        nifty = prepared.nifty.loc[:actual_date] if prepared.nifty is not None else None
        sector = prepared.sector.loc[:actual_date] if prepared.sector is not None else None
        peer = prepared.peer.loc[:actual_date] if prepared.peer is not None else None
        rs = relative_strength(d, nifty, sector, prepared.sector_symbol, peer)
        if rs["nifty"]["status"] == "unavailable":
            limitations.append("NIFTY relative strength unavailable")
        if rs["sector"]["status"] == "unavailable":
            limitations.append("sector relative strength unavailable; no sector confirmation fabricated")

        up_daily = (
            pd.notna(row.get("sma50")) and current > float(row["ema20"])
            and current > float(row["sma50"])
            and float(row.get("trend_slope20", 0)) > 0
        )
        volume_ok = float(row.get("volume_ratio", 0) or 0) >= cfg.breakout_volume_ratio
        nifty_positive = rs["nifty"].get("trend") == "positive"
        sector_status = rs["sector"].get("status")
        sector_positive = sector_status == "unavailable" or rs["sector"].get("trend") == "positive"
        rs_ok = nifty_positive and sector_positive
        prior55 = finite_or_none(row.get("prior_high55"), 2) or current
        prior20 = finite_or_none(row.get("prior_high20"), 2) or current
        retest = breakout_retest_state(f, actual_date)

        candidates: list[_Candidate] = []
        candidates.append(self._candidate(
            "Weekly-trend breakout", prior55,
            [
                (weekly_state == "positive", "positive completed-week trend"),
                (up_daily, "daily trend confirmation"),
                (_truth(row.get("breakout55")), "close above prior 55-session high"),
                (volume_ok, f"volume ≥{cfg.breakout_volume_ratio:.1f}x 20-day average"),
                (nifty_positive, "positive stock-vs-NIFTY relative strength"),
                (sector_positive, "positive sector RS (or explicitly unavailable)"),
            ],
            "daily close back below breakout level or confirmed support",
        ))
        candidates.append(self._candidate(
            "Breakout retest", float(retest.get("level") or prior55),
            [
                (weekly_state == "positive", "positive completed-week trend"),
                (bool(retest.get("confirmed_breakout")), "prior breakout confirmed after close"),
                (bool(retest.get("retest")), "former resistance retested and bullish reversal closed"),
                (rs_ok, "positive benchmark/available-sector relative strength"),
            ],
            "close below former resistance/retest support", entry_style="pullback",
        ))
        near_ema = (
            abs(current - float(row.get("ema20", current))) <= max(atr * 0.6, current * 0.01)
            or abs(current - float(row.get("sma50", current))) <= max(atr * 0.6, current * 0.01)
            or any(float(row["Low"]) <= z.high + atr * 0.25 for z in levels["supports"][:2])
        )
        selling_contracts = float(row.get("volume_ratio", 9) or 9) <= 0.9
        candidates.append(self._candidate(
            "Trend pullback", current,
            [
                (weekly_state == "positive", "positive completed-week trend"),
                (up_daily, "daily uptrend intact"),
                (near_ema, "pullback reached EMA/SMA or confirmed support"),
                (selling_contracts, "selling volume ≤0.9x 20-day average"),
                (_truth(row.get("bullish_reversal")), "bullish daily reversal closed"),
                (rs_ok, "positive benchmark/available-sector relative strength"),
            ],
            "close below pullback support or 50-day average", entry_style="pullback",
        ))
        contraction_recent = bool(f["volatility_contraction"].tail(10).fillna(False).any())
        range_tight = float(row.get("range20_pct", 9) or 9) <= 0.15
        range_volume = float(row.get("volume_ratio", 0) or 0) >= max(1.3, cfg.breakout_volume_ratio - 0.2)
        candidates.append(self._candidate(
            "Range breakout / volatility contraction", prior20,
            [
                (contraction_recent, "volatility contraction occurred in prior 10 sessions"),
                (range_tight, "prior 20-session range ≤15%"),
                (_truth(row.get("breakout20")), "close above prior 20-session range"),
                (range_volume, "breakout volume confirmation"),
                (nifty_positive, "positive stock-vs-NIFTY relative strength"),
            ],
            "close back inside the prior range",
        ))
        bottoming = self._bottoming_regime(f)
        rsi_recovery = bool((f["rsi14"].tail(10) < 35).any() and float(row.get("rsi14", 0)) > 35)
        higher_low = len(f) >= 12 and float(f["Low"].tail(5).min()) > float(f["Low"].iloc[-12:-5].min())
        candidates.append(self._candidate(
            "Bottoming reversal probe", current,
            [
                (bottoming, "deterministic bottoming regime"),
                (rsi_recovery, "RSI recovered after a sub-35 reading"),
                (float(row.get("macd_hist", 0)) > 0, "MACD histogram positive"),
                (higher_low, "confirmed short-term higher low"),
                (_truth(row.get("bullish_reversal")), "bullish reversal candle closed"),
                (float(row.get("volume_ratio", 0) or 0) >= 1.2, "reversal volume ≥1.2x"),
            ],
            "close below the reversal swing low", entry_style="pullback", allocation_cap=5.0,
        ))

        active = [c for c in candidates if c.active]
        chosen = active[0] if active else max(candidates, key=lambda c: len(c.confirmations))
        state = SignalState.ACTIVE if chosen.active else SignalState.WAITING
        entry_zone = self._entry_zone(chosen, current, atr)
        stop, stop_reason, stop_valid = self._stop(entry_zone, chosen, levels["supports"], atr)
        t1, t2, rr = self._targets(entry_zone, stop, levels["resistances"])
        if not stop_valid or rr is None or rr < cfg.min_reward_risk:
            state = SignalState.INVALID if chosen.active else SignalState.WAITING
            chosen.missing.append("valid structure stop / minimum reward:risk unavailable")

        quantity, allocation, allocation_pct, max_loss, portfolio_loss_pct = self._size(
            entry_zone, stop, d, p, chosen,
        )
        if quantity <= 0:
            chosen.missing.append("risk/allocation/liquidity limits produce zero valid quantity")
            if state == SignalState.ACTIVE:
                state = SignalState.INVALID

        action, reasons = self._action(
            p, chosen, state, ev, limitations, row, weekly_state, rs, retest,
            current, allocation_pct, event_imminent,
        )
        # Quantity means the quantity to transact for the primary action.  WAIT
        # intentionally keeps prospective sizing; HOLD/REVIEW place no order,
        # while TRIM/EXIT report the actual deterministic reduction quantity.
        if action == DetailedAction.EXIT:
            quantity = p.current_quantity
            allocation = quantity * current
            allocation_pct = allocation / p.portfolio_capital * 100 if p.portfolio_capital else 0.0
            max_loss = portfolio_loss_pct = 0.0
        elif action == DetailedAction.TRIM:
            quantity = max(1, p.current_quantity // 2) if p.current_quantity else 0
            allocation = quantity * current
            allocation_pct = allocation / p.portfolio_capital * 100 if p.portfolio_capital else 0.0
            max_loss = portfolio_loss_pct = 0.0
        elif action in {DetailedAction.HOLD, DetailedAction.REVIEW}:
            quantity = 0
            allocation = allocation_pct = max_loss = portfolio_loss_pct = 0.0
        legacy = "BUY" if action in {DetailedAction.ENTER, DetailedAction.ADD} else (
            "SELL" if action in {DetailedAction.TRIM, DetailedAction.EXIT} else "HOLD"
        )
        trigger = self._trigger_text(chosen, rs, cfg)
        daily_summary = {
            "close": round(current, 2), "ema10": finite_or_none(row.get("ema10"), 2),
            "ema20": finite_or_none(row.get("ema20"), 2), "sma20": finite_or_none(row.get("sma20"), 2),
            "sma50": finite_or_none(row.get("sma50"), 2), "sma200": finite_or_none(row.get("sma200"), 2),
            "rsi14": finite_or_none(row.get("rsi14"), 1), "macd": finite_or_none(row.get("macd"), 2),
            "macd_hist": finite_or_none(row.get("macd_hist"), 2), "atr14": round(atr, 2),
            "bollinger_width_pct": finite_or_none(float(row.get("boll_width", 0)) * 100, 2),
            "volume_ratio": finite_or_none(row.get("volume_ratio"), 2),
            "volatility_state": "contraction" if _truth(row.get("volatility_contraction")) else
                                "expansion" if _truth(row.get("volatility_expansion")) else "normal",
            "gap_pct": finite_or_none(row.get("gap_pct"), 2),
            "breakout20": _truth(row.get("breakout20")), "breakout55": _truth(row.get("breakout55")),
            "drawdown_pct": finite_or_none(float(row.get("drawdown252", 0)) * 100, 2),
            "trend_slope20": finite_or_none(row.get("trend_slope20"), 5),
        }
        horizon_time_stop = {
            "swing": max(5, cfg.time_stop_sessions // 2),
            "positional": cfg.time_stop_sessions,
            "long-term": min(252, cfg.time_stop_sessions * 2),
        }[p.horizon]
        weekly_summary = {
            "through": w.index[-1].date().isoformat() if len(w) else None,
            "close": finite_or_none(weekly_row.get("Close"), 2),
            "sma10": finite_or_none(weekly_row.get("sma10"), 2),
            "sma20": finite_or_none(weekly_row.get("sma20"), 2),
            "sma40": finite_or_none(weekly_row.get("sma40"), 2),
            "sma20_slope": finite_or_none(weekly_row.get("sma20_slope"), 5),
            "rsi14": finite_or_none(weekly_row.get("rsi14"), 1),
            "macd": finite_or_none(weekly_row.get("macd"), 2),
            "macd_hist": finite_or_none(weekly_row.get("macd_hist"), 2),
            "trend_state": weekly_state,
            "major_swing_high": self._latest_pivot(prepared.pivots, cutoff, "high", "weekly"),
            "major_swing_low": self._latest_pivot(prepared.pivots, cutoff, "low", "weekly"),
        }
        return DeterministicPlan(
            as_of=actual_date.date().isoformat(), action=action, legacy_action=legacy,
            setup_name=chosen.name, signal_state=state, trigger=trigger,
            trigger_price=round(chosen.trigger_price, 2), entry_zone=entry_zone,
            confirmations=chosen.confirmations, missing_confirmations=chosen.missing,
            invalidation=chosen.invalidation, initial_stop=stop, stop_reason=stop_reason,
            target_1=t1, target_2=t2, reward_risk=rr, quantity=quantity,
            allocation_rupees=round(allocation, 2), allocation_pct=round(allocation_pct, 2),
            max_loss_rupees=round(max_loss, 2),
            max_portfolio_loss_pct=round(portfolio_loss_pct, 3),
            trailing_rule=f"highest close minus {cfg.trailing_atr:g} ATR; raised after close, effective next session",
            early_exit_rules=[
                "partial exit: sell 50% at T1; manage remainder toward T2",
                "failed breakout: close back below breakout level",
                "trend break: close below 50-SMA with negative completed-week trend",
                "relative-strength breakdown: 3M relative return and slope both negative",
                "gap through stop: exit at next available open, not the stale stop price",
                "event/results uncertainty: REVIEW; no automatic fresh entry",
            ],
            time_stop_sessions=horizon_time_stop,
            support_zones=levels["supports"], resistance_zones=levels["resistances"],
            relative_strength=rs, weekly=weekly_summary, daily=daily_summary,
            deterministic_reasons=reasons, limitations=list(dict.fromkeys(limitations)), evidence=ev,
        )

    @staticmethod
    def _candidate(name: str, trigger: float, requirements: list[tuple[bool, str]],
                   invalidation: str, entry_style: str = "breakout",
                   allocation_cap: float | None = None) -> _Candidate:
        confirmations = [text for ok, text in requirements if ok]
        missing = [text for ok, text in requirements if not ok]
        return _Candidate(name, not missing, float(trigger), confirmations, missing,
                          invalidation, entry_style, allocation_cap)

    @staticmethod
    def _bottoming_regime(f: pd.DataFrame) -> bool:
        if len(f) < 60:
            return False
        r = f.iloc[-1]
        below_long = pd.notna(r.get("sma200")) and float(r["Close"]) < float(r["sma200"])
        improving = float(r.get("macd_hist", 0)) > float(f["macd_hist"].iloc[-5])
        off_low = float(r["Close"]) > float(f["Low"].tail(20).min()) * 1.03
        return bool(below_long and improving and off_low)

    def _entry_zone(self, candidate: _Candidate, current: float, atr: float) -> PriceZone:
        if candidate.entry_style == "pullback" and candidate.active:
            low = max(0.01, min(current, candidate.trigger_price))
            high = max(low, current + atr * 0.25)
        else:
            low = candidate.trigger_price + atr * 0.05
            high = candidate.trigger_price + atr * 0.50
        return PriceZone(round(low, 2), round(high, 2), "entry", 1, None,
                         "deterministic_trigger_plus_ATR_tolerance")

    def _stop(self, entry: PriceZone, candidate: _Candidate,
              supports: list[PriceZone], atr: float) -> tuple[float | None, str, bool]:
        cfg = self.config
        entry_ref = entry.high  # conservative sizing assumes top of entry zone
        candidates: list[tuple[float, str]] = []
        for z in supports:
            if z.low < entry.low:
                candidates.append((z.low - cfg.stop_atr_buffer * atr,
                                   f"{z.source} support {_fmt(z.low)}–{_fmt(z.high)} minus {cfg.stop_atr_buffer:g} ATR"))
        if candidate.trigger_price < entry.low:
            candidates.append((candidate.trigger_price - cfg.stop_atr_buffer * atr,
                               "setup invalidation/breakout level minus ATR buffer"))
        if candidates:
            # Nearest structural level below entry.  Minimum ATR width is then enforced.
            structural, reason = max((x for x in candidates if x[0] < entry.low), key=lambda x: x[0])
        else:
            return None, "no confirmed support below entry", False
        narrow_floor = entry_ref - cfg.min_stop_atr * atr
        if structural > narrow_floor:
            structural = narrow_floor
            reason += f"; widened to minimum {cfg.min_stop_atr:g} ATR risk"
        stop = round(max(0.01, structural), 2)
        distance = (entry_ref - stop) / entry_ref * 100
        valid = stop < entry.low and 0 < distance <= cfg.max_stop_distance_pct
        if distance > cfg.max_stop_distance_pct:
            reason += f"; {distance:.1f}% exceeds {cfg.max_stop_distance_pct:.1f}% maximum"
        return stop, reason, valid

    def _targets(self, entry: PriceZone, stop: float | None,
                 resistances: list[PriceZone]) -> tuple[float | None, float | None, float | None]:
        if stop is None:
            return None, None, None
        e = entry.high
        risk = e - stop
        if risk <= 0:
            return None, None, None
        valid_res = sorted(z.low for z in resistances if z.low > e + risk * 0.8)
        # T1 never jumps beyond 1R merely because the next chart resistance is
        # distant.  A defensible resistance between 0.8R and 1R may be used;
        # otherwise 1R is the partial-profit level.
        one_r = e + risk
        t1 = min(one_r, valid_res[0]) if valid_res else one_r
        # T2 must preserve minimum economics and remain strictly beyond T1.
        floor = e + max(2.0, self.config.min_reward_risk) * risk
        next_res = [x for x in valid_res if x > t1 + risk * 0.5]
        t2 = max(floor, next_res[0]) if next_res else floor
        if t2 <= t1:  # defensive against unusual future configuration values
            t2 = t1 + risk
        rr = (t2 - e) / risk
        return round(t1, 2), round(t2, 2), round(rr, 2)

    def _size(self, entry: PriceZone, stop: float | None, d: pd.DataFrame,
              p: PortfolioInputs, candidate: _Candidate) -> tuple[int, float, float, float, float]:
        if stop is None or p.portfolio_capital <= 0:
            return 0, 0.0, 0.0, 0.0, 0.0
        e = entry.high
        risk_share = e - stop
        if risk_share <= 0:
            return 0, 0.0, 0.0, 0.0, 0.0
        profile_factor = {"conservative": 0.75, "balanced": 1.0, "aggressive": 1.0}[p.risk_profile]
        risk_budget = p.portfolio_capital * p.max_risk_pct / 100 * profile_factor
        risk_qty = math.floor(risk_budget / risk_share)
        # Existing safe regime caps remain binding.
        try:
            from indiaagents.data.quant import REGIME_BANDS, regime_state
            regime = regime_state(d)
            regime_cap = float(REGIME_BANDS[regime["regime"]][1])
        except Exception:  # noqa: BLE001 - sizing must fail closed if regime code/data fails
            regime_cap = 5.0
        horizon_cap = {"swing": 12.0, "positional": 20.0, "long-term": 20.0}[p.horizon]
        alloc_cap = min(p.max_single_stock_pct, regime_cap, horizon_cap,
                        candidate.allocation_cap if candidate.allocation_cap is not None else 100.0)
        current_value = p.current_quantity * float(d["Close"].iloc[-1]) if p.existing_holding else 0.0
        available_allocation = max(0.0, p.portfolio_capital * alloc_cap / 100 - current_value)
        allocation_qty = math.floor(available_allocation / e)
        median_value = float((d["Close"] * d["Volume"]).tail(20).median())
        liquidity_rupees = median_value * self.config.liquidity_participation_pct / 100
        liquidity_qty = math.floor(liquidity_rupees / e) if median_value > 0 else 0
        qty = max(0, min(risk_qty, allocation_qty, liquidity_qty))
        allocation = qty * e
        loss = qty * risk_share
        return qty, allocation, allocation / p.portfolio_capital * 100, loss, loss / p.portfolio_capital * 100

    def _action(self, p: PortfolioInputs, candidate: _Candidate, state: SignalState,
                evidence: StrategyEvidence, limitations: list[str], row: pd.Series,
                weekly_state: str, rs: dict, retest: dict, current: float,
                prospective_allocation_pct: float,
                event_imminent: bool = False) -> tuple[DetailedAction, list[str]]:
        reasons = [f"{len(candidate.confirmations)} confirmations passed; {len(candidate.missing)} missing"]
        if event_imminent:
            reasons.append("known event/results window blocks automatic position change")
            return DetailedAction.REVIEW, reasons
        critical = any("stale" in x or "only " in x and "sessions" in x for x in limitations)
        if critical:
            reasons.append("critical history/freshness limitation requires human review")
            return DetailedAction.REVIEW, reasons
        n = rs["nifty"]
        rs_break = n.get("3m_pct") is not None and n["3m_pct"] < 0 and (n.get("slope_ann_pct") or 0) < 0
        close = float(row["Close"])
        sma50 = float(row["sma50"]) if pd.notna(row.get("sma50")) else close
        sma200 = float(row["sma200"]) if pd.notna(row.get("sma200")) else close
        if p.existing_holding:
            if ((close < sma200 and weekly_state == "negative")
                    or (bool(retest.get("failed")) and close < sma50 and rs_break)):
                reasons.append("full deterministic exit rule triggered")
                return DetailedAction.EXIT, reasons
            if ((close < sma50 and rs_break)
                    or (weekly_state != "positive" and close < float(row.get("ema20", close)))):
                reasons.append("trend/relative-strength deterioration triggers partial reduction")
                return DetailedAction.TRIM, reasons
            if state == SignalState.ACTIVE and evidence.validated_edge:
                current_value = p.current_quantity * current
                current_pct = current_value / p.portfolio_capital * 100 if p.portfolio_capital else 100
                if current_pct + prospective_allocation_pct <= p.max_single_stock_pct:
                    reasons.append("active validated setup and concentration headroom permit ADD")
                    return DetailedAction.ADD, reasons
            reasons.append("holding remains above hard exit rules; no validated add trigger")
            return DetailedAction.HOLD, reasons
        if state == SignalState.ACTIVE:
            if self.config.require_validated_edge and not evidence.validated_edge:
                reasons.append(f"{evidence.status}: active occurrence is not permission to claim edge")
                return DetailedAction.WAIT, reasons
            reasons.append("active setup, valid levels/size and acceptance gate passed")
            return DetailedAction.ENTER, reasons
        reasons.append("fresh investor has no complete setup; WAIT instead of HOLD")
        return DetailedAction.WAIT, reasons

    @staticmethod
    def _trigger_text(candidate: _Candidate, rs: dict, cfg: StrategyConfig) -> str:
        sector = rs["sector"]
        sector_text = ("sector RS positive" if sector.get("trend") == "positive" else
                       "sector RS unavailable (not assumed positive)" if sector.get("status") == "unavailable"
                       else "sector RS must turn positive")
        if candidate.entry_style == "pullback":
            return (f"Bullish daily reversal must close above {_fmt(candidate.trigger_price)} after support/retest; "
                    f"stock-vs-NIFTY RS positive and {sector_text}.")
        return (f"Daily close above {_fmt(candidate.trigger_price)} with volume ≥"
                f"{cfg.breakout_volume_ratio:.1f}x 20-day average; stock-vs-NIFTY RS positive and {sector_text}.")

    @staticmethod
    def _latest_pivot(pivots: list[ConfirmedPivot], cutoff: pd.Timestamp,
                      kind: str, timeframe: str) -> float | None:
        values = [p for p in pivots if p.kind == kind and p.timeframe == timeframe
                  and p.confirmation_date <= cutoff]
        return round(values[-1].price, 2) if values else None
