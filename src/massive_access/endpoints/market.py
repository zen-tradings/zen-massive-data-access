"""Market operations endpoints: market status and market holidays.

Docs: https://massive.com/docs/rest/stocks/market-operations/market-status
      https://massive.com/docs/rest/stocks/market-operations/market-holidays
"""

from __future__ import annotations

from ..client import MassiveClient
from ..errors import MassiveAPIError
from ..models import MarketHoliday, MarketStatus

_EXCHANGES_FOR_SESSION_CALENDAR = ("NYSE", "Nasdaq")


def get_market_status(client: MassiveClient) -> MarketStatus:
    """Current market status: open/closed/extended-hours snapshot."""
    return MarketStatus.from_api(client.get_json("/v1/marketstatus/now"))


def get_market_holidays(
    client: MassiveClient,
    *,
    exchanges: tuple[str, ...] = _EXCHANGES_FOR_SESSION_CALENDAR,
) -> list[MarketHoliday]:
    """Upcoming holidays/shortened days from /v1/marketstatus/upcoming.

    The endpoint only returns a few upcoming notable days, filtered to the
    cash-equities exchanges by default. Informational: ``build_closes`` uses
    the dates Massive has bars for as the trading days.
    """
    payload = client.get_json("/v1/marketstatus/upcoming")
    if not isinstance(payload, list):
        raise MassiveAPIError(
            f"expected list JSON from /v1/marketstatus/upcoming, got {type(payload)}"
        )
    holidays = [MarketHoliday.from_api(obj) for obj in payload]
    if exchanges:
        holidays = [h for h in holidays if h.exchange in exchanges]
    return holidays
