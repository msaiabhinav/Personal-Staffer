from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.email.gmail import HistoryExpired
from app.email.orchestration import RecordedPage


def test_prefetched_page_replays_without_network_and_refuses_changed_plan():
    calls = []
    api = SimpleNamespace(message=lambda identifier: calls.append(identifier) or {"id": identifier})
    page = RecordedPage()
    assert page.record(api, "message", "one") == {"id": "one"}
    api.message = lambda _: pytest.fail("network during database commit")
    assert page.message("one") == {"id": "one"}
    assert calls == ["one"]
    with pytest.raises(RuntimeError):
        page.message("unfetched")


def test_expired_history_and_frozen_backfill_args_preserved():
    def expired(*_):
        raise HistoryExpired()

    page = RecordedPage()
    api = SimpleNamespace(history=expired, backfill=lambda *args: {"after": args[0]})
    with pytest.raises(HistoryExpired):
        page.record(api, "history", "old", None, None)
    with pytest.raises(HistoryExpired):
        page.history("old", None, None)
    stamp = datetime(2026, 9, 12, tzinfo=UTC)
    page.record(api, "backfill", stamp, None, None)
    assert page.backfill(stamp, None, None) == {"after": stamp}
