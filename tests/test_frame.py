from __future__ import annotations

import datetime as dt
import json
import logging

import httpx
import pandas as pd
import pytest
import respx

from massive_access import (
    MissingDataError,
    StaleDataError,
    build_closes,
    last_complete_session_date,
    read_closes,
    write_closes,
)
from massive_access.cli import main as cli_main
from massive_access.frame import NY

AGGS = r"https://api\.massive\.com/v2/aggs/ticker/{sym}/range/1/day/.*"
# Thursday 2024-01-11, after the close
AFTER_CLOSE = dt.datetime(2024, 1, 11, 17, 0, tzinfo=NY)
SESSIONS = ["2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10", "2024-01-11"]


def bars_body(sym: str, closes: dict[str, float]) -> dict:
    """Aggregates payload; ``t`` is the session's midnight ET, as Massive returns."""
    results = [
        {"t": int(pd.Timestamp(d, tz=NY).timestamp() * 1000),
         "o": c, "h": c, "l": c, "c": c, "v": 1000}
        for d, c in closes.items()
    ]
    return {"ticker": sym, "adjusted": True, "status": "OK", "results": results}


def mock_symbol(sym: str, closes: dict[str, float]) -> respx.Route:
    return respx.get(url__regex=AGGS.format(sym=sym)).mock(
        return_value=httpx.Response(200, json=bars_body(sym, closes))
    )


def full(base: float) -> dict[str, float]:
    return {d: base + i for i, d in enumerate(SESSIONS)}


def mock_calendar() -> respx.Route:
    """SPY (default calendar symbol) with every session present."""
    return mock_symbol("SPY", full(470))


# -- last_complete_session_date ---------------------------------------------


def test_cutoff_before_close_is_yesterday():
    now = dt.datetime(2024, 1, 11, 10, 0, tzinfo=NY)
    assert last_complete_session_date(now) == dt.date(2024, 1, 10)


def test_cutoff_after_close_is_today():
    assert last_complete_session_date(AFTER_CLOSE) == dt.date(2024, 1, 11)


def test_cutoff_converts_from_utc():
    # 2024-01-11 23:00 UTC == 18:00 ET -> after close
    now = dt.datetime(2024, 1, 11, 23, 0, tzinfo=dt.UTC)
    assert last_complete_session_date(now) == dt.date(2024, 1, 11)


# -- build_closes -------------------------------------------------------------


@respx.mock
def test_build_closes_shape_and_index(fast_client):
    mock_calendar()
    mock_symbol("SMH", full(100))
    mock_symbol("QQQ", full(400))

    closes = build_closes(fast_client, ["SMH", "QQQ"], 30, now=AFTER_CLOSE)

    assert list(closes.columns) == ["SMH", "QQQ"]
    assert list(closes.index) == list(pd.to_datetime(SESSIONS))
    assert closes.index.tz is None
    assert closes.index.is_monotonic_increasing and closes.index.is_unique
    assert (closes.index == closes.index.normalize()).all()
    assert closes.index.name == "date"
    assert closes.loc["2024-01-11", "QQQ"] == 404.0
    assert not closes.isna().any().any()


@respx.mock
def test_request_window_ends_at_last_complete_session(fast_client):
    mock_calendar()
    route = mock_symbol("SMH", full(100))
    during_session = dt.datetime(2024, 1, 11, 11, 0, tzinfo=NY)

    closes = build_closes(fast_client, ["SMH"], 10, now=during_session)

    assert route.calls[0].request.url.path.endswith("/2023-12-31/2024-01-10")
    # even if the API had returned today's forming bar, it is dropped
    assert closes.index[-1] == pd.Timestamp("2024-01-10")


@respx.mock
def test_explicit_end_is_capped_by_cutoff(fast_client):
    mock_calendar()
    route = mock_symbol("SMH", full(100))
    build_closes(fast_client, ["SMH"], 5, end=dt.date(2030, 1, 1), now=AFTER_CLOSE)
    assert route.calls[0].request.url.path.endswith("/2024-01-06/2024-01-11")


@respx.mock
def test_small_gap_warns_and_drops_row(fast_client, caplog):
    mock_calendar()
    mock_symbol("SMH", full(100))
    gappy = full(400)
    del gappy["2024-01-09"]
    mock_symbol("QQQ", gappy)

    with caplog.at_level(logging.WARNING):
        closes = build_closes(
            fast_client, ["SMH", "QQQ"], 30, max_missing_fraction=0.25, now=AFTER_CLOSE
        )

    assert pd.Timestamp("2024-01-09") not in closes.index
    assert len(closes) == 4
    assert "QQQ=1" in caplog.text


@respx.mock
def test_too_many_missing_raises(fast_client):
    mock_calendar()
    mock_symbol("SMH", full(100))
    mock_symbol("QQQ", {"2024-01-11": 404.0})
    with pytest.raises(MissingDataError, match="QQQ=4/5"):
        build_closes(fast_client, ["SMH", "QQQ"], 30, now=AFTER_CLOSE)


@respx.mock
def test_no_bars_raises(fast_client):
    respx.get(url__regex=AGGS.format(sym="NOPE")).mock(
        return_value=httpx.Response(200, json={"status": "OK", "ticker": "NOPE"})
    )
    with pytest.raises(MissingDataError, match="NOPE"):
        build_closes(fast_client, ["NOPE"], 30, now=AFTER_CLOSE)


@respx.mock
def test_nonpositive_close_raises(fast_client):
    mock_calendar()
    bad = full(100)
    bad["2024-01-08"] = 0.0
    mock_symbol("SMH", bad)
    with pytest.raises(MissingDataError, match="nonpositive"):
        build_closes(fast_client, ["SMH"], 30, now=AFTER_CLOSE)


@respx.mock
def test_single_symbol_gap_detected_via_calendar_symbol(fast_client, caplog):
    mock_calendar()
    gappy = full(100)
    del gappy["2024-01-09"]
    mock_symbol("SMH", gappy)

    with caplog.at_level(logging.WARNING):
        closes = build_closes(
            fast_client, ["SMH"], 30, max_missing_fraction=0.25, now=AFTER_CLOSE
        )

    assert list(closes.columns) == ["SMH"]  # SPY only defines the days
    assert pd.Timestamp("2024-01-09") not in closes.index
    assert "SMH=1" in caplog.text


@respx.mock
def test_without_calendar_symbol_single_symbol_gap_is_invisible(fast_client):
    gappy = full(100)
    del gappy["2024-01-09"]
    mock_symbol("SMH", gappy)
    closes = build_closes(fast_client, ["SMH"], 30, calendar_symbol=None, now=AFTER_CLOSE)
    assert len(closes) == 4  # documented limitation of calendar_symbol=None


@respx.mock
def test_calendar_symbol_in_request_is_not_fetched_twice(fast_client):
    spy = mock_calendar()
    closes = build_closes(fast_client, ["SPY"], 30, now=AFTER_CLOSE)
    assert spy.call_count == 1
    assert list(closes.columns) == ["SPY"]


@respx.mock
def test_stale_latest_session_warns(fast_client, caplog):
    stale = {d: 1.0 + i for i, d in enumerate(SESSIONS[:-1])}  # no 2024-01-11 bar yet
    mock_symbol("SPY", stale)
    mock_symbol("SMH", stale)

    with caplog.at_level(logging.WARNING):
        closes = build_closes(fast_client, ["SMH"], 30, now=AFTER_CLOSE)

    assert closes.index[-1] == pd.Timestamp("2024-01-10")
    assert "expected 2024-01-11" in caplog.text


def mock_stale() -> None:
    stale = {d: 1.0 + i for i, d in enumerate(SESSIONS[:-1])}  # no 2024-01-11 bar
    mock_symbol("SPY", stale)
    mock_symbol("SMH", stale)


@respx.mock
def test_stale_raises_when_asked(fast_client):
    mock_stale()
    with pytest.raises(StaleDataError, match="expected 2024-01-11"):
        build_closes(fast_client, ["SMH"], 30, on_stale="raise", now=AFTER_CLOSE)


@respx.mock
def test_stale_on_known_holiday_is_fine(fast_client, caplog):
    mock_stale()
    with caplog.at_level(logging.WARNING):
        closes = build_closes(
            fast_client, ["SMH"], 30, on_stale="raise",
            closed_dates={dt.date(2024, 1, 11)}, now=AFTER_CLOSE,
        )
    assert closes.index[-1] == pd.Timestamp("2024-01-10")
    assert "expected" not in caplog.text


@respx.mock
def test_min_sessions(fast_client):
    mock_calendar()
    mock_symbol("SMH", full(100))
    assert len(build_closes(fast_client, ["SMH"], 30, min_sessions=5, now=AFTER_CLOSE)) == 5
    with pytest.raises(MissingDataError, match="only 5 sessions, need >= 6"):
        build_closes(fast_client, ["SMH"], 30, min_sessions=6, now=AFTER_CLOSE)


@pytest.mark.parametrize(
    ("symbols", "lookback"), [([], 30), (["SMH", "SMH"], 30), (["SMH"], 0)]
)
def test_bad_arguments(fast_client, symbols, lookback):
    with pytest.raises(ValueError):
        build_closes(fast_client, symbols, lookback, now=AFTER_CLOSE)


# -- parquet output -----------------------------------------------------------


def test_write_and_read_roundtrip(tmp_path):
    closes = pd.DataFrame(
        {"SMH": [1.0, 2.0]}, index=pd.DatetimeIndex(["2024-01-10", "2024-01-11"], name="date")
    )
    path = write_closes(closes, tmp_path / "out")

    assert path.name == "closes_20240111.parquet"
    assert (tmp_path / "out" / "closes_latest.parquet").exists()
    assert not list((tmp_path / "out").glob("*.tmp"))
    pd.testing.assert_frame_equal(read_closes(path), closes)


def test_write_refuses_empty(tmp_path):
    with pytest.raises(ValueError):
        write_closes(pd.DataFrame(), tmp_path)


# -- CLI ----------------------------------------------------------------------


@respx.mock
def test_cli_closes_writes_parquet(monkeypatch, tmp_path, capsys):
    mock_calendar()
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(
        "massive_access.frame.last_complete_session_date", lambda *_a, **_k: dt.date(2024, 1, 11)
    )
    mock_symbol("SMH", full(100))

    rc = cli_main(["closes", "smh", "--lookback-days", "30", "--out", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "closes_20240111.parquet").exists()
    assert "5 sessions x 1 symbols" in capsys.readouterr().out


@respx.mock
def test_cli_status_error_in_200_body_exits_cleanly(monkeypatch, capsys):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    respx.get(url__regex=AGGS.format(sym="SMH")).mock(
        return_value=httpx.Response(200, json={"status": "ERROR", "error": "bad ticker"})
    )
    assert cli_main(["closes", "SMH"]) == 1
    assert "bad ticker" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["SMH", "--lookback-days", "0"], ["SMH", "smh"]])
def test_cli_bad_arguments_exit_cleanly(monkeypatch, capsys, argv):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    assert cli_main(["closes", *argv]) == 1
    assert capsys.readouterr().err.startswith("error:")


def test_cli_missing_key_exits_nonzero(monkeypatch, capsys):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    # Ignore real key files (~/.config/..., /etc/...) so this never hits the network.
    monkeypatch.setattr("massive_access.config.key_file_candidates", lambda: [])
    assert cli_main(["closes", "SMH"]) == 1
    assert "MASSIVE_API_KEY" in capsys.readouterr().err


HOLIDAYS = r"https://api\.massive\.com/v1/marketstatus/upcoming"


@pytest.fixture
def cli_env(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    monkeypatch.setattr(
        "massive_access.frame.last_complete_session_date", lambda *_a, **_k: dt.date(2024, 1, 11)
    )


@respx.mock
def test_cli_fail_on_stale_exits_1_and_writes_nothing(cli_env, tmp_path, capsys):
    mock_stale()
    respx.get(url__regex=HOLIDAYS).mock(return_value=httpx.Response(200, json=[]))

    rc = cli_main(["closes", "SMH", "--fail-on-stale", "--out", str(tmp_path)])

    assert rc == 1
    assert "expected 2024-01-11" in capsys.readouterr().err
    assert not list(tmp_path.glob("*.parquet"))


@respx.mock
def test_cli_holiday_cache_remembers_past_upcoming_days(cli_env, tmp_path):
    mock_stale()
    # day before: the endpoint lists the holiday as upcoming -> cached
    (tmp_path / "market_holidays.json").write_text(json.dumps(["2024-01-11"]))
    # on the day itself the endpoint no longer lists it
    respx.get(url__regex=HOLIDAYS).mock(return_value=httpx.Response(200, json=[]))

    rc = cli_main(["closes", "SMH", "--fail-on-stale", "--out", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "closes_20240110.parquet").exists()


@respx.mock
def test_cli_holiday_cache_is_updated(cli_env, tmp_path):
    mock_calendar()
    mock_symbol("SMH", full(100))
    respx.get(url__regex=HOLIDAYS).mock(return_value=httpx.Response(200, json=[
        {"date": "2024-01-15", "exchange": "NYSE", "name": "MLK", "status": "closed"},
        {"date": "2024-01-16", "exchange": "NYSE", "name": "x", "status": "early-close"},
        {"date": "2024-01-17", "exchange": "NASDAQ", "name": "x", "status": "closed"},
    ]))

    assert cli_main(["closes", "SMH", "--fail-on-stale", "--out", str(tmp_path)]) == 0
    assert json.loads((tmp_path / "market_holidays.json").read_text()) == ["2024-01-15"]


@respx.mock
def test_cli_holiday_fetch_failure_falls_back_to_stale_check(cli_env, tmp_path, capsys):
    mock_stale()
    respx.get(url__regex=HOLIDAYS).mock(return_value=httpx.Response(404, json={}))
    assert cli_main(["closes", "SMH", "--fail-on-stale", "--out", str(tmp_path)]) == 1
