# zen-massive-data-access

Daily adjusted close data from **Massive.com (ex-Polygon.io)** for daily / multi-day
rebalancing strategies that run after the close. Massive is **data-only**: brokerage
and execution stay with Alpaca. Design and scope: `plan.md`.

## Setup

The API key is resolved in order: explicit argument → `MASSIVE_API_KEY` env var →
key file. The key file lives outside this repo:

```bash
mkdir -p ~/.config/massive-access
# either just the key on one line, or MASSIVE_API_KEY=<key> (EnvironmentFile style)
echo 'mk_your_key_here' > ~/.config/massive-access/key
chmod 600 ~/.config/massive-access/key
```

Locations checked, in order: `$MASSIVE_CONFIG_FILE`,
`~/.config/massive-access/key`, `/etc/massive-access/key` (server).
`massive-access key` shows where the key resolved from (never the key itself).

## Usage

### CLI

```bash
# print the last few sessions
massive-access closes SMH SOXX QQQ --lookback-days 365

# write closes_YYYYMMDD.parquet + closes_latest.parquet for other servers to read
massive-access closes SMH SOXX QQQ XLK --lookback-days 730 --out /var/lib/massive-access

# scheduled runs: exit 1 and write nothing if data is short or not published yet
massive-access closes SMH SOXX QQQ --lookback-days 730 --min-sessions 200 \
    --fail-on-stale --out /var/lib/massive-access
```

`--fail-on-stale` treats a missing latest weekday session as an error unless
the day is a NYSE holiday. Holidays come from `/v1/marketstatus/upcoming`, which
only lists *upcoming* days, so the CLI keeps every closed date it has seen in
`<out>/market_holidays.json`. A holiday is then still known on the day itself.
The cache fills on the first run, which is enough for holidays after that.

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
- trading days are the dates SPY has bars for (`calendar_symbol`, CLI
  `--calendar-symbol`), so a gap in any requested symbol is caught
- a warning is logged if the latest session is older than expected (data not
  published yet, or a holiday); `on_stale="raise"` raises `StaleDataError`
  instead, except for dates in `closed_dates`
- `min_sessions=N` → `MissingDataError` if fewer sessions come back
- small gaps → warning and those rows are dropped; more than
  `max_missing_fraction` (default 2%) missing for a symbol → `MissingDataError`.
  Never forward-filled

Lower-level endpoints are also exported: `get_daily_bars`, `get_aggregates`,
`get_last_quote`, `get_market_status`, `get_market_holidays`.

## Deploy (Ubuntu 24.04 server)

```bash
git clone https://github.com/zen-tradings/zen-massive-data-access
cd zen-massive-data-access && sudo ./deploy/install.sh   # prompts for the key once
```

`deploy/install.sh` is idempotent (upgrade: `git pull && sudo ./deploy/install.sh`):

- system user `massive`, venv at `/opt/massive-access/venv` with pinned,
  hash-checked deps from `deploy/requirements.lock`
- `/etc/massive-access/key` (`root:massive 0640`) and
  `/etc/massive-access/closes.env` (symbols, lookback, min sessions; edit it)
- `massive-access-closes.timer` runs weekdays at **17:00 America/New_York**
  (correct even when the server clock is UTC, and across DST)
- `massive-access-closes.service` writes to `/var/lib/massive-access`; on failure
  (e.g. data not published yet) it retries every 20 min, up to 5 times

```bash
systemctl list-timers massive-access-closes.timer
sudo systemctl start massive-access-closes.service     # run now
journalctl -u massive-access-closes.service -n 50
systemctl --failed                                     # alerting: wire OnFailure= in the unit
```

Regenerate the lock after changing dependencies:

```bash
uv pip compile pyproject.toml --python-version 3.12 \
    --python-platform x86_64-unknown-linux-gnu --generate-hashes -o deploy/requirements.lock
```

## Development

```bash
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Tests use `respx` fixtures: no network and no API key needed.
