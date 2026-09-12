"""Suite-wide isolation from the host's owner configuration.

The documented in-container `pytest` command inherits the Compose env file. Owner-specific
policy choices (ADR 0003 informational E-Verify) must not change what the specification
tests assert, so the gate is pinned to the specification default for every test unless a
test sets it explicitly.
"""

import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _specification_policy_env(monkeypatch):
    monkeypatch.setenv("EVERIFY_GATE", "REQUIRED")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
