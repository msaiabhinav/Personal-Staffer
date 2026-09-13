"""Execute with TEST_DATABASE_URL. Uses migrations and actual concurrent connections."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker
from test_database_core import pg_engine as pg_engine  # noqa: PLC0414 - Re-export shared pytest fixture.

from app.db.models import OutboxEvent, WorkItem
from app.workers.service import dispatch_once, enqueue, execute_work, reconcile

pytestmark = pytest.mark.postgres


def test_duplicate_work_after_commit_before_ack_has_single_effect(pg_engine):
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        work = enqueue(session, "TEST", {}, "one-logical-task")
        identifier = work.id

    def handler(session, task_type, payload):
        session.add(OutboxEvent(event_key="domain-result", event_type="TEST", payload={}))
        return {"worked": True}

    assert execute_work(factory, identifier, handler) == "SUCCEEDED"
    assert execute_work(factory, identifier, handler) == "NOOP"
    with factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(OutboxEvent).where(OutboxEvent.event_key == "domain-result")
            )
            == 1
        )


def test_broker_loss_and_crash_reconcile_both_work_and_outbox(pg_engine):
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    now = datetime.now(UTC)
    with factory() as session, session.begin():
        work = enqueue(session, "TEST", {}, "lost-message")
        work.state = "RUNNING"
        work.lease_expires_at = now - timedelta(minutes=1)
        work.next_attempt_at = now - timedelta(minutes=1)
        lost = OutboxEvent(
            event_key="notification-lost",
            event_type="NOTIFICATION",
            payload={},
            state="DISPATCHED",
            dispatched_at=now - timedelta(minutes=11),
        )
        session.add(lost)
        assert reconcile(session, now=now) == 1
        assert work.state == "QUEUED"
        assert lost.state == "RETRY"
    published = []
    assert dispatch_once(factory, published.append, now=now) >= 2
    assert published


def test_failed_publish_keeps_durable_retry(pg_engine):
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        enqueue(session, "TEST", {}, "broker-down")

    def broken(_):
        raise ConnectionError("broker unavailable")

    assert dispatch_once(factory, broken) == 0
    with factory() as session:
        event = session.scalar(select(OutboxEvent))
        assert event.state == "RETRY"
        assert event.last_error == "ConnectionError"


def test_fast_worker_cannot_be_regressed_by_dispatcher(pg_engine):
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        enqueue(session, "TEST", {}, "fast-worker")

    def publish(identifier):
        with factory() as session, session.begin():
            event = session.get(OutboxEvent, UUID(identifier))
            event.state = "PROCESSED"

    assert dispatch_once(factory, publish) == 1
    with factory() as session:
        assert session.scalar(select(OutboxEvent)).state == "PROCESSED"


def test_retryable_provider_result_commits_evidence_and_retries(pg_engine):
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        identifier = enqueue(session, "TEST", {}, "provider-retry").id

    def handler(session, task_type, payload):
        session.add(OutboxEvent(event_key="failed-provider-evidence", event_type="TEST", payload={}))
        return {"state": "UNAVAILABLE"}

    assert execute_work(factory, identifier, handler) == "RETRY"
    assert execute_work(factory, identifier, handler) == "NOT_DUE"
    with factory() as session:
        assert session.scalar(select(OutboxEvent).where(OutboxEvent.event_key == "failed-provider-evidence"))
        work = session.get(WorkItem, identifier)
        assert work.result["state"] == "UNAVAILABLE"
        assert work.completed_at is None


def test_fcm_failure_retries_preserves_inbox_and_caps_attempts(pg_engine, monkeypatch):
    from cryptography.fernet import Fernet

    from app.auth.crypto import SecretBox
    from app.config.settings import Settings
    from app.db.models import Device, Notification, NotificationDelivery, User
    from app.notifications import delivery

    settings = Settings(token_encryption_key=Fernet.generate_key().decode())
    monkeypatch.setattr(delivery, "get_settings", lambda: settings)
    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        user = User(google_subject="delivery-owner", verified_email="owner@example.test")
        session.add(user)
        session.flush()
        device = Device(
            user_id=user.id,
            platform="ANDROID",
            push_token_encrypted=SecretBox(settings.token_encryption_key).encrypt("fcm-token"),
        )
        notification = Notification(
            user_id=user.id,
            notification_type="JOB",
            target_type="jobs",
            target_id=__import__("uuid").uuid4(),
            title="A retained alert",
            body="Update",
            event_dedupe_key="retry-notification",
        )
        session.add_all([device, notification])
        session.flush()
        identifier = notification.id

    class Broken:
        def send(self, token, notification):
            raise ConnectionError("Provider unreachable")

    for expected in ["RETRY", "RETRY", "FAILED", "FAILED"]:
        with factory() as session, session.begin():
            assert delivery.deliver(session, identifier, sender=Broken())["state"] == expected
    with factory() as session:
        assert session.get(Notification, identifier)
        assert session.scalar(select(NotificationDelivery)).attempts == 3


def test_dispatch_publishes_mail_sync_and_inbox_ahead_of_source_scans(pg_engine):
    from app.workers.service import event_priority

    factory = sessionmaker(pg_engine, expire_on_commit=False)
    with factory() as session, session.begin():
        scan = enqueue(session, "SEARCH_SOURCE", {"source_id": "s", "user_id": "u"}, "prio-scan")
        prep = enqueue(
            session,
            "SEARCH_SOURCE",
            {"source_id": "s", "user_id": "u", "report_preparation": "2026-09-13"},
            "prio-prep",
        )
        mail = enqueue(session, "GMAIL_SYNC", {"user_id": "u"}, "prio-mail")
        for name, work in [("scan", scan), ("prep", prep), ("mail", mail)]:
            session.add(OutboxEvent(event_key=f"prio:{name}", event_type="WORK", payload={"work_id": str(work.id)}))
        session.add(
            OutboxEvent(event_key="prio:inbox", event_type="notification.created", payload={"notification_id": "n"})
        )
        session.flush()
        rows = {e.event_key: event_priority(session, e) for e in session.scalars(select(OutboxEvent))}
    assert rows["prio:inbox"] == 0 and rows["prio:mail"] == 1 and rows["prio:prep"] == 3 and rows["prio:scan"] == 6
    published = []
    later = datetime.now(UTC) + timedelta(seconds=1)
    assert dispatch_once(factory, lambda event_id, priority: published.append(priority), now=later) >= 4
    assert {0, 1, 3, 6} <= set(published)
    # A single-argument publisher (older callers/tests) still works.
    with factory() as session, session.begin():
        session.add(OutboxEvent(event_key="prio:plain", event_type="notification.created", payload={}))
    plain = []
    assert dispatch_once(factory, plain.append, now=datetime.now(UTC) + timedelta(seconds=1)) == 1
