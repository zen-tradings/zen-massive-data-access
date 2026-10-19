"""massive_access — data access on the Massive.com (ex-Polygon.io) REST API.

Scope: daily / multi-day strategies run after the close. Authenticated client,
core stock/market endpoints, and a daily adjusted close frame builder.
"""

from .client import MassiveClient
from .config import get_api_key
from .endpoints.market import get_market_holidays, get_market_status
from .endpoints.stocks import get_aggregates, get_daily_bars, get_last_quote
from .errors import (
    MassiveAPIError,
    MassiveAuthError,
    MassiveError,
    MissingAPIKeyError,
)
from .frame import (
    MissingDataError,
    StaleDataError,
    build_closes,
    last_complete_session_date,
    read_closes,
    write_closes,
)
from .models import (
    Aggregate,
    AggregateResponse,
    MarketHoliday,
    MarketStatus,
    Quote,
)

__version__ = "0.1.0"

__all__ = [
    "Aggregate",
    "AggregateResponse",
    "MarketHoliday",
    "MarketStatus",
    "MassiveAPIError",
    "MassiveAuthError",
    "MassiveClient",
    "MassiveError",
    "MissingAPIKeyError",
    "MissingDataError",
    "Quote",
    "StaleDataError",
    "__version__",
    "build_closes",
    "get_aggregates",
    "get_api_key",
    "get_daily_bars",
    "get_last_quote",
    "get_market_holidays",
    "get_market_status",
    "last_complete_session_date",
    "read_closes",
    "write_closes",
]
