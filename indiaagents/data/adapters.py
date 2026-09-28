"""Extensible OHLCV source contracts for strategy/backtest code.

Strategy modules consume normalized DataFrames and do not know whether bars came
from Yahoo, Alpha Vantage, a future official bhavcopy adapter or a broker API.
No unofficial source is labelled official/reliable here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

import pandas as pd
import yfinance as yf

from indiaagents.strategy.features import normalize_ohlcv


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class DataProvenance:
    source: str
    symbol: str
    fetched_at_utc: str
    adjusted: bool
    rows: int
    start: str | None
    end: str | None
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OHLCVResult:
    data: pd.DataFrame
    provenance: DataProvenance


@runtime_checkable
class OHLCVSource(Protocol):
    name: str

    def fetch(self, symbol: str, start: str, end: str, *, adjusted: bool = True) -> OHLCVResult:
        """Fetch bars where end is inclusive at this interface boundary."""
        ...


class YahooOHLCVSource:
    name = "yahoo"

    def fetch(self, symbol: str, start: str, end: str, *, adjusted: bool = True) -> OHLCVResult:
        exclusive_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        raw = yf.Ticker(symbol).history(start=start, end=exclusive_end, interval="1d",
                                        auto_adjust=adjusted)
        data = normalize_ohlcv(raw)
        data = data[(data.index >= pd.Timestamp(start)) & (data.index <= pd.Timestamp(end))]
        limits = [
            "Yahoo history is a current adjusted-history vintage, not an immutable point-in-time archive",
            "current-universe survivorship, delistings and historical symbol changes are not resolved",
        ]
        if adjusted:
            limits.append("OHLC are split/dividend-adjusted while volume adjustment semantics depend on Yahoo")
        else:
            limits.append("raw OHLC needs explicit split/dividend/bonus processing before long-horizon comparison")
        return OHLCVResult(data, DataProvenance(
            self.name, symbol, _utc_now(),
            adjusted, len(data), data.index[0].date().isoformat() if len(data) else None,
            data.index[-1].date().isoformat() if len(data) else None, limits,
        ))


class AlphaVantageOHLCVSource:
    name = "alpha_vantage"

    def fetch(self, symbol: str, start: str, end: str, *, adjusted: bool = True) -> OHLCVResult:
        from .health import SourceResult
        from .sources import get_alpha_vantage_history
        result = get_alpha_vantage_history(symbol, with_health=True)
        if isinstance(result, SourceResult):
            raw = result.value
            if raw is None:
                raise RuntimeError(
                    f"Alpha Vantage {result.health.status}: {result.health.detail}"
                )
        else:  # third-party/injected legacy adapter
            raw = result
        data = normalize_ohlcv(raw) if raw is not None else normalize_ohlcv(pd.DataFrame(columns=[
            "Open", "High", "Low", "Close", "Volume",
        ]))
        data = data[(data.index >= pd.Timestamp(start)) & (data.index <= pd.Timestamp(end))]
        return OHLCVResult(data, DataProvenance(
            self.name, symbol, _utc_now(),
            False, len(data), data.index[0].date().isoformat() if len(data) else None,
            data.index[-1].date().isoformat() if len(data) else None,
            ["Alpha Vantage fallback is unadjusted daily OHLCV in this project",
             "corporate actions must be handled before strict long-horizon backtesting"],
        ))


class CompositeOHLCVSource:
    """First sufficiently populated source wins; failures are explicit in provenance."""
    name = "composite"

    def __init__(self, sources: list[OHLCVSource] | None = None, minimum_rows: int = 100):
        self.sources = sources or [YahooOHLCVSource(), AlphaVantageOHLCVSource()]
        self.minimum_rows = minimum_rows

    def fetch(self, symbol: str, start: str, end: str, *, adjusted: bool = True) -> OHLCVResult:
        failures: list[str] = []
        best: OHLCVResult | None = None
        for source in self.sources:
            try:
                result = source.fetch(symbol, start, end, adjusted=adjusted)
                if best is None or len(result.data) > len(best.data):
                    best = result
                if len(result.data) >= self.minimum_rows:
                    result.provenance.limitations.extend(failures)
                    return result
                failures.append(f"{source.name}: only {len(result.data)} rows")
            except Exception as exc:  # noqa: BLE001  # failure is recorded, then next adapter is tried
                failures.append(f"{source.name}: {type(exc).__name__}: {str(exc)[:100]}")
        if best is None or best.data.empty:
            raise ValueError(f"No OHLCV source returned data for {symbol}: {'; '.join(failures)}")
        best.provenance.limitations.extend(failures)
        return best


def fetch_strategy_history(symbol: str, years: int = 10, *, end: str | None = None,
                           adjusted: bool = True,
                           source: OHLCVSource | None = None) -> OHLCVResult:
    end_ts = pd.Timestamp(end or datetime.now(UTC).date().isoformat())
    start = (end_ts - pd.Timedelta(days=max(1, years) * 366)).date().isoformat()
    return (source or CompositeOHLCVSource()).fetch(
        symbol, start, end_ts.date().isoformat(), adjusted=adjusted,
    )


class OfficialBhavcopySource(Protocol):
    """Future extension point; no fake implementation is supplied."""
    name: str
    def fetch(self, symbol: str, start: str, end: str, *, adjusted: bool = True) -> OHLCVResult: ...


class BrokerOHLCVSource(Protocol):
    """Future authenticated broker adapter contract; secrets stay outside code."""
    name: str
    def fetch(self, symbol: str, start: str, end: str, *, adjusted: bool = True) -> OHLCVResult: ...
