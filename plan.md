# zen-massive-data-access — Dev Plan

A small data access module on **Massive.com (ex-Polygon.io)** for **daily and multi-day
rebalancing strategies that run after the market close**: the PPO and rule-based
workers in
[deploy-quant-research-experiment](https://github.com/zen-tradings/deploy-quant-research-experiment)
(branch `yanpan`, `deployment/`), plus training/backtests on the same data.

Massive is **data-only** here. Brokerage (account, positions, orders, market clock)
stays with Alpaca.

> **Scope change.** An earlier version of this plan described a production-grade
> pipeline: a half-day-accurate session calendar, sha256 fingerprints that byte-match
> the deployment `build_snapshot`, and immutable rsync bundles with atomic symlink
> flips. For after-close daily strategies that is more machinery than the problem
> needs, so it is **deferred** (see §5). If it's needed later, it can be built on
> top of the same client.

---

## 1. What consumers need

| Consumer | Data | Notes |
|---|---|---|
| PPO worker | Daily **adjusted** closes, ~10 ETFs (SMH, SOXX, QQQ, XLK, XLE, VDE, XOP, XLU, ITA, XPH), 365–730 calendar days | Completed sessions only |
| Rule-based workers | Daily adjusted closes, 200+ sessions (SMA200, 20-day vol, EMA20) | Same frame |
| Training / backtests | Same adjusted daily closes, multi-year | Same function, larger `lookback_days` |

Not needed: intraday bars, real-time quotes as a data feed, or options. (Where the
order planner wants a spread check at execution time, `get_last_quote` exists, but
Alpaca can keep doing that.)

## 2. Output contract (simple)

`build_closes(client, symbols, lookback_days, *, end=None, max_missing_fraction=0.02,
calendar_symbol="SPY")`
returns a `pd.DataFrame`:

- tz-naive, midnight-normalized, unique, ascending `DatetimeIndex` named `date`
- one column per requested symbol, in the order requested
- daily closes from Massive aggregates with `adjusted=true`
- **completed sessions only**: before 16:30 ET, today's bar is excluded
- **trading days = dates the reference symbol (SPY) has bars for** (no separate
  calendar). Using a reference rather than the requested symbols means a gap is
  detectable even for a single symbol, or a day missing from all of them
- if the latest session is older than the expected one on a weekday → warning
  (data not published yet, or a holiday)
- missing data: per symbol, `missing / total sessions > max_missing_fraction` →
  `MissingDataError`; below that → logged warning and incomplete rows dropped.
  Values are never forward-filled
- a symbol with no bars, or any nonpositive close → `MissingDataError`

## 3. Distribution (simple)

`write_closes(df, out_dir)` writes `closes_YYYYMMDD.parquet` (date = last session)
and refreshes `closes_latest.parquet`, each via temp file + rename so a reader never
sees a half-written file. Other servers just read the file — via a shared mount,
`rsync`/`scp` from cron, or by running the CLI themselves with their own key. No
protocol beyond that.

```bash
massive-access closes SMH SOXX QQQ XLK --lookback-days 730 --out /var/lib/massive-access
```

Run via the systemd timer in `deploy/` (weekdays 17:00 America/New_York, retries on
failure, `--fail-on-stale --min-sessions 200`); see README "Deploy".

## 4. Layout

```
src/massive_access/
├── client.py            # REST client: Bearer auth, retry/backoff (429/5xx), next_url pagination
├── config.py            # API key: explicit arg > MASSIVE_API_KEY env > key file
│                         # ($MASSIVE_CONFIG_FILE, ~/.config/massive-access/key,
│                         #  /etc/massive-access/key; never from a repo .env)
├── errors.py
├── models.py            # Aggregate, Quote, MarketStatus, MarketHoliday
├── endpoints/
│   ├── stocks.py        # aggregates / daily bars, last NBBO quote
│   └── market.py        # market status, market holidays
├── frame.py             # build_closes, write_closes/read_closes, last_complete_session_date
└── cli.py               # `massive-access closes ...`
```

## 5. Phases

### Done
- [x] Phase 0: pyproject, package layout, ruff + pytest + CI, `MASSIVE_API_KEY` config
- [x] Phase 1: `MassiveClient`, aggregates (`adjusted=true`), last NBBO quote,
      market status/holidays, tests with recorded fixtures
- [x] Phase 2 (simplified): `build_closes` + `write_closes` + `massive-access closes`
- [x] Phase 3: deployable — `min_sessions`, `on_stale="raise"` + holiday cache,
      systemd service/timer, `deploy/install.sh`, hash-pinned `deploy/requirements.lock`

API note (checked against live api.massive.com + docs): Polygon-compatible, except
last quote is **`/v2/last/nbbo/{ticker}`** (not Polygon's `/v2/last-quote/stocks/...`).
Auth via `Authorization: Bearer` header.

### Next (small)
- [ ] Parity spot check: Massive vs Alpaca/yfinance closes for the profile universes;
      check dividend handling on XLU/XLE around ex-dates (Massive documents
      `adjusted` as split adjustment — confirm whether dividends are included before
      relying on it for total-return-sensitive signals)
- [ ] Confirm with a real key that the daily bar is final by 16:30 ET
- [ ] Optional incremental cache (append new sessions to one parquet per symbol)
      if multi-year pulls become slow or hit rate limits

### Deferred (only if needed)
- Session calendar with half-day precision (derive from `market-holidays`)
- sha256 fingerprints matching deployment `Snapshot`, byte-identical reproducibility
- Immutable `vYYYYMMDD` bundles + manifest + rsync pull + atomic `current` symlink
- Strict contract tests that import `build_snapshot` validation
- Flat Files (S3) bulk backfill

### Out of scope
- Intraday / minute bars, WebSocket streaming, options, order execution

## 6. Verification

- `ruff check .` and `pytest -q` green (no network, respx fixtures)
- Manual: `massive-access closes SMH QQQ --lookback-days 30` with a real key prints
  the last sessions, and excludes today when run before 16:30 ET
