"""Daily adjusted close frames for daily / multi-day strategies.

Intentionally simple:
- the trading days are the dates Massive returns bars for (no session calendar)
- today's bar is dropped until the session is over (``complete_after`` ET)
- missing data is counted per symbol; too much → ``MissingDataError``,
  a little → warning, and incomplete rows are dropped (never forward-filled)
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Sequence
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .client import MassiveClient
from .endpoints.stocks import get_daily_bars
from .errors import MassiveError

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")

# Regular close is 16:00 ET; the extra margin lets the final daily bar settle.
# On half days this simply waits longer than needed, which is harmless.
DEFAULT_COMPLETE_AFTER = dt.time(16, 30)


class MissingDataError(MassiveError):
    """A symbol has no bars, or more missing sessions than allowed."""


def last_complete_session_date(
    now: dt.datetime | None = None,
    complete_after: dt.time = DEFAULT_COMPLETE_AFTER,
) -> dt.date:
    """Latest date whose daily bar may be used.

    Before ``complete_after`` ET, today's bar is still forming, so the cutoff is
    yesterday. Weekends/holidays need no special case: there are simply no bars.
    """
    now_et = (now or dt.datetime.now(tz=NY)).astimezone(NY)
    if now_et.time() >= complete_after:
        return now_et.date()
    return now_et.date() - dt.timedelta(days=1)


def build_closes(
    client: MassiveClient,
    symbols: Sequence[str],
    lookback_days: int,
    *,
    end: dt.date | None = None,
    max_missing_fraction: float = 0.02,
    now: dt.datetime | None = None,
) -> pd.DataFrame:
    """Daily adjusted closes for ``symbols`` over the last ``lookback_days``
    calendar days ending at ``end`` (default: last complete session).

    Returns a DataFrame with a tz-naive, midnight-normalized, ascending
    ``DatetimeIndex`` (named ``date``) and one column per symbol, in the order
    given. Contains no NaN and only positive prices.
    """
    if not symbols:
        raise ValueError("symbols must not be empty")
    if len(set(symbols)) != len(symbols):
        raise ValueError(f"duplicate symbols: {list(symbols)}")
    if lookback_days < 1:
        raise ValueError(f"lookback_days must be >= 1, got {lookback_days}")

    cutoff = last_complete_session_date(now)
    end = min(end, cutoff) if end is not None else cutoff
    start = end - dt.timedelta(days=lookback_days)

    series: dict[str, pd.Series] = {}
    for symbol in symbols:
        resp = get_daily_bars(client, symbol, start, end, adjusted=True)
        if not resp.results:
            raise MissingDataError(f"{symbol}: no daily bars between {start} and {end}")
        index = (
            pd.to_datetime([bar.t for bar in resp.results], unit="ms", utc=True)
            .tz_convert(NY)
            .tz_localize(None)
            .normalize()
        )
        s = pd.Series([bar.c for bar in resp.results], index=index, name=symbol, dtype=float)
        s = s[~s.index.duplicated(keep="last")]
        series[symbol] = s[s.index.date <= end]  # belt and braces vs. the cutoff

    closes = pd.DataFrame(series).sort_index()
    closes.index.name = "date"

    bad = closes.le(0) & closes.notna()
    if bad.any().any():
        raise MissingDataError(f"nonpositive closes for: {list(closes.columns[bad.any()])}")

    total = len(closes)
    missing = closes.isna().sum()
    too_many = missing[missing > max_missing_fraction * total]
    if not too_many.empty:
        detail = ", ".join(f"{sym}={n}/{total}" for sym, n in too_many.items())
        raise MissingDataError(f"too many missing sessions: {detail}")
    if missing.any():
        detail = ", ".join(f"{sym}={n}" for sym, n in missing[missing > 0].items())
        logger.warning("dropping sessions with missing closes (%s)", detail)
        closes = closes.dropna()

    return closes


def write_closes(closes: pd.DataFrame, out_dir: str | Path, *, name: str = "closes") -> Path:
    """Write ``closes`` to ``out_dir/<name>_YYYYMMDD.parquet`` (date = last row)
    and refresh ``out_dir/<name>_latest.parquet``. Writes go through a temp file
    + rename so readers never see a half-written file.
    """
    if closes.empty:
        raise ValueError("refusing to write an empty frame")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = closes.index[-1].strftime("%Y%m%d")
    dated = out / f"{name}_{stamp}.parquet"
    for target in (dated, out / f"{name}_latest.parquet"):
        tmp = target.with_suffix(".parquet.tmp")
        closes.to_parquet(tmp)
        os.replace(tmp, target)
    return dated


def read_closes(path: str | Path) -> pd.DataFrame:
    """Read a frame written by ``write_closes``."""
    return pd.read_parquet(path)
