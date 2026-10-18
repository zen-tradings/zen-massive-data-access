"""Environment configuration.

Rule (per plan): the API key comes from the ``MASSIVE_API_KEY`` env var or an
explicit argument. It is never loaded from a ``.env`` file implicitly — the
operator owns the shell environment on the servers.
"""

from __future__ import annotations

import os

from .errors import MissingAPIKeyError

ENV_API_KEY = "MASSIVE_API_KEY"

_SIGNUP_HINT = (
    "Get an API key at https://massive.com and set it via "
    f"`export {ENV_API_KEY}=<key>` in the service's shell environment."
)

MISSING_KEY_MESSAGE = (
    f"{ENV_API_KEY} is not set. {_SIGNUP_HINT}"
)


def get_api_key(explicit: str | None = None) -> str:
    """Resolve the API key: explicit argument wins, else the environment.

    Raises ``MissingAPIKeyError`` with a signup hint when unset or blank.
    """
    key = (explicit if explicit is not None else os.environ.get(ENV_API_KEY, "")) or ""
    key = key.strip()
    if not key:
        raise MissingAPIKeyError(MISSING_KEY_MESSAGE)
    return key


def signup_hint() -> str:
    """Signup hint text used in auth error messages."""
    return _SIGNUP_HINT
