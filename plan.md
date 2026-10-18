# zen-massive-data-access — Dev Plan

A data access module on **Massive.com (ex-Polygon.io) Advanced plan** whose primary
consumer is the strategy deployment stack in
[deploy-quant-research-experiment](https://github.com/zen-tradings/deploy-quant-research-experiment)
(branch `yanpan`, `deployment/` directory).

Massive is **data-only** here. Brokerage concerns (account, positions, orders, market
clock gating) stay with Alpaca; this module replaces only the market-data reads
currently done via Alpaca IEX bars/quotes and yfinance in the training code.

---

## 1. What the deployment module needs (contract inputs)

Source of truth: `deployment/rebalancing/` (`alpaca.py`, `data.py`) and profiles
(`baseline.yaml`, `ppo.yaml`, `soxl_ema20.yaml`, plus `rule-based/` strategies:
SOXX/XLK 200-day trend, QQQ 20% vol target).

| Consumer | Data needed | Notes |
|---|---|---|
| PPO worker | Daily **adjusted** closes, ~10 ETFs (SMH, SOXX, QQQ, XLK, XLE, VDE, XOP, XLU, ITA, XPH), completed sessions only, `lookback_days` 365–730 calendar days | Fed to `build_snapshot`; min 200 sessions; NaN/missing/nonpositive → fail closed |
| Rule-based workers | Daily adjusted closes; up to 200+ sessions (SMA200, 20-day realized vol, EMA20) | Same frame, no partial bar for today |
| Order planner | **Latest NBBO quote** per symbol (bid/ask + timestamp) at run time | Spread/staleness checks against `risk.max_spread_fraction` / `max_quote_age_seconds` |
| All workers | NYSE session calendar (open days, incl. half days) | Today from Alpaca `get_calendar`; Massive `market-holidays` only gives holidays, so derive sessions ourselves or keep a small static calendar |
| Training (`train_ppo.py`, `walk_forward.py`) | Same adjusted daily bars, but **multi-year** history for the whole universe | Must be the *same adjustment semantics* as serving (`test_deployment_parity.py`) |
| `options_collector` notebook | Option chains + per-session quote polling (currently Alpaca) | Later phase: replace with Massive options endpoints |

There may be **many consumer services**: `rebalance@*` template workers (`baseline`,
`ppo`, `rank-*`), `rule-based` family workers, and future families — potentially on
separate servers. The data module must distribute to N consumers, not act as a
library local to one strategy box.

### Frame contract (must satisfy `build_snapshot`'s validation)

- `pd.DataFrame` of closes: tz-**naive** `DatetimeIndex`, midnight-normalized, unique,
  monotonic increasing; columns exactly the requested symbols
- Completed sessions only — the running day's bar is excluded during market hours
- Adjusted for splits and dividends (equivalent of Alpaca `Adjustment.ALL`,
  Massive aggregates `adjusted=true`)
- Complete: no NaN, no nonpositive prices
- Reproducible: same `(symbols, as_of, lookback)` → byte-identical values,
  so the sha256 fingerprint in `Snapshot` stays stable across runs

---

## 2. Scope of this module

**In scope**
- Authenticated REST client (reads `MASSIVE_API_KEY` from env; never loaded from `.env` implicitly)
- Stocks: aggregates (custom bars), daily summaries, last trade / last NBBO quote,
  historical quotes+trades (paged), snapshots, market holidays/status, splits, dividends
- Session calendar derivation (US equities) and canonical close-frame builder
- Parquet cache with incremental updates (like `src/data.py` in the research repo,
  but versioned and fingerprint-aware)
- CLI for daily pull / backfill / verify (systemd-friendly for the Ubuntu server)
- Parity tooling: prove Massive frames ≡ Alpaca/yfinance frames used today

**Out of scope (phase 1)**
- Order execution, account/position reads (stay with Alpaca)
- WebSocket streaming (deployment runs daily via systemd timers; REST polling suffices)
- Minute bars (only needed if intraday strategies arrive)
- Options endpoints (phase 4, tracking `options_collector` migration)

---

## 2.1 Bundle transmission (strategy servers)

Consumers live on separate servers, so datasets move as **immutable bundles**, not
API calls between services:

- **Producer** (this module): after the daily pull, publishes
  `/opt/quant-datasets/vYYYYMMDD/` — parquet frames + `manifest.json`
  (schema version, symbol set, session range, sha256 fingerprint matching the
  deployment `Snapshot` inputs, producer host/timestamp)
- **Transport**: consumers **pull** with `rsync -e ssh` from the data host
  (deploy-key, read-only, like the existing GitHub deploy key). Pull-not-push:
  adding a server needs no producer change
- **Install**: stage to `vYYYYMMDD.partial/`, verify manifest fingerprint against
  the parquet just downloaded, then atomic symlink flip `current` → `vYYYYMMDD`.
  A broken mid-transfer bundle is never consumed
- **Ordering**: consumer timer ~15–30 min after producer timer; consumer also
  verifies manifest fingerprint matches what `build_snapshot` computes — mismatch
  → fail closed, keep using the previous day (matches the deployment philosophy)
- **Live exceptions not bundled**: execution-time NBBO quotes and market clock
  are fetched per-consumer directly (seconds-old data can't be bundled)
- Alt transports if the topology changes: S3/object storage or read-only NFS —
  the bundle format stays identical

## 3. Architecture

```
zen-massive-data-access/
├── pyproject.toml                    # python 3.11/3.12; httpx, pandas, pyarrow; dev: pytest, respx, ruff
├── src/massive_access/
│   ├── client.py                     # REST client: retries w/ jittered backoff on 429/5xx,
│   │                                 # pagination (next_url), timeouts, request id logging
│   ├── endpoints/
│   │   ├── stocks.py                 # aggregates, daily summary, last trade/quote, snapshot,
│   │   │                             # splits, dividends
│   │   └── market.py                 # market-holidays, market-status
│   ├── calendar.py                   # session calendar 2004→now+1y from holidays; half-day aware
│   ├── frame.py                      # bars → session-indexed closes DataFrame (the contract above)
│   ├── cache.py                      # parquet store keyed by (symbol, adjusted, timeframe),
│   │                                 # atomic write, incremental append + dedupe
│   ├── fingerprint.py                # sha256 window fingerprint, matches deployment Snapshot
│   └── cli.py                        # `massive-access pull|verify|calendar` commands
├── tests/                            # respx-recorded fixtures, calendar edge cases,
│                                     # contract tests replicating build_snapshot validation
└── docs/
```

Key decisions
- **`adjusted=true` from the API**, no self-adjustment in v1 — but store splits/dividends
  alongside so we can audit adjustment-break days (ex-date → prior-day closes change →
  fingerprint changes; expected behavior, but must be visible in logs)
- **Fail closed**: any missing session in the window → error, never silently
  forward-fill (matches the deployment philosophy)
- **No partial bar**: `end` is exclusive; during an open session, today's row is dropped
  and flagged in logs
- Cache files under `$MASSIVE_DATA_DIR` (default `~/.cache/massive-access`,
  `/var/lib/massive-access` on the server)

---

## 4. Phase plan

### Phase 0 — Scaffolding
- [ ] pyproject, package layout, ruff + pytest + CI
- [ ] Env-var config: `MASSIVE_API_KEY` required; clear error listing the signup
      hint if missing/401

### Phase 1 — Client + core endpoints
- [ ] `client.py`: retry/backoff (429/5xx), pagination, timeouts, request logging
- [ ] Stocks aggregates (daily bars, `adjusted=true`), last-NBBO-quote, market-status,
      market-holidays
- [ ] Tests with recorded fixtures

### Phase 2 — Contract frame
- [ ] `calendar.py`: derive sessions; unit tests incl. early-close days, holidays
- [ ] `frame.build_closes(symbols, as_of, lookback_days) -> DataFrame` with the exact
      contract validation rules
- [ ] `fingerprint` for `(sessions × closes)` identical to deployment hashing inputs
- [ ] **Bundle publishing**: immutable `dataset-vYYYYMMDD` outputs (parquet + manifest
      + sha256 fingerprint); strategy servers pull before their timer windows, same
      as `/opt/quant-models/ppo-vNNN` model bundles

### Phase 3 — Cache + CLI
- [ ] Parquet cache, incremental daily update, atomic replace
- [ ] `massive-access pull` (daily refresh), `verify --as-of DATE` (rebuilds and
      fingerprints today's window), `backfill --years N`
- [ ] systemd timer/service snippets mirroring `deployment/ops/`

### Phase 4 — Parity & integration
- [ ] Run Alpaca-IEX and Massive pulls for the profile universes; report per-session
      close deltas (expected: small; decisions documented, esp. corporate actions)
- [ ] Adapter doc + example: swap-in function returning `(closes, quotes)` with the
      same signature semantics as `rebalancing/alpaca.py` paper reads
- [ ] Feasibility note: consolidating Alpaca data + Massive in deployment `data_source` config

### Phase 5 — Options (later)
- [ ] Options contracts + chain snapshot + quote polling to replace Alpaca in
      `options_collector`

---

## 5. Open questions

1. **Quote latency on Advanced plan** — confirm the entitlement window for NBBO
   (`last-quote`) during market hours; the risk checks (`max_quote_age_seconds`,
   `max_spread_fraction`) need genuinely fresh quotes.
2. **Flat Files (S3)** — Advanced includes bulk files; use them for multi-year
   backfill of the training universe instead of thousands of REST calls?
3. **Adjustment semantics** — spot-check Massive `adjusted=true` vs Alpaca `ALL`
   on dividend-heavy ETFs (XLU, XLE) around ex-dates; document deltas before cutover.
4. Repo home: standalone PyPI-less package installed from git on its own host
   (`/opt/massive-data-access` + `/opt/quant-datasets/`), consistent with
   `deployment/`'s install model.

## 6. Verification

- `pytest` green incl. contract tests that import `build_snapshot`'s validation rules
  as fixtures
- `massive-access verify` reproduces the deployment fingerprint for a fixed
  `(symbols, as_of)` on two different machines
- 30-day shadow run: Massive frames vs Alpaca frames; zero fail-closed events caused
  by the data layer
