"""Exception hierarchy for massive_access.

No endpoint logic here; everything subclasses ``MassiveError`` so callers can
catch the family or a specific failure mode. Per the fail-closed philosophy of
the deployment stack, nothing in this package ever swallows an API error.
"""

from __future__ import annotations


class MassiveError(Exception):
    """Base class for all massive_access errors."""


class MissingAPIKeyError(MassiveError):
    """MASSIVE_API_KEY was neither passed explicitly nor found in the environment."""


class MassiveAPIError(MassiveError):
    """The API returned an error status or an unparsable/error JSON body."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.request_id = request_id

    def __str__(self) -> str:
        base = super().__str__()
        suffix: list[str] = []
        if self.status is not None:
            suffix.append(f"status={self.status}")
        if self.request_id:
            suffix.append(f"request_id={self.request_id}")
        return f"{base} ({', '.join(suffix)})" if suffix else base


class MassiveAuthError(MassiveAPIError):
    """401/403 from the API: the key is missing, unknown, or lacks entitlement."""
