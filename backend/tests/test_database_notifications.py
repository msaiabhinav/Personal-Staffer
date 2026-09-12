"""Real PostgreSQL tests; set TEST_DATABASE_URL to enable an isolated schema."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import pytest
import test_database_core
from sqlalchemy import func, select
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres
engine = test_database_core.pg_engine  # Exercise production migrations, not metadata-only tables.


@pytest.fixture
def users(engine):
    from app.db.models import User

    with Session(engine) as session, session.begin():
        first = User(google_subject="test-a", verified_email="a@example.test", display_name="A")
        second = User(google_subject="test-b", verified_email="b@example.test", display_name="B")
        session.add_all([first, second])
        session.flush()
        return first.id, second.id


def make_notification(session, user_id, key="one"):
    from app.notifications.service import create_notification

    return create_notification(session, user_id, "JOB_ALERT", "JOB", uuid4(), "A job", "A retained alert", key)


def test_at45_at46_at51_deduplicated_durable_inbox_and_outbox(engine, users):
    from app.db.models import Notification, OutboxEvent, UserChange
    from app.notifications.service import create_notification, list_notifications, unread_count

    user_id = users[0]
    with Session(engine) as session, session.begin():
        row = make_notification(session, user_id)
        first_id = row.id
        result = create_notification(
            session, user_id, row.notification_type, row.target_type, row.target_id, row.title, row.body, "one"
        )
        assert result.id == first_id
    with Session(engine) as session, session.begin():
        row = session.get(Notification, first_id)
        replay = create_notification(
            session, user_id, row.notification_type, row.target_type, row.target_id, row.title, row.body, "one"
        )
        assert replay.id == first_id
        assert unread_count(session, user_id) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
        assert session.scalar(select(func.count()).select_from(UserChange)) == 1
        assert len(list_notifications(session, user_id)["items"]) == 1


def test_at44_at45_at53_exact_open_and_owned_read_state(engine, users):
    from app.notifications.contracts import NotificationError
    from app.notifications.service import open_notification, set_read

    with Session(engine) as session, session.begin():
        row = make_notification(session, users[0])
        identifier, target_id = row.id, row.target_id
    with Session(engine) as session, session.begin():
        with pytest.raises(NotificationError) as err:
            open_notification(session, users[1], identifier)
        assert err.value.status_code == 404
    with Session(engine) as session, session.begin():
        first = open_notification(session, users[0], identifier)
        repeated = open_notification(session, users[0], identifier)
        assert first["destination"] == f"personalstaffer://jobs/{target_id}"
        assert first == repeated
        assert first["unread_count"] == 0
        unread = set_read(session, users[0], identifier, False, expected_revision=first["revision"])
        assert unread["unread_count"] == 1


def test_at50_sync_tombstone_and_stale_cursor(engine, users):
    from app.sync.contracts import SyncError
    from app.sync.service import changes_page, record_change

    with Session(engine) as session, session.begin():
        initial = record_change(session, users[0], "application", uuid4(), 1)
        initial_cursor = initial.cursor
        removed = record_change(session, users[0], "application", initial.entity_id, 2, tombstone=True)
        removed_cursor = removed.cursor
        second_user = record_change(session, users[1], "application", uuid4(), 1)
        other_cursor = second_user.cursor
    with Session(engine) as session:
        page = changes_page(session, users[0], initial_cursor)
        assert page["items"][0]["tombstone"] is True
        assert page["items"][0]["revision"] == 2
        assert page["next_cursor"] == removed_cursor
        with pytest.raises(SyncError) as err:
            changes_page(session, users[0], other_cursor)
        assert err.value.code == "RESYNC_REQUIRED"
        with pytest.raises(SyncError) as err:
            changes_page(session, users[0], initial_cursor, now=datetime.now(UTC) + timedelta(days=91))
        assert err.value.code == "RESYNC_REQUIRED"


def test_cursor_commit_order_is_serialized_per_user(engine, users):
    from app.sync.service import changes_page, record_change

    first_has_lock, second_started, release_first = Event(), Event(), Event()

    def first_writer():
        with Session(engine) as session, session.begin():
            row = record_change(session, users[0], "application", uuid4(), 1)
            first_has_lock.set()
            assert release_first.wait(5)
            return row.cursor

    def second_writer():
        assert first_has_lock.wait(5)
        with Session(engine) as session, session.begin():
            second_started.set()
            row = record_change(session, users[0], "application", uuid4(), 1)
            return row.cursor

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(first_writer), executor.submit(second_writer)
        assert second_started.wait(5)
        with Session(engine) as session:
            assert changes_page(session, users[0], 0)["items"] == []
        release_first.set()
        cursor1, cursor2 = first.result(5), second.result(5)
    assert cursor1 < cursor2
    with Session(engine) as session:
        assert [row["cursor"] for row in changes_page(session, users[0], 0)["items"]] == [cursor1, cursor2]


def test_at50_snapshot_is_frozen_owned_and_followed_by_tombstone(engine, users):
    from app.db.models import Application
    from app.sync.contracts import SyncError
    from app.sync.service import changes_page, lock_user, record_change
    from app.sync.snapshot import snapshot_page, start_snapshot

    user_id, other_id = users
    with Session(engine) as session, session.begin():
        app = Application(
            user_id=user_id,
            title="Analyst",
            company="Fixture company",
            applied_at=datetime.now(UTC),
            notes="Original note",
        )
        session.add(app)
        session.flush()
        application_id = app.id
        first = start_snapshot(session, user_id, limit=1)
        snapshot_id = first["snapshot_id"]
        boundary = first["boundary_cursor"]
    with Session(engine) as session, session.begin():
        lock_user(session, user_id)
        app = session.get(Application, application_id)
        app.voided_at = datetime.now(UTC)
        app.notes = "Corrected after snapshot"
        app.revision += 1
        record_change(session, user_id, "applications", app.id, app.revision, tombstone=True)
    with Session(engine) as session:
        frozen = snapshot_page(session, user_id, snapshot_id, limit=100)
        frozen_app = next(row for row in frozen["items"] if row["entity_type"] == "applications")
        assert frozen_app["data"]["notes"] == "Original note"
        assert frozen_app["tombstone"] is False
        delta = changes_page(session, user_id, boundary)
        assert delta["items"][0]["tombstone"] is True
        assert delta["items"][0]["revision"] > frozen_app["revision"]
        with pytest.raises(SyncError) as err:
            snapshot_page(session, other_id, snapshot_id)
        assert err.value.status_code == 404
        with pytest.raises(SyncError) as err:
            snapshot_page(session, user_id, snapshot_id, now=datetime.now(UTC) + timedelta(hours=2))
        assert err.value.code == "RESYNC_REQUIRED"


def test_inbox_cursor_has_stable_order_and_is_user_scoped(engine, users):
    from app.notifications.contracts import NotificationError
    from app.notifications.service import list_notifications

    with Session(engine) as session, session.begin():
        first, second = make_notification(session, users[0], "first"), make_notification(session, users[0], "second")
        first_id, second_id = first.id, second.id
        foreign = make_notification(session, users[1], "foreign")
        foreign_id = foreign.id
    with Session(engine) as session:
        page1 = list_notifications(session, users[0], limit=1)
        page2 = list_notifications(session, users[0], limit=1, cursor=page1["next_cursor"])
        assert page1["has_more"] is True
        assert page2["has_more"] is False
        assert {page1["items"][0]["id"], page2["items"][0]["id"]} == {str(first_id), str(second_id)}
        with pytest.raises(NotificationError) as err:
            list_notifications(session, users[0], cursor=foreign_id)
        assert err.value.status_code == 404
