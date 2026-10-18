"""massive-access CLI.

    massive-access closes SMH SOXX QQQ --lookback-days 730 --out /var/lib/massive-access
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys

from .client import MassiveClient
from .errors import MassiveError
from .frame import build_closes, write_closes


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
        "--out", help="directory for closes_YYYYMMDD.parquet + closes_latest.parquet"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        with MassiveClient() as client:
            closes = build_closes(
                client,
                [s.upper() for s in args.symbols],
                args.lookback_days,
                end=args.end,
                max_missing_fraction=args.max_missing,
            )
    except MassiveError as exc:
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
