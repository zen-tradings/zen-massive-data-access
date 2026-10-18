"""Market operations endpoints (Phase 1): market status and market holidays.

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

    The endpoint only returns up to a few upcoming notable days; it is the
    input for deriving our own session calendar (Phase 2), filtered to the
    cash-equities exchanges by default.
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
