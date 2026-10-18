"""Stocks endpoints: aggregates (custom bars) and last NBBO quote.

Docs: https://massive.com/docs/rest/stocks/aggregates/custom-bars
      https://massive.com/docs/rest/stocks/trades-quotes/last-quote
"""

from __future__ import annotations

import datetime as dt

from ..client import MassiveClient
from ..models import VALID_TIMESPANS, Aggregate, AggregateResponse, Quote

DateLike = str | int | dt.date | dt.datetime


def _window_param(value: DateLike) -> str:
    """Coerce ``from``/``to`` to the API format: YYYY-MM-DD or ms-since-epoch.

    ``str`` values pass through unchanged (YYYY-MM-DD or raw ms string).
    ``int``/``float`` are milliseconds since epoch.
    """
    if isinstance(value, (int, float)):
        return str(int(value))
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError(f"unsupported window bound {value!r}")


def get_aggregates(
    client: MassiveClient,
    ticker: str,
    from_: DateLike,
    to: DateLike,
    *,
    multiplier: int = 1,
    timespan: str = "day",
    adjusted: bool = True,
    sort: str = "asc",
    limit: int = 50_000,
) -> AggregateResponse:
    """Fetch all aggregate bars for one ticker in [``from_``, ``to``].

    Follows cursor pagination transparently; the returned object holds the
    merged results. ``results`` is empty (not an error) when the window
    contains no bars — callers decide whether that's a fail-closed condition.
    """
    if timespan not in VALID_TIMESPANS:
        raise ValueError(f"timespan must be one of {VALID_TIMESPANS}, got {timespan!r}")
    if sort not in ("asc", "desc"):
        raise ValueError(f"sort must be 'asc' or 'desc', got {sort!r}")
    if not 1 <= limit <= 50_000:
        raise ValueError(f"limit must be in [1, 50000], got {limit}")

    path = (
        f"/v2/aggs/ticker/{ticker}"
        f"/range/{multiplier}/{timespan}/{_window_param(from_)}/{_window_param(to)}"
    )
    params = {"adjusted": adjusted, "sort": sort, "limit": limit}

    results: list[Aggregate] = []
    status = "UNKNOWN"
    request_id: str | None = None
    pages = 0
    for page in client.iter_pages(path, params=params):
        pages += 1
        payload_status = str(page.get("status", "UNKNOWN"))
        if payload_status == "ERROR":
            raise ValueError(
                f"aggregates request returned status=ERROR for {ticker} "
                f"(request_id={page.get('request_id')})"
            )
        status = payload_status
        request_id = page.get("request_id") or request_id
        rows = page.get("results") or []  # API returns null results for empty windows
        results.extend(Aggregate.from_api(r) for r in rows)

    return AggregateResponse(
        ticker=ticker,
        adjusted=adjusted,
        status=status,
        results=tuple(results),
        request_id=request_id,
        query_count=pages,
    )


def get_daily_bars(
    client: MassiveClient,
    ticker: str,
    from_: DateLike,
    to: DateLike,
    *,
    adjusted: bool = True,
) -> AggregateResponse:
    """Daily bars for one ticker. Note ``to`` is inclusive on the API side —
    excluding the running session is ``frame.build_closes``'s job.
    """
    return get_aggregates(
        client, ticker, from_, to, multiplier=1, timespan="day", adjusted=adjusted
    )


def get_last_quote(client: MassiveClient, ticker: str) -> Quote:
    """Latest NBBO (bid/ask) quote for one ticker.

    Live data for execution-time spread checks; not used by ``build_closes``.
    """
    payload = client.get_json(f"/v2/last/nbbo/{ticker}")
    quote = Quote.from_api(payload)
    if isinstance(payload, dict) and payload.get("request_id"):
        quote = Quote(**{**quote.__dict__, "request_id": payload["request_id"]})
    return quote
