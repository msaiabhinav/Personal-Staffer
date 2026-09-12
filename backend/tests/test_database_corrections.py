"""Regression cases for status corrections and retained Saved snapshot provenance.

These execute only against real PostgreSQL via the shared migration fixture.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_database_core import example as example  # noqa: PLC0414 -- expose shared pytest fixture
from test_database_core import pg_engine as pg_engine  # noqa: PLC0414 -- expose shared pytest fixture
from test_database_core import run_command

from app.api.schemas import ApplicationPatch, ApplyInput, CorrectionInput, SaveInput, StatusInput
from app.applications import service
from app.db.models import Application, ApplicationEvent, Job, JobSnapshot, Notification, SavedJobVersion, UserJobState

pytestmark = pytest.mark.postgres


def _applied_and_interviewing(engine, user_id, job_id):
    clock = datetime.now(UTC) - timedelta(days=2)
    applied = run_command(
        engine,
        user_id,
        "apply",
        job_id,
        ApplyInput(expected_revision=0, applied_at=clock),
        "apply-initial",
        service.mark_applied,
    )
    app_id = UUID(applied["application_id"])
    interview = run_command(
        engine,
        user_id,
        "status",
        app_id,
        StatusInput(
            expected_revision=1,
            status="INTERVIEWING",
            reason="Recruiter interview",
            effective_at=clock + timedelta(hours=1),
        ),
        "interview-initial",
        service.add_status_event,
    )
    return app_id, clock, interview


def _email_status(engine, user_id, app_id, revision, status, effective_at, operation_id):
    with Session(engine) as session, session.begin():
        return service.add_status_event(
            session,
            user_id,
            app_id,
            StatusInput(
                expected_revision=revision, status=status, reason="Recorded employer email", effective_at=effective_at
            ),
            operation_id,
            actor="EMAIL",
            source_reference=f"gmail:{operation_id}",
        )


@pytest.mark.parametrize("later_activity", ["notes", "unprojected_confirmation"])
def test_at41_reverting_rejection_preserves_later_notes_but_restores_real_status(pg_engine, example, later_activity):
    user_id, _, job_id, _ = example
    app_id, clock, interview = _applied_and_interviewing(pg_engine, user_id, job_id)
    rejected = _email_status(
        pg_engine, user_id, app_id, interview["revision"], "REJECTED", clock + timedelta(hours=2), "gmail-rejection"
    )
    assert rejected["current_status"] == "REJECTED"
    if later_activity == "notes":
        later = run_command(
            pg_engine,
            user_id,
            "notes",
            app_id,
            ApplicationPatch(expected_revision=rejected["revision"], notes="Keep this user note"),
            "note-after-rejection",
            service.patch_application,
        )
    else:
        later = _email_status(
            pg_engine,
            user_id,
            app_id,
            rejected["revision"],
            "APPLIED",
            clock + timedelta(hours=3),
            "gmail-late-confirmation",
        )
        assert later["current_status"] == "REJECTED"
    result = run_command(
        pg_engine,
        user_id,
        "correction",
        app_id,
        CorrectionInput(
            expected_revision=later["revision"],
            event_id=rejected["event_id"],
            action="REVERT_EVENT",
            reason="Rejection was interpreted incorrectly",
        ),
        "correct-the-rejection",
        service.correct_event,
    )
    assert result["current_status"] == "INTERVIEWING"
    with Session(pg_engine) as session:
        app = session.get(Application, app_id)
        assert app.current_status == "INTERVIEWING"
        if later_activity == "notes":
            assert app.notes == "Keep this user note"
        correction = session.scalar(
            select(ApplicationEvent).where(
                ApplicationEvent.application_id == app_id,
                ApplicationEvent.correction_of_event_id == UUID(rejected["event_id"]),
            )
        )
        assert correction is not None
        assert session.get(ApplicationEvent, UUID(rejected["event_id"])) is not None


def test_at40_unprojected_confirmation_does_not_hide_later_real_employer_status(pg_engine, example):
    user_id, _, job_id, _ = example
    app_id, clock, interview = _applied_and_interviewing(pg_engine, user_id, job_id)
    confirmation = _email_status(
        pg_engine,
        user_id,
        app_id,
        interview["revision"],
        "APPLIED",
        clock + timedelta(hours=3),
        "gmail-late-confirmation",
    )
    assert confirmation["current_status"] == "INTERVIEWING"
    rejected = _email_status(
        pg_engine,
        user_id,
        app_id,
        confirmation["revision"],
        "REJECTED",
        clock + timedelta(hours=2),
        "gmail-real-rejection",
    )
    assert rejected["current_status"] == "REJECTED"
    with Session(pg_engine) as session:
        ignored = session.get(ApplicationEvent, UUID(confirmation["event_id"]))
        assert ignored.evidence["projection_applied"] is False
        applied = session.get(ApplicationEvent, UUID(rejected["event_id"]))
        assert applied.evidence["projection_applied"] is True
        assert (
            session.scalar(select(func.count()).select_from(Notification).where(Notification.user_id == user_id)) == 2
        )


def test_at34_undo_restores_original_saved_snapshot_after_source_refresh(pg_engine, example):
    user_id, _, job_id, saved_snapshot_id = example
    saved = run_command(
        pg_engine,
        user_id,
        "save",
        job_id,
        SaveInput(expected_revision=0, saved=True),
        "save-original-jd",
        service.set_saved,
    )
    with Session(pg_engine) as session, session.begin():
        original = session.get(JobSnapshot, saved_snapshot_id)
        refreshed = JobSnapshot(
            job_id=job_id,
            source_id=original.source_id,
            description="Changed employer JD after this job was saved",
            content_hash="b" * 64,
            content_complete=True,
        )
        session.add(refreshed)
        session.flush()
        session.get(Job, job_id).current_snapshot_id = refreshed.id
    applied = run_command(
        pg_engine,
        user_id,
        "apply",
        job_id,
        ApplyInput(expected_revision=saved["revision"]),
        "apply-refreshed-jd",
        service.mark_applied,
    )
    undone = run_command(
        pg_engine,
        user_id,
        "correction",
        UUID(applied["application_id"]),
        CorrectionInput(
            expected_revision=applied["application_revision"],
            event_id=applied["event_id"],
            action="UNDO_APPLIED",
            reason="Accidental click",
        ),
        "undo-refreshed-apply",
        service.correct_event,
    )
    assert undone["restored_saved"] is True
    with Session(pg_engine) as session:
        state = session.scalar(
            select(UserJobState).where(UserJobState.user_id == user_id, UserJobState.job_id == job_id)
        )
        assert state.is_saved is True
        assert state.saved_at.isoformat() == saved["saved_at"]
        active_versions = list(
            session.scalars(
                select(SavedJobVersion).where(
                    SavedJobVersion.user_id == user_id,
                    SavedJobVersion.job_id == job_id,
                    SavedJobVersion.ended_at.is_(None),
                )
            )
        )
        assert len(active_versions) == 1
        assert active_versions[0].snapshot_id == saved_snapshot_id
        assert session.get(Application, UUID(applied["application_id"])).voided_at is not None
