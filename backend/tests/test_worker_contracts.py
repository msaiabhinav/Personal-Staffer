from types import SimpleNamespace

import pytest

from app.workers.schedule import source_interval
from app.workers.service import result_state


@pytest.mark.parametrize(
    "state,expected",
    [
        ("UNAVAILABLE", "RETRY"),
        ("FAILED", "RETRY"),
        ("RATE_LIMITED", "RETRY"),
        ("PARTIAL", "PARTIAL"),
        ("NOT_CONFIGURED", "NOT_CONFIGURED"),
        ("RECONNECT_REQUIRED", "RECONNECT_REQUIRED"),
        ("PENDING_BUDGET", "DEFERRED"),
        ("HEALTHY", "SUCCEEDED"),
        ("PARTIALLY_FOUND", "SUCCEEDED"),
    ],
)
def test_provider_states_never_become_false_success(state, expected):
    assert result_state({"state": state}, 1) == expected


def test_provider_retries_are_bounded():
    assert result_state({"state": "RATE_LIMITED"}, 3) == "FAILED"
    assert result_state({"state": "PENDING_BUDGET"}, 3) == "DEFERRED"
    assert result_state({"state": "NEW_UNRECOGNIZED_FAILURE"}, 1) == "RETRY"


@pytest.mark.parametrize(
    "tags,interval",
    [
        (["WATCHLIST"], 900),
        (["CONNECTICUT"], 1800),
        (["UNIVERSITY"], 3600),
        (["NYC"], 3600),
        (["BAY_AREA"], 3600),
        ([], 14400),
    ],
)
def test_priority_registry_cadences(tags, interval):
    assert source_interval(SimpleNamespace(pool_tags=tags, connector_type="ashby")) == interval
