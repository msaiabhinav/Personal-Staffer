"""Authentication and connector effects tested against isolated real PostgreSQL.

Run with TEST_DATABASE_URL; SQLite is deliberately unsupported.
"""

import base64
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
import test_database_core
from cryptography.fernet import Fernet
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.errors import DomainError
from app.applications.service import correct_event, lock_user
from app.auth.crypto import challenge, digest
from app.auth.service import begin_intent, enroll_owner, redeem_intent, rotate_session
from app.config.settings import Settings
from app.db.models import (
    Application,
    ApplicationEvent,
    AppSession,
    EmailApplicationLink,
    EmailMessage,
    EmployerGroup,
    EnrichmentRun,
    GmailConnection,
    GmailSyncState,
    InitialDelivery,
    Job,
    LoginIntent,
    Notification,
    ReviewItem,
    User,
    utcnow,
)
from app.email.gmail import GmailUnavailable, HistoryExpired, MessageBatch
from app.email.service import process_message, synchronize
from app.people.discovery import SearchResult
from app.people.service import enrich, job_people

pytestmark = pytest.mark.postgres
engine = test_database_core.pg_engine  # Actual Alembic migrations, including retained-history guards.


@pytest.fixture
def settings():
    return Settings(
        google_client_id="client",
        google_client_secret="secret",
        google_redirect_uri="https://staffer.example/callback",
        gmail_redirect_uri="https://staffer.example/gmail/callback",
        owner_allowed_email="owner@example.test",
        token_encryption_key=Fernet.generate_key().decode(),
        people_search_provider="brave",
        people_search_api_key="key",
    )


@pytest.fixture
def owner(engine):
    with Session(engine) as session, session.begin():
        user = User(id=uuid4(), google_subject="subject", verified_email="owner@example.test", display_name="Owner")
        session.add(user)
        session.flush()
        return user.id


def seed_application(session, owner, title="Data Analyst"):
    app = Application(
        id=uuid4(),
        user_id=owner,
        title=title,
        company="Example Corporation",
        applied_at=utcnow() - timedelta(days=3),
        current_status="APPLIED",
        revision=1,
    )
    session.add(app)
    session.flush()
    session.add(
        ApplicationEvent(
            id=uuid4(),
            application_id=app.id,
            event_type="APPLIED",
            status="APPLIED",
            effective_at=app.applied_at,
            operation_id="original-apply",
        )
    )
    session.flush()
    return app


def seed_connection(session, owner):
    conn = GmailConnection(
        id=uuid4(),
        user_id=owner,
        google_identity="owner@example.test",
        refresh_token_encrypted="test-encrypted",
        granted_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        sync_health="CONNECTED",
    )
    session.add(conn)
    session.flush()
    return conn


def message(identifier="abcd", body="Your application was rejected for Data Analyst at Example Corporation"):
    return {
        "id": identifier,
        "threadId": "thread1",
        "internalDate": str(int(utcnow().timestamp() * 1000)),
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Application update"},
                {"name": "From", "value": "recruiting@shared-ats.example"},
                {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass header.from=shared-ats.example"},
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


def test_at53_device_bound_flow_and_rotating_hashed_sessions(engine, owner, settings):
    device_id, verifier = uuid4(), "v" * 64
    provider = SimpleNamespace(authorize=lambda *args: "https://accounts.google.com/auth")
    payload = SimpleNamespace(
        device_id=device_id, platform="WINDOWS", device_label="Test PC", challenge=challenge(verifier)
    )
    with Session(engine) as session, session.begin():
        started = begin_intent(session, settings, payload, provider=provider)
        from uuid import UUID

        flow_id = UUID(started["flow_id"])
        intent = session.get(LoginIntent, flow_id)
        intent.completed_at, intent.user_id = utcnow(), owner
    with Session(engine) as session:
        with pytest.raises(DomainError) as error:
            redeem_intent(session, settings, flow_id, uuid4(), verifier)
        assert error.value.code == "DEVICE_VERIFIER_MISMATCH"
    with Session(engine) as session, session.begin():
        tokens = redeem_intent(session, settings, flow_id, device_id, verifier)
        stored = session.scalar(select(AppSession))
        assert stored.refresh_token_hash == digest(tokens["refresh_token"])
        assert stored.access_token_hash == digest(tokens["access_token"])
    with Session(engine) as session, session.begin():
        rotated = rotate_session(session, settings, tokens["refresh_token"], device_id)
        assert rotated["refresh_token"] != tokens["refresh_token"]
    with Session(engine) as session:
        with pytest.raises(DomainError) as error:
            rotate_session(session, settings, tokens["refresh_token"], device_id)
        assert error.value.code == "REFRESH_TOKEN_REUSED"
    with Session(engine) as session:
        assert all(row.revoked_at for row in session.scalars(select(AppSession)))


def test_owner_allowlist_and_stable_subject(engine, settings):
    with Session(engine) as session:
        with pytest.raises(DomainError):
            enroll_owner(session, settings, {"sub": "wrong", "email": "other@example.test"})
        session.rollback()
        owner = enroll_owner(session, settings, {"sub": "stable", "email": "owner@example.test", "name": "Name"})
        identifier = owner.id
        session.commit()
    with Session(engine) as session, session.begin():
        owner = enroll_owner(session, settings, {"sub": "stable", "email": "changed@example.test"})
        assert owner.id == identifier
    with Session(engine) as session, pytest.raises(DomainError):
        enroll_owner(session, settings, {"sub": "attacker", "email": "owner@example.test"})


def test_at38_at40_at41_email_effect_atomic_idempotent_and_correctable(engine, owner):
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        app = seed_application(session, owner)
        conn = seed_connection(session, owner)
        app_id, conn_id = app.id, conn.id
        reviewed_mail = EmailMessage(
            id=uuid4(),
            connection_id=conn.id,
            gmail_message_id="reviewed-sender",
            thread_id="reviewed-thread",
            sender="recruiting@shared-ats.example",
            subject="Previously reviewed sender",
            excerpt="Synthetic manual review",
            received_at=utcnow() - timedelta(days=1),
            classification="USER_REVIEWED",
            evidence={"sender_security": {"from_address": "recruiting@shared-ats.example"}},
        )
        session.add(reviewed_mail)
        session.flush()
        session.add(
            EmailApplicationLink(
                email_id=reviewed_mail.id,
                application_id=app.id,
                match_state="USER_CONFIRMED",
                reviewed_at=utcnow(),
                evidence={"synthetic_manual_review": True},
            )
        )
        session.flush()
        assert process_message(session, conn, message()) == "APPLIED"
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        assert process_message(session, session.get(GmailConnection, conn_id), message()) == "DUPLICATE"
        app = session.get(Application, app_id)
        assert app.current_status == "REJECTED"
        assert session.scalar(select(func.count()).select_from(Notification)) == 1
        link = session.scalar(select(EmailApplicationLink).where(EmailApplicationLink.event_id.is_not(None)))
        correct_event(
            session,
            owner,
            app.id,
            SimpleNamespace(
                event_id=link.event_id,
                expected_revision=app.revision,
                action="UNDO_STATUS",
                reason="Wrong interpretation",
            ),
            "correct-email",
        )
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        assert process_message(session, session.get(GmailConnection, conn_id), message()) == "DUPLICATE"
        assert session.get(Application, app_id).current_status == "APPLIED"
        assert session.scalar(
            select(EmailApplicationLink).where(EmailApplicationLink.event_id.is_not(None))
        ).corrected_at


def test_at39_ambiguous_email_creates_review_no_status_change(engine, owner):
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        seed_application(session, owner)
        seed_application(session, owner)
        conn = seed_connection(session, owner)
        assert process_message(session, conn, message()) == "REVIEW"
        assert all(app.current_status == "APPLIED" for app in session.scalars(select(Application)))
        session.flush()
        assert session.scalar(select(func.count()).select_from(ReviewItem)) == 1


class FakeGmail:
    def __init__(self, fail_second=False, expired=False, next_page=False):
        self.fail_second, self.expired, self.next_page = fail_second, expired, next_page
        self.profile_called = False

    def profile(self):
        self.profile_called = True
        return {"historyId": "baseline200"}

    def history(self, cursor, page_token=None, label=None):
        if self.expired:
            raise HistoryExpired()
        return MessageBatch(
            ("abcd", "efgh") if self.fail_second else ("abcd",), "page2" if self.next_page else None, "300"
        )

    def backfill(self, after, page_token=None, label=None):
        assert self.profile_called
        assert utcnow() - after < timedelta(days=31)
        return MessageBatch(("abcd",), None, None)

    def message(self, identifier):
        if self.fail_second and identifier == "efgh":
            raise GmailUnavailable("UNAVAILABLE", "Temporary test failure")
        return message(identifier)


def test_at43_sync_failure_rolls_back_cursor_and_email_effects(engine, owner, settings):
    with Session(engine) as session, session.begin():
        seed_application(session, owner)
        conn = seed_connection(session, owner)
        session.add(GmailSyncState(connection_id=conn.id, history_cursor="100"))
    with Session(engine) as session:
        with pytest.raises(GmailUnavailable):
            synchronize(session, owner, settings, api=FakeGmail(fail_second=True))
        session.rollback()
    with Session(engine) as session:
        assert session.scalar(select(GmailSyncState)).history_cursor == "100"
        assert session.scalar(select(func.count()).select_from(EmailMessage)) == 0
        assert session.scalar(select(Application)).current_status == "APPLIED"


def test_at43_expired_history_bounded_resync_baseline_before_backfill(engine, owner, settings):
    with Session(engine) as session, session.begin():
        seed_application(session, owner)
        conn = seed_connection(session, owner)
        session.add(GmailSyncState(connection_id=conn.id, history_cursor="expired"))
    with Session(engine) as session, session.begin():
        result = synchronize(session, owner, settings, api=FakeGmail(expired=True))
        assert result["history_cursor"] == "baseline200"
        assert result["processed"] == 1


def test_history_pagination_does_not_advance_final_cursor_early(engine, owner, settings):
    with Session(engine) as session, session.begin():
        seed_application(session, owner)
        conn = seed_connection(session, owner)
        session.add(GmailSyncState(connection_id=conn.id, history_cursor="100"))
    with Session(engine) as session, session.begin():
        result = synchronize(session, owner, settings, api=FakeGmail(next_page=True))
        assert result["history_cursor"] == "100" and result["has_more"]
        assert session.scalar(select(GmailSyncState)).reconciliation_progress["page_token"] == "page2"


def test_people_budget_cache_and_no_fake_completion(engine, owner, settings):
    with Session(engine) as session, session.begin():
        group = EmployerGroup(id=uuid4(), canonical_name="Example Corporation", normalized_name="example corporation")
        session.add(group)
        session.flush()
        job = Job(id=uuid4(), employer_group_id=group.id, title="Data Analyst")
        session.add(job)
        session.flush()
        job_id = job.id
        session.add(InitialDelivery(user_id=owner, job_id=job.id, channel="PRIORITY"))
    calls = []

    class Search:
        def search(self, query):
            calls.append(query)
            return [
                SearchResult(
                    "https://www.linkedin.com/in/jane-doe",
                    "Jane Doe - Recruiter at Example Corporation",
                    "Recruiter at Example Corporation",
                    utcnow(),
                )
            ]

    settings.people_daily_query_budget = 1
    maker = sessionmaker(engine, expire_on_commit=False)
    result = enrich(owner, job_id, settings, session_maker=maker, provider=Search())
    assert result["state"] == "PENDING_BUDGET" and result["approved_count"] == 1
    result = enrich(owner, job_id, settings, session_maker=maker, provider=Search())
    assert len(calls) == 1  # Cached query does not spend budget again.
    with maker() as session:
        people = job_people(session, owner, job_id, settings)
        assert len(people["items"]) == 1
        assert people["items"][0]["name"] == "Jane Doe"
        assert session.scalar(select(func.sum(EnrichmentRun.query_count))) == 1


def test_at59_unconfigured_auth_fails_before_db_network(settings):
    settings.google_client_secret = ""
    with pytest.raises(DomainError) as error:
        begin_intent(None, settings, None)
    assert error.value.code == "NOT_CONFIGURED"
