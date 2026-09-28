"""Deterministic data-quality and trade-plan guardrails.

LLMs may explain evidence, but source coverage, freshness, numeric R:R and maximum
capital-at-risk are code decisions.  These functions are deliberately provider-free
so they are easy to test and cannot hallucinate.
"""
from __future__ import annotations

import math
import re
from datetime import datetime


def _finite(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def assess_data_quality(*, trade_date: str, market: dict, fundamentals: dict,
                        news: dict, macro_news: dict, social: dict,
                        market_context: dict, fred: dict) -> dict:
    """Return a transparent 0-100 evidence coverage score.

    This is a coverage/freshness score, not a prediction-confidence score.  A low
    value must constrain the final action; a high value does not imply a good trade.
    """
    components: dict[str, int] = {}
    issues: list[str] = []

    df = market.get("df")
    sessions = len(df) if df is not None else 0
    components["price_history"] = 30 if sessions >= 252 else 22 if sessions >= 120 else 10
    if sessions < 200:
        issues.append(f"sirf {sessions} price sessions available")

    stale_days = 999
    try:
        stale_days = (datetime.strptime(trade_date, "%Y-%m-%d").date()
                      - datetime.strptime(market["snapshot"]["date"], "%Y-%m-%d").date()).days
    except (KeyError, TypeError, ValueError):
        issues.append("price-bar date verify nahi hui")
    components["freshness"] = 10 if stale_days <= 4 else 5 if stale_days <= 7 else 0
    if stale_days > 7:
        issues.append(f"price data {stale_days} calendar days stale hai")

    sources = set(market.get("price_sources") or [])
    cross_note = str(market.get("data_quality") or "")
    if "MISMATCH" in cross_note.upper():
        components["price_crosscheck"] = 0
        issues.append("independent price sources mein >2% conflict")
    elif len(sources) >= 2:
        components["price_crosscheck"] = 10
    else:
        components["price_crosscheck"] = 4
        issues.append("price ka independent live cross-check unavailable")

    key = fundamentals.get("key") or {}
    present = sum(_finite(key.get(k)) for k in
                  ("revenue", "net_income", "market_cap", "pe", "pb", "roe", "fcf"))
    components["fundamentals"] = min(15, present * 3)
    if fundamentals.get("screener"):
        components["fundamentals"] += 5
    else:
        issues.append("independent fundamental cross-check unavailable")
    if components["fundamentals"] < 9:
        issues.append("fundamental coverage weak hai")

    n_news = len(news.get("items") or [])
    components["company_news"] = 10 if n_news >= 5 else 6 if n_news else 0
    if not n_news:
        issues.append("company-news feed unavailable/empty")

    has_nifty = bool(market_context.get("nifty"))
    has_macro_news = bool(macro_news.get("items"))
    components["india_macro"] = (5 if has_nifty else 0) + (5 if has_macro_news else 0)
    if not has_nifty:
        issues.append("NIFTY market-context data unavailable")
    if not has_macro_news:
        issues.append("India macro-news feed unavailable/empty")

    social_ok = social.get("source") not in (None, "unavailable") and social.get("count", 0) > 0
    components["sentiment"] = 5 if social_ok else 0
    if not social_ok:
        issues.append("social sentiment unavailable (neutral evidence mat samjho)")

    fred_block = str(fred.get("fred_block") or "").lower()
    fred_ok = bool(fred_block) and "not configured" not in fred_block and "<unavailable" not in fred_block
    components["global_macro"] = 5 if fred_ok else 0
    if not fred_ok:
        issues.append("FRED global macro unavailable")

    score = max(0, min(100, sum(components.values())))
    level = "HIGH" if score >= 80 else "MEDIUM" if score >= 60 else "LOW" if score >= 40 else "CRITICAL"
    hard_block = stale_days > 7 or score < 40 or components["price_history"] < 20
    return {"score": score, "level": level, "components": components,
            "issues": issues, "hard_block": hard_block, "stale_days": stale_days}


def quality_block(quality: dict) -> str:
    parts = " | ".join(f"{k} {v}" for k, v in quality.get("components", {}).items())
    issues = "; ".join(quality.get("issues") or []) or "none"
    return (f"DATA QUALITY (deterministic): {quality['score']}/100 [{quality['level']}]"
            f" | components: {parts}\nLimitations: {issues}\n"
            "Coverage score prediction confidence NAHI hai; low coverage final action ko constrain karta hai.")


def _absolute_level(value) -> float | None:
    """Parse an absolute INR level/range; reject percentage-only relative plans."""
    text = str(value or "").strip()
    if not text or text in {"—", "-"}:
        return None
    if "%" in text and "₹" not in text and "rs" not in text.lower() and "inr" not in text.lower():
        return None
    nums = []
    for raw in re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?", text):
        try:
            number = float(raw.replace(",", ""))
            if number > 0:
                nums.append(number)
        except ValueError:
            continue
    if not nums:
        return None
    # Entry zones are commonly ranges. The midpoint is the least optimistic fill.
    return sum(nums[:2]) / min(2, len(nums))


def apply_trade_guard(decision: dict, current_price: float,
                      max_loss_pct: float = 1.0) -> dict:
    """Validate numeric execution and cap allocation by capital-at-risk.

    Contradictory BUY levels or R:R below 1:1.5 become HOLD. Missing absolute
    levels remain unverified and receive a confidence/size cap rather than being
    silently treated as valid.
    """
    action = str(decision.get("decision") or "HOLD").upper()
    entry = _absolute_level(decision.get("entry_zone"))
    if entry is None and "current" in str(decision.get("entry_zone") or "").lower() and _finite(current_price):
        entry = float(current_price)
    target = _absolute_level(decision.get("target"))
    stop = _absolute_level(decision.get("stop_loss"))
    parsed = {"entry": entry, "target": target, "stop": stop}
    notes: list[str] = []
    rr = None
    valid = True
    verified = all(_finite(x) for x in (entry, target, stop))

    if action == "SELL":
        decision["position_size_pct"] = 0
        notes.append("SELL/exit action ke liye fresh allocation 0% lock")
    elif action == "BUY" and verified:
        risk = entry - stop
        reward = target - entry
        if not (stop < entry < target) or risk <= 0:
            valid = False
            notes.append("BUY levels inconsistent: stop < entry < target hona chahiye")
        else:
            rr = reward / risk
            if rr < 1.5:
                valid = False
                notes.append(f"R:R 1:{rr:.2f} minimum 1:1.50 se kam")
            stop_distance_pct = risk / entry * 100
            if stop_distance_pct > 0:
                risk_capped_size = max(0, int(max_loss_pct / stop_distance_pct * 100))
                old_size = int(decision.get("position_size_pct") or 0)
                if old_size > risk_capped_size:
                    decision["position_size_pct"] = risk_capped_size
                    notes.append(
                        f"capital-at-risk cap: size {old_size}% → {risk_capped_size}% "
                        f"(stop distance {stop_distance_pct:.1f}%, max loss {max_loss_pct:.1f}%)"
                    )
                if risk_capped_size == 0:
                    valid = False
                    notes.append("stop itna wide hai ki 1% risk budget mein minimum 1% allocation bhi fit nahi hota")
    elif action == "BUY":
        verified = False
        old_size = int(decision.get("position_size_pct") or 0)
        decision["position_size_pct"] = min(old_size, 5)
        decision["confidence"] = min(int(decision.get("confidence") or 0), 60)
        notes.append("absolute ₹ entry/target/stop parse nahi hue — plan UNVERIFIED; size/confidence capped")

    if action == "BUY" and not valid:
        decision["decision"] = "HOLD"
        decision["rating"] = "Hold"
        decision["position_size_pct"] = 0
        decision["confidence"] = min(int(decision.get("confidence") or 0), 45)
        notes.append("invalid execution economics ki wajah se BUY → HOLD")

    if notes:
        decision["battle_notes"] = ((decision.get("battle_notes") or "").rstrip()
                                    + " | 🧮 TRADE GUARD: " + "; ".join(notes)).strip(" |")
    decision["trade_validation"] = {
        "verified": verified, "valid": valid, "rr": round(rr, 2) if rr is not None else None,
        "levels": parsed, "max_loss_pct": max_loss_pct, "notes": notes,
    }
    return decision


def apply_quality_guard(decision: dict, quality: dict) -> dict:
    """Constrain confidence/action when evidence coverage is inadequate."""
    score = int(quality.get("score") or 0)
    notes: list[str] = []
    if quality.get("hard_block"):
        old = decision.get("decision")
        decision["decision"] = "HOLD"
        decision["rating"] = "Hold"
        decision["position_size_pct"] = 0
        decision["confidence"] = min(int(decision.get("confidence") or 0), 35)
        notes.append(f"quality {score}/100 hard block: {old} → HOLD, allocation 0%")
    elif score < 60:
        old_size = int(decision.get("position_size_pct") or 0)
        decision["position_size_pct"] = min(old_size, 5)
        decision["confidence"] = min(int(decision.get("confidence") or 0), 55)
        notes.append(f"quality {score}/100: confidence ≤55%, allocation ≤5%")
    elif score < 80:
        decision["confidence"] = min(int(decision.get("confidence") or 0), 75)
        notes.append(f"quality {score}/100: confidence ≤75%")
    if notes:
        decision["battle_notes"] = ((decision.get("battle_notes") or "").rstrip()
                                    + " | 🔌 DATA GUARD: " + "; ".join(notes)).strip(" |")
    decision["data_quality_score"] = score
    decision["data_quality_level"] = quality.get("level", "?")
    return decision
