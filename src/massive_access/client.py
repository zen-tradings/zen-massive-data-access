"""Authenticated HTTP client for the Massive REST API.

Scope (Phase 1): auth, timeouts, retry with jittered exponential backoff on
429/5xx and transport errors, cursor pagination via ``next_url``, and request
logging. This layer knows nothing about specific endpoints or timespans — that
lives in ``massive_access.endpoints``, so future minute-bar or options frame
builders reuse this client unchanged.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator, Mapping
from typing import Any

import httpx

from .config import get_api_key, signup_hint
from .errors import MassiveAPIError, MassiveAuthError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.massive.com"

# Retryable statuses: 429 (plan rate limit) and transient 5xx.
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=5.0)


class MassiveClient:
    """Synchronous REST client for the Massive API.

    Auth: ``Authorization: Bearer <key>``. The key is resolved from the
    ``api_key`` argument or the ``MASSIVE_API_KEY`` env var.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        backoff_cap: float = 30.0,
        timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
        sleep_fn: Callable[[float], None] = time.sleep,
        httpx_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = get_api_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._sleep = sleep_fn
        if httpx_client is not None:
            self._client = httpx_client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                base_url=self._base_url,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=timeout,
            )
            self._owns_client = True

    # -- public API -------------------------------------------------------

    def get_json(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        """GET one page; returns the parsed JSON body (object or array)."""
        return self._request("GET", path, params=params)

    def iter_pages(
        self, path: str, *, params: Mapping[str, Any] | None = None
    ) -> Iterator[dict[str, Any]]:
        """Yield each JSON page, following cursor pagination (``next_url``).

        Query params are only attached to the first request; ``next_url``
        already carries the cursor for subsequent pages.
        """
        url: str | None = path
        while url is not None:
            page = self._request("GET", url, params=params)
            params = None
            if not isinstance(page, dict):
                raise MassiveAPIError(f"expected object JSON from {url}, got {type(page)}")
            yield page
            next_url = page.get("next_url")
            url = self._validated_next_url(str(next_url)) if next_url else None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MassiveClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- internals --------------------------------------------------------

    def _validated_next_url(self, next_url: str) -> str:
        if not next_url.startswith(self._base_url):
            raise MassiveAPIError(f"refusing to follow off-host next_url: {next_url!r}")
        return next_url

    def _compute_wait(self, resp: httpx.Response | None, attempt: int) -> float:
        # Honor Retry-After (429s) when present; otherwise full-jitter backoff.
        if resp is not None:
            retry_after = resp.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(float(retry_after), self._backoff_cap)
                except ValueError:
                    pass
        ceiling = min(self._backoff_cap, self._backoff_base * (2**attempt))
        return random.uniform(0.0, ceiling)

    def _request(self, method: str, url: str, *, params: Mapping[str, Any] | None = None) -> Any:
        last_error: MassiveAPIError | None = None
        for attempt in range(self._max_retries + 1):
            resp: httpx.Response | None = None
            try:
                resp = self._client.request(method, url, params=params)
            except httpx.TransportError as exc:  # connect/read timeouts, DNS, ...
                wait = self._compute_wait(None, attempt)
                if attempt < self._max_retries:
                    logger.warning(
                        "%s %s transport error (%s); retry %d/%d in %.2fs",
                        method, url, exc, attempt + 1, self._max_retries, wait,
                    )
                    self._sleep(wait)
                    continue
                last_error = MassiveAPIError(f"transport error on {method} {url}: {exc}")
                break

            body: dict[str, Any] = {}
            request_id: str | None = resp.headers.get("X-Request-Id")
            if resp.status_code >= 400:
                try:
                    parsed = resp.json() if resp.content else {}
                except ValueError:
                    parsed = {}
                if isinstance(parsed, dict):
                    body = parsed
                request_id = body.get("request_id") or request_id

            if resp.status_code in RETRYABLE_STATUSES and attempt < self._max_retries:
                wait = self._compute_wait(resp, attempt)
                logger.warning(
                    "%s %s -> %d (request_id=%s); retry %d/%d in %.2fs",
                    method, url, resp.status_code, request_id,
                    attempt + 1, self._max_retries, wait,
                )
                self._sleep(wait)
                continue

            if resp.status_code >= 400:
                detail = (
                    body.get("error") or body.get("message") or resp.reason_phrase or "API error"
                )
                if resp.status_code in (401, 403):
                    hint = signup_hint()
                    raise MassiveAuthError(
                        f"Massive API auth failed: {detail}. Check MASSIVE_API_KEY. {hint}",
                        status=resp.status_code,
                        request_id=request_id,
                    )
                raise MassiveAPIError(
                    f"Massive API request failed: {detail}",
                    status=resp.status_code,
                    request_id=request_id,
                )

            logger.debug(
                "%s %s -> %d request_id=%s",
                method, url, resp.status_code, request_id,
            )
            try:
                return resp.json()
            except ValueError as exc:
                raise MassiveAPIError(
                    f"invalid JSON in response to {method} {url}",
                    status=resp.status_code,
                    request_id=request_id,
                ) from exc

        if last_error is not None:
            raise last_error
        raise MassiveAPIError(f"retries exhausted for {method} {url}")

