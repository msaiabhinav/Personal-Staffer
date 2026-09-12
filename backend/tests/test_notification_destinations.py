from uuid import uuid4

import pytest

from app.notifications.contracts import NotificationError, destination


@pytest.mark.parametrize(
    "kind,path",
    [
        ("JOB", "jobs"),
        ("APPLICATION", "applications"),
        ("REVIEW", "reviews"),
        ("REPORT", "reports"),
        ("SEARCH_RUN", "search-runs"),
    ],
)
def test_exact_native_destination(kind, path):
    identifier = uuid4()
    result = destination(kind, identifier)
    assert result["route"] == f"/{path}/{identifier}"
    assert result["deep_link"] == f"personalstaffer://{path}/{identifier}"
    assert result["target_type"] == path
    assert destination(path, str(identifier)) == result


@pytest.mark.parametrize(
    "kind,identifier",
    [
        ("https://evil.test", str(uuid4())),
        ("JOB", "../settings"),
        ("JOB", f"{uuid4()}?url=https://evil.test"),
        ("JOB", "javascript:alert(1)"),
        ("unknown", str(uuid4())),
    ],
)
def test_untrusted_uri_does_not_become_destination(kind, identifier):
    with pytest.raises(NotificationError) as exc:
        destination(kind, identifier)
    assert exc.value.code == "INVALID_DESTINATION"


def test_notification_projection_retains_exact_authoritative_destination():
    from datetime import UTC, datetime

    from app.db.models import Notification
    from app.notifications.service import as_dict

    target_id = uuid4()
    row = Notification(
        id=uuid4(),
        user_id=uuid4(),
        notification_type="EMAIL_REVIEW",
        target_type="reviews",
        target_id=target_id,
        title="Review email",
        body="More than one application may match.",
        event_dedupe_key="email:test",
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        revision=1,
    )
    result = as_dict(row)
    assert result["destination"] == f"personalstaffer://reviews/{target_id}"
    assert result["type"] == "EMAIL_REVIEW"
    assert result["read_at"] is None
    assert "event_dedupe_key" not in result
