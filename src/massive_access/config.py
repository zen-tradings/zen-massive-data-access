"""API key configuration.

Resolution order (first wins):
1. explicit argument (``MassiveClient(api_key=...)``)
2. ``MASSIVE_API_KEY`` env var
3. a key file: ``$MASSIVE_CONFIG_FILE``, or ``~/.config/massive-access/key``,
   or ``/etc/massive-access/key`` (last one for the server)

The key file sits outside any repo. Plain text, one of:
- just the key on one line
- ``MASSIVE_API_KEY=<key>`` (systemd EnvironmentFile-compatible)

Blank lines and ``#`` comments are ignored. It should be chmod 600.
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import MissingAPIKeyError

ENV_API_KEY = "MASSIVE_API_KEY"
ENV_CONFIG_FILE = "MASSIVE_CONFIG_FILE"

_SIGNUP_HINT = (
    "Get an API key at https://massive.com and set it via "
    f"`export {ENV_API_KEY}=<key>`, or put it in a key file (see README)."
)


def key_file_candidates() -> list[Path]:
    """Where to look for a key file, in order."""
    candidates: list[Path] = []
    if explicit := os.environ.get(ENV_CONFIG_FILE):
        candidates.append(Path(explicit))
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    candidates.append(Path(xdg) / "massive-access" / "key")
    candidates.append(Path("/etc/massive-access/key"))
    return candidates


def _read_key_file(path: Path) -> str | None:
    """Read the key from one file, or None if absent/unusable/blank."""
    try:
        text = path.read_text()
    except OSError:  # missing, unreadable, wrong permissions, ...
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            name, _, value = line.partition("=")
            if name.strip() in (ENV_API_KEY, "KEY"):
                value = value.strip().strip('"').strip("'")
                if value:
                    return value
                continue  # ``MASSIVE_API_KEY=`` empty: keep looking
        else:
            return line.strip('"').strip("'")  # bare key on its own line
    return None


def find_api_key() -> tuple[str, str]:
    """Resolve the key without raising.

    Returns ``(key, source)`` where source describes where it came from
    (``"environment"``, ``"<path>"``, or ``"argument"``), or ``("", "")`` if
    not found anywhere.
    """
    if value := os.environ.get(ENV_API_KEY, "").strip():
        return value, "environment"
    for path in key_file_candidates():
        if key := _read_key_file(path):
            return key, str(path)
    return "", ""


def get_api_key(explicit: str | None = None) -> str:
    """Resolve the API key: explicit argument > env var > key file.

    Raises ``MissingAPIKeyError`` with a signup hint when unset or blank.
    """
    key = (explicit if explicit is not None else "") or ""
    key = key.strip()
    if key:
        return key
    key, _ = find_api_key()
    if key:
        return key
    raise MissingAPIKeyError(
        f"{ENV_API_KEY} is not set and no key file was found at "
        + ", ".join(str(p) for p in key_file_candidates())
        + f". {_SIGNUP_HINT}"
    )


def signup_hint() -> str:
    """Signup hint text used in auth error messages."""
    return _SIGNUP_HINT
