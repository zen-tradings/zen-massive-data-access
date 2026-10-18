from __future__ import annotations

import datetime as dt

import httpx
import pytest
import respx

from massive_access import (
    get_aggregates,
    get_last_quote,
    get_market_holidays,
    get_market_status,
)
from massive_access.endpoints.stocks import get_daily_bars

BASE = "https://api.massive.com"


@respx.mock
def test_get_aggregates_merges_pages(fast_client, fixture):
    page1 = fixture("aggregates_page1.json")
    page2 = fixture("aggregates_page2.json")
    respx.get(f"{BASE}/v2/aggs/ticker/AAPL/range/1/day/2020-01-01/2020-01-10").mock(
        return_value=httpx.Response(200, json=page1)
    )
    respx.get(page1["next_url"]).mock(return_value=httpx.Response(200, json=page2))

    resp = get_aggregates(fast_client, "AAPL", "2020-01-01", "2020-01-10")

    assert resp.ticker == "AAPL"
    assert resp.adjusted is True
    assert resp.status == "OK"
    assert resp.results_count == 3
    assert [a.c for a in resp.results] == [75.0875, 74.3575, 74.9535]
    first = resp.results[0]
    assert (first.o, first.h, first.l, first.v, first.vw, first.n) == (
        74.06, 75.15, 73.7975, 135647456.0, 74.6099, 1
    )
    assert first.start_time_utc == dt.datetime(2020, 1, 2, 5, 0, tzinfo=dt.UTC)
    assert resp.query_count == 2  # two pages


@respx.mock
def test_get_aggregates_empty_window_is_not_error(fast_client, fixture):
    respx.get(f"{BASE}/v2/aggs/ticker/AAPL/range/1/day/2020-11-26/2020-11-26").mock(
        return_value=httpx.Response(200, json=fixture("aggregates_empty.json"))
    )
    resp = get_aggregates(fast_client, "AAPL", "2020-11-26", "2020-11-26")
    assert resp.results_count == 0


@respx.mock
def test_get_daily_bars_sends_expected_params(fast_client, fixture):
    route = respx.get(f"{BASE}/v2/aggs/ticker/SMH/range/1/day/2024-01-01/2024-02-01").mock(
        return_value=httpx.Response(200, json=fixture("aggregates_empty.json"))
    )
    get_daily_bars(
        fast_client, "SMH", dt.date(2024, 1, 1), dt.date(2024, 2, 1), adjusted=True
    )
    params = route.calls[0].request.url.params
    assert params["adjusted"] == "true"
    assert params["sort"] == "asc"
    assert params["limit"] == "50000"


def test_aggregates_rejects_invalid_timespan(fast_client):
    with pytest.raises(ValueError, match="timespan"):
        get_aggregates(fast_client, "AAPL", "2020-01-01", "2020-01-10", timespan="fortnight")


@respx.mock
def test_get_last_quote_parses_nbbo(fast_client, fixture):
    respx.get(f"{BASE}/v2/last/nbbo/AAPL").mock(
        return_value=httpx.Response(200, json=fixture("last_quote.json"))
    )
    quote = get_last_quote(fast_client, "AAPL")
    # uppercase = ask, lowercase = bid
    assert quote.ask_price == 127.98
    assert quote.ask_size == 7
    assert quote.ask_exchange == 19
    assert quote.bid_price == 127.96
    assert quote.bid_size == 1
    assert quote.bid_exchange == 11
    assert quote.timestamp_ns == 1617827221349730300
    assert quote.participant_timestamp_ns == 1617827221349366000
    assert quote.sequence == 83480742
    assert quote.tape == 3
    assert quote.ticker == "AAPL"
    assert quote.request_id == "a0114ff18a3b0155e7b1c3b7912e13ef"
    assert quote.timestamp_utc == dt.datetime(2021, 4, 7, 20, 27, 1, 349730, tzinfo=dt.UTC)


@respx.mock
def test_get_market_status(fast_client, fixture):
    respx.get(f"{BASE}/v1/marketstatus/now").mock(
        return_value=httpx.Response(200, json=fixture("market_status.json"))
    )
    status = get_market_status(fast_client)
    assert status.market == "extended-hours"
    assert status.after_hours is True
    assert status.early_hours is False
    assert status.exchanges["nyse"] == "extended-hours"
    assert status.server_time.tzinfo is not None


@respx.mock
def test_get_market_holidays(fast_client, fixture):
    respx.get(f"{BASE}/v1/marketstatus/upcoming").mock(
        return_value=httpx.Response(200, json=fixture("market_holidays.json"))
    )
    holidays = get_market_holidays(fast_client)
    assert len(holidays) == 2

    closed, early_close = holidays
    assert closed.status == "closed"
    assert closed.date == dt.date(2020, 11, 26)
    assert not closed.is_trading_day
    assert not closed.is_early_close

    assert early_close.is_early_close
    assert early_close.is_trading_day
    assert early_close.close == "1:00 PM"
    assert early_close.open == "9:30 AM"


def test_holidays_exchange_filter(fast_client, fixture):
    body = fixture("market_holidays.json") + [
        {"date": "2020-11-26", "exchange": "OTC", "name": "Thanksgiving", "status": "closed"}
    ]
    with respx.mock:
        respx.get(f"{BASE}/v1/marketstatus/upcoming").mock(
            return_value=httpx.Response(200, json=body)
        )
        assert len(get_market_holidays(fast_client, exchanges=())) == 3
        assert len(get_market_holidays(fast_client)) == 2
