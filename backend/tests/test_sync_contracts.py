from datetime import UTC, datetime

import pytest

from app.sync.contracts import SyncError, utc, validate_cursor, validate_limit


@pytest.mark.parametrize("value", [-1, True, "2", None])
def test_invalid_sync_cursor(value):
    with pytest.raises(SyncError):
        validate_cursor(value)


@pytest.mark.parametrize("value", [0, 101, True, "25", None])
def test_page_bounds(value):
    with pytest.raises(SyncError):
        validate_limit(value)


def test_timestamps_require_explicit_timezone():
    with pytest.raises(SyncError):
        utc(datetime(2026, 9, 12))  # noqa: DTZ001 -- regression requires a naive timestamp
    value = datetime(2026, 9, 12, tzinfo=UTC)
    assert utc(value) == value
