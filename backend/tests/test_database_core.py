"""State and concurrency checks use real PostgreSQL, never a SQLite substitute."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.api.errors import DomainError
from app.api.schemas import ApplyInput, CorrectionInput, ManualApplicationInput, SaveInput, StatusInput
from app.applications import service
from app.db.models import *

pytestmark = pytest.mark.postgres


@pytest.fixture
def pg_engine():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("TEST_DATABASE_URL is not configured; PostgreSQL behavioral checks were not executed")
    if not dsn.startswith("postgresql"):
        pytest.fail("Use an actual PostgreSQL server")
    engine = create_engine(dsn)
    schema = "core_" + uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = create_engine(dsn, connect_args={"options": f"-csearch_path={schema}"})
    from alembic import command
    from alembic.config import Config

    with engine.begin() as connection:
        connection.execute(text(f'SET search_path TO "{schema}"'))
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    yield scoped
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    scoped.dispose()
    engine.dispose()


@pytest.fixture
def example(pg_engine):
    with Session(pg_engine) as session, session.begin():
        user = User(google_subject="test:" + str(uuid4()), verified_email="owner@example.test")
        other = User(google_subject="test:" + str(uuid4()), verified_email="other@example.test")
        group = EmployerGroup(canonical_name="Synthetic employer", normalized_name="synthetic employer")
        session.add_all([user, other, group])
        session.flush()
        job = Job(
            employer_group_id=group.id,
            title="Synthetic Analyst",
            availability="ACTIVE",
            synthetic=True,
            published_at=datetime.now(UTC) - timedelta(hours=24),
        )
        source = SourceRegistry(connector_type="fixture", tenant=str(uuid4()))
        session.add_all([job, source])
        session.flush()
        job_source = JobSource(
            job_id=job.id,
            source_registry_id=source.id,
            external_id="one",
            source_url="https://example.test/jobs/one",
            application_url="https://example.test/jobs/one/apply",
            availability="ACTIVE",
        )
        session.add(job_source)
        session.flush()
        snapshot = JobSnapshot(
            job_id=job.id,
            source_id=job_source.id,
            description="Full synthetic retained job description",
            content_hash="a" * 64,
            content_complete=True,
        )
        session.add(snapshot)
        session.flush()
        job.current_snapshot_id = snapshot.id
        session.add(InitialDelivery(user_id=user.id, job_id=job.id, channel="PRIORITY", snapshot_id=snapshot.id))
        return user.id, other.id, job.id, snapshot.id


def run_command(engine, user, command, target, payload, key, handler):
    with Session(engine) as session, session.begin():
        return service.execute_operation(
            session,
            user,
            key,
            command,
            target,
            payload.model_dump(mode="json"),
            lambda: handler(session, user, target, payload, key),
        )


def test_at31_at32_at34_saved_apply_undo_preserves_pinned_history(pg_engine, example):
    user, _, job, snapshot = example
    saved = run_command(
        pg_engine, user, "save", job, SaveInput(saved=True, expected_revision=0), "save-one", service.set_saved
    )
    with Session(pg_engine) as session, session.begin():
        row = session.get(Job, job)
        row.availability = "CLOSED"
        row.published_at -= timedelta(days=100)
    applied = run_command(
        pg_engine,
        user,
        "apply",
        job,
        ApplyInput(expected_revision=saved["revision"]),
        "apply-one",
        service.mark_applied,
    )
    assert applied["is_saved"] is False
    with Session(pg_engine) as session:
        app = session.get(Application, UUID(applied["application_id"]))
        assert app.selected_snapshot_id == snapshot
        assert app.application_url.endswith("/apply")
        assert session.get(JobSnapshot, app.selected_snapshot_id).description.startswith("Full synthetic")
    undo = run_command(
        pg_engine,
        user,
        "correction",
        UUID(applied["application_id"]),
        CorrectionInput(
            event_id=applied["event_id"], expected_revision=1, reason="Mistaken click", action="UNDO_APPLIED"
        ),
        "undo-one",
        service.correct_event,
    )
    assert undo["restored_saved"] is True and undo["voided_at"]
    with Session(pg_engine) as session:
        state = session.scalar(select(UserJobState).where(UserJobState.user_id == user, UserJobState.job_id == job))
        assert state.is_saved and state.saved_at.isoformat() == saved["saved_at"]
        assert session.scalar(select(func.count()).select_from(ApplicationEvent)) == 2
        assert session.scalar(select(func.count()).select_from(Application).where(Application.voided_at.is_(None))) == 0


def test_at32_open_is_not_application(pg_engine, example):
    user, _, job, _ = example
    with Session(pg_engine) as session, session.begin():
        result = service.record_open(session, user, job, "open-one", True)
        assert result["recorded_only"] is True
        assert session.scalar(select(func.count()).select_from(Application)) == 0


def test_at33_concurrent_apply_retries_produce_one_active_application(pg_engine, example):
    user, _, job, _ = example

    def apply(index):
        return run_command(
            pg_engine,
            user,
            "apply",
            job,
            ApplyInput(expected_revision=0),
            f"apply-device-{index}",
            service.mark_applied,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, [1, 2]))
    assert results[0]["application_id"] == results[1]["application_id"]
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Application)) == 1
        assert session.scalar(select(func.count()).select_from(ApplicationEvent)) == 1


def test_at34_unsaved_apply_undo_does_not_invent_saved(pg_engine, example):
    user, _, job, _ = example
    applied = run_command(
        pg_engine, user, "apply", job, ApplyInput(expected_revision=0), "apply-one", service.mark_applied
    )
    undo = run_command(
        pg_engine,
        user,
        "correction",
        UUID(applied["application_id"]),
        CorrectionInput(event_id=applied["event_id"], expected_revision=1, reason="Mistaken", action="UNDO_APPLIED"),
        "undo-one",
        service.correct_event,
    )
    assert undo["restored_saved"] is False


def test_at35_later_interview_conflicts_with_undo_and_resave(pg_engine, example):
    user, _, job, _ = example
    applied = run_command(
        pg_engine, user, "apply", job, ApplyInput(expected_revision=0), "apply-one", service.mark_applied
    )
    app_id = UUID(applied["application_id"])
    run_command(
        pg_engine,
        user,
        "status",
        app_id,
        StatusInput(status="INTERVIEWING", reason="Recruiter called", expected_revision=1),
        "status-one",
        service.add_status_event,
    )
    with pytest.raises(DomainError, match="Later application activity"):
        run_command(
            pg_engine,
            user,
            "correction",
            app_id,
            CorrectionInput(
                event_id=applied["event_id"], expected_revision=2, reason="Mistaken", action="UNDO_APPLIED"
            ),
            "undo-one",
            service.correct_event,
        )
    with pytest.raises(DomainError, match="active application"):
        run_command(
            pg_engine, user, "save", job, SaveInput(saved=True, expected_revision=1), "save-one", service.set_saved
        )


def test_at37_manual_no_link_and_ownership(pg_engine, example):
    user, other, _, _ = example
    payload = ManualApplicationInput(
        title="External Contract Role", company="Unknown EVerify", description="Recorded actual application"
    )
    with Session(pg_engine) as session, session.begin():
        result = service.execute_operation(
            session,
            user,
            "manual-one",
            "manual",
            user,
            payload.model_dump(mode="json"),
            lambda: service.create_manual(session, user, payload, "manual-one"),
        )
        assert result["application_url"] is None and result["added_by_user"] is True
    with Session(pg_engine) as session:
        with pytest.raises(DomainError) as err:
            service.get_owned_application(session, other, UUID(result["id"]))
        assert err.value.status_code == 404


def test_at49_idempotency_replay_and_changed_payload_conflict(pg_engine, example):
    user, _, job, _ = example
    payload = SaveInput(saved=True, expected_revision=0)
    first = run_command(pg_engine, user, "save", job, payload, "save-one", service.set_saved)
    assert run_command(pg_engine, user, "save", job, payload, "save-one", service.set_saved) == first
    with pytest.raises(DomainError) as err:
        run_command(
            pg_engine, user, "save", job, SaveInput(saved=False, expected_revision=1), "save-one", service.set_saved
        )
    assert err.value.code == "IDEMPOTENCY_CONFLICT"
    with pytest.raises(DomainError) as err:
        run_command(
            pg_engine, user, "save", job, SaveInput(saved=False, expected_revision=0), "unsave-other", service.set_saved
        )
    assert err.value.code == "STALE_REVISION"


def test_at40_late_email_confirmation_never_regresses_interview(pg_engine, example):
    user, _, job, _ = example
    applied = run_command(
        pg_engine, user, "apply", job, ApplyInput(expected_revision=0), "apply-one", service.mark_applied
    )
    app_id = UUID(applied["application_id"])
    run_command(
        pg_engine,
        user,
        "status",
        app_id,
        StatusInput(status="INTERVIEWING", reason="Interview", expected_revision=1),
        "status-one",
        service.add_status_event,
    )
    with Session(pg_engine) as session, session.begin():
        result = service.add_status_event(
            session,
            user,
            app_id,
            StatusInput(status="APPLIED", reason="Delayed email", expected_revision=2),
            "gmail-confirmation",
            actor="EMAIL",
        )
        assert result["current_status"] == "INTERVIEWING"
        assert session.scalar(select(func.count()).select_from(Notification)) == 1
