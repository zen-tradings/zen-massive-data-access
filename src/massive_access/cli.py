"""massive-access CLI.

    massive-access closes SMH SOXX QQQ --lookback-days 730 --out /var/lib/massive-access
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path

from .client import MassiveClient
from .config import find_api_key
from .endpoints.market import get_market_holidays
from .errors import MassiveError
from .frame import build_closes, write_closes

logger = logging.getLogger("massive_access.cli")

HOLIDAY_CACHE = "market_holidays.json"


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="massive-access", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("closes", help="fetch daily adjusted closes (completed sessions only)")
    c.add_argument("symbols", nargs="+", help="tickers, e.g. SMH SOXX QQQ")
    c.add_argument("--lookback-days", type=int, default=365, help="calendar days (default 365)")
    c.add_argument(
        "--end",
        type=dt.date.fromisoformat,
        help="last date YYYY-MM-DD (default: last complete session)",
    )
    c.add_argument(
        "--max-missing",
        type=float,
        default=0.02,
        help="max missing fraction per symbol (default 0.02)",
    )
    c.add_argument(
        "--calendar-symbol",
        default="SPY",
        help="symbol whose bars define the trading days (default SPY; 'none' to disable)",
    )
    c.add_argument(
        "--min-sessions",
        type=int,
        help="fail unless at least this many sessions are returned (e.g. 200 for SMA200)",
    )
    c.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="exit 1 (and write nothing) if the latest session is missing on a "
        "non-holiday weekday; for scheduled runs",
    )
    c.add_argument(
        "--out", help="directory for closes_YYYYMMDD.parquet + closes_latest.parquet"
    )
    sub.add_parser("key", help="show where the API key resolves from (never the key)")
    return p


def _cmd_key() -> int:
    key, source = find_api_key()
    if not key:
        print("no API key found (env var or key file)", file=sys.stderr)
        return 1
    print(f"API key found via {source}")
    return 0


def _closed_dates(client: MassiveClient, out: str | None) -> set[dt.date]:
    """NYSE full-closure dates: live ``/v1/marketstatus/upcoming`` merged with a
    cache in ``out`` (the endpoint only lists *upcoming* days, so remembering
    them means a holiday is still known on the day itself)."""
    cache = Path(out) / HOLIDAY_CACHE if out else None
    dates: set[dt.date] = set()
    if cache is not None and cache.exists():
        try:
            dates |= {dt.date.fromisoformat(d) for d in json.loads(cache.read_text())}
        except (ValueError, TypeError) as exc:
            logger.warning("ignoring unreadable %s: %s", cache, exc)
    try:
        live = get_market_holidays(client, exchanges=("NYSE",))
    except MassiveError as exc:
        logger.warning("could not fetch market holidays (%s); using cache only", exc)
    else:
        dates |= {h.date for h in live if not h.is_trading_day}
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(sorted(d.isoformat() for d in dates), indent=1))
            os.replace(tmp, cache)
    return dates


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request
    if args.command == "key":
        return _cmd_key()
    calendar_symbol = args.calendar_symbol.upper()
    try:
        with MassiveClient() as client:
            closed = _closed_dates(client, args.out) if args.fail_on_stale else set()
            closes = build_closes(
                client,
                [s.upper() for s in args.symbols],
                args.lookback_days,
                end=args.end,
                max_missing_fraction=args.max_missing,
                calendar_symbol=None if calendar_symbol == "NONE" else calendar_symbol,
                min_sessions=args.min_sessions,
                on_stale="raise" if args.fail_on_stale else "warn",
                closed_dates=closed,
            )
    except (MassiveError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.out:
        path = write_closes(closes, args.out)
        print(f"wrote {len(closes)} sessions x {closes.shape[1]} symbols -> {path}")
    else:
        print(closes.tail().to_string())
        print(f"[{len(closes)} sessions, {closes.index[0].date()} .. {closes.index[-1].date()}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
