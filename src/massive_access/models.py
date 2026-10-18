"""Typed models for Massive REST API payloads.

These are thin, immutable wrappers over the documented JSON shapes — no
resampling, adjustment, or strategy logic here. Field names map 1:1 to the API
(massive.com/docs/rest/stocks); convenience properties document the units.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

__all__ = [
    "Aggregate",
    "AggregateResponse",
    "Quote",
    "MarketHoliday",
    "MarketStatus",
    "VALID_TIMESPANS",
]

# https://massive.com/docs/rest/stocks/aggregates/custom-bars
VALID_TIMESPANS = ("second", "minute", "hour", "day", "week", "month", "quarter", "year")


@dataclass(frozen=True)
class Aggregate:
    """One aggregate bar from /v2/aggs/ticker/{ticker}/range/...

    ``t`` is milliseconds since epoch (start of the bar's window, UTC).
    """

    t: int
    o: float
    h: float
    l: float  # noqa: E741 -- mirrors the API field name
    c: float
    v: float | None = None
    vw: float | None = None
    n: int | None = None

    @staticmethod
    def from_api(obj: Mapping[str, Any]) -> Aggregate:
        return Aggregate(
            t=int(obj["t"]),
            o=float(obj["o"]),
            h=float(obj["h"]),
            l=float(obj["l"]),
            c=float(obj["c"]),
            v=float(obj["v"]) if obj.get("v") is not None else None,
            vw=float(obj["vw"]) if obj.get("vw") is not None else None,
            n=int(obj["n"]) if obj.get("n") is not None else None,
        )

    @property
    def start_time_utc(self) -> datetime:
        """Bar window start as a tz-aware UTC datetime."""
        return datetime.fromtimestamp(self.t / 1000, tz=UTC)


@dataclass(frozen=True)
class AggregateResponse:
    """Aggregated (all pages merged) result of one aggregates request."""

    ticker: str
    adjusted: bool
    status: str
    results: tuple[Aggregate, ...]
    request_id: str | None = None
    query_count: int | None = None

    @property
    def results_count(self) -> int:
        return len(self.results)


@dataclass(frozen=True)
class Quote:
    """Latest NBBO quote from /v2/last/nbbo/{stocksTicker}.

    Massive field mapping (uppercase = ask side, lowercase = bid side):
    ``P/p`` ask/bid price, ``S/s`` ask/bid size, ``X/x`` ask/bid exchange id,
    ``t`` SIP timestamp (ns since epoch), ``y`` participant timestamp (ns),
    ``q`` sequence number, ``z`` tape.
    """

    ticker: str
    ask_price: float
    ask_size: int
    bid_price: float
    bid_size: int
    ask_exchange: int | None = None
    bid_exchange: int | None = None
    timestamp_ns: int | None = None
    participant_timestamp_ns: int | None = None
    sequence: int | None = None
    tape: int | None = None
    request_id: str | None = None

    @staticmethod
    def from_api(payload: Mapping[str, Any]) -> Quote:
        r = payload["results"]
        return Quote(
            ticker=str(r["T"]),
            ask_price=float(r["P"]),
            ask_size=int(r["S"]),
            bid_price=float(r["p"]),
            bid_size=int(r["s"]),
            ask_exchange=int(r["X"]) if r.get("X") is not None else None,
            bid_exchange=int(r["x"]) if r.get("x") is not None else None,
            timestamp_ns=int(r["t"]) if r.get("t") is not None else None,
            participant_timestamp_ns=int(r["y"]) if r.get("y") is not None else None,
            sequence=int(r["q"]) if r.get("q") is not None else None,
            tape=int(r["z"]) if r.get("z") is not None else None,
        )

    @property
    def timestamp_utc(self) -> datetime | None:
        """SIP timestamp as tz-aware UTC, or None if the API omitted it."""
        if self.timestamp_ns is None:
            return None
        return datetime.fromtimestamp(self.timestamp_ns / 1e9, tz=UTC)


@dataclass(frozen=True)
class MarketStatus:
    """Snapshot of /v1/marketstatus/now."""

    market: str
    server_time: datetime
    after_hours: bool
    early_hours: bool
    exchanges: Mapping[str, str]
    currencies: Mapping[str, str]

    @staticmethod
    def from_api(obj: Mapping[str, Any]) -> MarketStatus:
        return MarketStatus(
            market=str(obj["market"]),
            server_time=datetime.fromisoformat(str(obj["serverTime"])),
            after_hours=bool(obj.get("afterHours", False)),
            early_hours=bool(obj.get("earlyHours", False)),
            exchanges=dict(obj.get("exchanges") or {}),
            currencies=dict(obj.get("currencies") or {}),
        )


@dataclass(frozen=True)
class MarketHoliday:
    """One entry of /v1/marketstatus/upcoming.

    ``status`` is "open", "closed", or "early-close". ``open``/``close`` are
    the (string) session times when status is "early-close".
    """

    date: date
    exchange: str
    name: str
    status: str
    open: str | None = None
    close: str | None = None

    @staticmethod
    def from_api(obj: Mapping[str, Any]) -> MarketHoliday:
        return MarketHoliday(
            date=date.fromisoformat(str(obj["date"])),
            exchange=str(obj["exchange"]),
            name=str(obj["name"]),
            status=str(obj["status"]),
            open=obj.get("open"),
            close=obj.get("close"),
        )

    @property
    def is_trading_day(self) -> bool:
        return self.status != "closed"

    @property
    def is_early_close(self) -> bool:
        return self.status == "early-close"
