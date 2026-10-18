from __future__ import annotations

import pytest

from massive_access import MassiveClient, MissingAPIKeyError, get_api_key
from massive_access.config import ENV_API_KEY


def test_missing_key_raises_with_signup_hint(monkeypatch):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    with pytest.raises(MissingAPIKeyError) as exc:
        get_api_key()
    assert ENV_API_KEY in str(exc.value)
    assert "massive.com" in str(exc.value)


def test_env_key_resolves(monkeypatch):
    monkeypatch.setenv(ENV_API_KEY, "from-env")
    assert get_api_key() == "from-env"


def test_blank_env_counts_as_missing(monkeypatch):
    monkeypatch.setenv(ENV_API_KEY, "   ")
    with pytest.raises(MissingAPIKeyError):
        get_api_key()


def test_explicit_key_wins_over_env(monkeypatch):
    monkeypatch.setenv(ENV_API_KEY, "from-env")
    assert get_api_key("explicit") == "explicit"


def test_explicit_empty_string_falls_back_to_error(monkeypatch):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    with pytest.raises(MissingAPIKeyError):
        get_api_key("")


def test_client_requires_key(monkeypatch):
    monkeypatch.delenv(ENV_API_KEY, raising=False)
    with pytest.raises(MissingAPIKeyError):
        MassiveClient()
