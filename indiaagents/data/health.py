"""Structured provider health and provenance helpers.

Data adapters in this project intentionally keep their legacy return values, but
also attach these records to pipeline output.  A missing payload must never be
silently presented as evidence that a market event did not occur.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Generic, TypeVar

import requests

T = TypeVar("T")
IST = timezone(timedelta(hours=5, minutes=30))


def india_today() -> date:
    """Current exchange-local calendar date (never the server's UTC date)."""
    return datetime.now(IST).date()


# ``suppressed`` means a current-only endpoint was deliberately not queried for
# a historical/PIT run.  It is different from a provider returning no rows.
SOURCE_STATUSES = frozenset({
    "available", "stale", "empty", "unconfigured", "network-blocked",
    "rate-limited", "parse-failed", "suppressed",
})


@dataclass(frozen=True)
class SourceHealth:
    source: str
    category: str
    status: str
    detail: str = ""
    rows: int | None = None
    as_of: str | None = None
    fetched_at_utc: str | None = None
    cached: bool = False

    def __post_init__(self) -> None:
        if self.status not in SOURCE_STATUSES:
            raise ValueError(f"Unsupported source status: {self.status}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class SourceResult(Generic[T]):
    value: T
    health: SourceHealth


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def health(source: str, category: str, status: str, detail: str = "", *,
           rows: int | None = None, as_of: str | None = None,
           cached: bool = False) -> SourceHealth:
    """Build a status without allowing credentials/URLs into diagnostics."""
    return SourceHealth(
        source=source,
        category=category,
        status=status,
        detail=str(detail)[:240],
        rows=rows,
        as_of=as_of,
        fetched_at_utc=utc_now(),
        cached=cached,
    )


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map transport/provider failures to a stable, secret-safe status.

    Exception messages are deliberately not copied: request URLs can contain an
    API key.  Type and HTTP status are enough for operator diagnostics.
    """
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return "rate-limited", "provider returned HTTP 429"
    if status_code in (401, 403, 451):
        return "network-blocked", f"provider denied access (HTTP {status_code})"
    if isinstance(exc, (requests.exceptions.SSLError,
                        requests.exceptions.ConnectionError,
                        requests.exceptions.Timeout,
                        TimeoutError, ConnectionError, OSError)):
        return "network-blocked", f"transport failure ({type(exc).__name__})"
    if status_code is not None:
        return "empty", f"provider returned HTTP {status_code}"
    return "parse-failed", f"adapter failure ({type(exc).__name__})"


_STATUS_PRIORITY = {
    "available": 0,
    "suppressed": 1,
    "empty": 2,
    "stale": 3,
    "unconfigured": 4,
    "parse-failed": 5,
    "network-blocked": 6,
    "rate-limited": 7,
}


def aggregate_health(source: str, category: str, records: list[SourceHealth], *,
                     rows: int | None = None, detail: str = "") -> SourceHealth:
    """Combine several requests for one logical feed.

    Any usable response makes the logical feed available.  If none is usable,
    the most actionable failure wins (rate limit > network > parse > config >
    empty).  Individual records should still be retained by callers.
    """
    if not records:
        return health(source, category, "empty", detail or "no requests attempted", rows=rows)
    usable = [r for r in records if r.status in ("available", "stale")]
    if usable:
        status = "available" if any(r.status == "available" for r in usable) else "stale"
    else:
        status = max(records, key=lambda r: _STATUS_PRIORITY[r.status]).status
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    count_text = ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
    if not detail:
        detail = count_text
    elif not usable:
        detail = f"{detail}; {count_text}"
    return health(
        source, category, status, detail, rows=rows,
        cached=bool(records) and all(record.cached for record in records),
    )


def health_dicts(*collections: Any) -> list[dict]:
    """Flatten SourceHealth/dict/list inputs into JSON-safe records."""
    out: list[dict] = []
    for collection in collections:
        if collection is None:
            continue
        values = collection if isinstance(collection, (list, tuple)) else [collection]
        for value in values:
            if isinstance(value, SourceHealth):
                out.append(value.to_dict())
            elif isinstance(value, dict) and value.get("source") and value.get("status"):
                out.append(dict(value))
    return out


def source_summary(records: list[dict]) -> str:
    """Compact status line for CLI/UI; full records remain in the report."""
    if not records:
        return "no source diagnostics"
    # Preserve category-level records while removing exact duplicates.
    seen: set[tuple] = set()
    parts: list[str] = []
    icons = {"available": "✓", "stale": "⚠", "suppressed": "↷"}
    for record in records:
        key = (record.get("source"), record.get("category"), record.get("status"))
        if key in seen:
            continue
        seen.add(key)
        status = str(record.get("status") or "empty")
        icon = icons.get(status, "✗")
        parts.append(f"{record.get('source', '?')} {icon} {status}")
    return " | ".join(parts)
