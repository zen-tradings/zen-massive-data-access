"""massive_access — data access on the Massive.com (ex-Polygon.io) REST API.

Phase 0/1 surface: authenticated client + core stock/market endpoints.
Strategy-neutral: contract frames, session calendar, and bundle publishing
(Phase 2+) build on top of this module.
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
    "Quote",
    "__version__",
    "get_aggregates",
    "get_api_key",
    "get_daily_bars",
    "get_last_quote",
    "get_market_holidays",
    "get_market_status",
]
