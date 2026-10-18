from __future__ import annotations

import json
from pathlib import Path

import pytest

from massive_access import MassiveClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fixture():
    return load_fixture


@pytest.fixture
def fast_client() -> MassiveClient:
    """Client that never actually sleeps during backoff."""
    return MassiveClient(api_key="test-key", sleep_fn=lambda *_: None)
