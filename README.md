# zen-massive-data-access

Daily adjusted close data from **Massive.com (ex-Polygon.io)** for daily / multi-day
rebalancing strategies that run after the close. Massive is **data-only**: brokerage
and execution stay with Alpaca. Design and scope: `plan.md`.

## Usage

`MASSIVE_API_KEY` must be set in the environment.

### CLI

```bash
# print the last few sessions
massive-access closes SMH SOXX QQQ --lookback-days 365

# write closes_YYYYMMDD.parquet + closes_latest.parquet for other servers to read
massive-access closes SMH SOXX QQQ XLK --lookback-days 730 --out /var/lib/massive-access
```

### Python

```python
from massive_access import MassiveClient, build_closes, write_closes

with MassiveClient() as client:
    closes = build_closes(client, ["SMH", "SOXX", "QQQ"], lookback_days=730)

write_closes(closes, "/var/lib/massive-access")
```

`closes` is a DataFrame with a tz-naive daily `DatetimeIndex` (`date`) and one
column per symbol:

- adjusted closes (`adjusted=true`), completed sessions only (today is excluded
  before 16:30 ET)
- trading days are the dates Massive has bars for
- small gaps → warning and those rows are dropped; more than
  `max_missing_fraction` (default 2%) missing for a symbol → `MissingDataError`.
  Never forward-filled

Lower-level endpoints are also exported: `get_daily_bars`, `get_aggregates`,
`get_last_quote`, `get_market_status`, `get_market_holidays`.

## Development

```bash
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Tests use `respx` fixtures: no network and no API key needed.
