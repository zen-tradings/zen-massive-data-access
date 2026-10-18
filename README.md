# zen-massive-data-access

Data access module on **Massive.com (ex-Polygon.io)**, serving the strategy
deployment stack in `deploy-quant-research-experiment`. Massive is **data-only**:
brokerage/execution stay with Alpaca. See `plan.md` for the full design.

## Status

- [x] Phase 0 — scaffolding, env-var config (`MASSIVE_API_KEY`)
- [x] Phase 1 — REST client (retry/backoff, pagination) + aggregates,
      last-NBBO-quote, market-status, market-holidays
- [ ] Phase 2 — session calendar, contract frame, fingerprint, bundles
- [ ] Phase 3 — parquet cache + CLI
- [ ] Phase 4 — parity vs Alpaca/yfinance
- [ ] Phase 5 — options

## Usage

```python
import datetime as dt

from massive_access import (
    MassiveClient,
    get_daily_bars,
    get_last_quote,
    get_market_status,
)

# MASSIVE_API_KEY must be set in the environment (or pass api_key=)
with MassiveClient() as client:
    bars = get_daily_bars(client, "SMH", dt.date(2024, 1, 1), dt.date(2024, 12, 31))
    quote = get_last_quote(client, "SMH")     # latest NBBO, live
    status = get_market_status(client)
```

Endpoints in scope return typed models from `massive_access.models`; raw API
shapes are preserved (field names per https://massive.com/docs/rest/stocks).

## Development

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest -q
```

Tests use `respx`-recorded fixtures (no network, no API key needed).
