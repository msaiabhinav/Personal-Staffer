"""Atomic commands; all callers use these services inside a PostgreSQL transaction.

The user-row lock serializes revision checks, idempotency and cursor allocation.
Application history is append only; corrections point to the superseded event.
"""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.api.errors import DomainError
from app.db.models import (
    Application,
    ApplicationEvent,
    EmailApplicationLink,
    EmployerGroup,
    Job,
    JobSource,
    OutboxEvent,
    ProcessedOperation,
    SavedJobVersion,
    User,
    UserChange,
    UserJobEvent,
    UserJobState,
)


def now():
    return datetime.now(UTC)


def lock_user(session, user_id):
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if not user:
        raise DomainError("NOT_FOUND", "Account not found.", 404)
    return user


def change(session, user_id, kind, entity_id, revision, tombstone=False):
    session.add(
        UserChange(user_id=user_id, entity_type=kind, entity_id=entity_id, revision=revision, tombstone=tombstone)
    )


def execute_operation(session, user_id, key, command, target_id, payload, action):
    if not key or not 8 <= len(key) <= 128:
        raise DomainError("IDEMPOTENCY_KEY_REQUIRED", "Supply an Idempotency-Key of 8–128 characters.", 422)
    lock_user(session, user_id)
    digest = hashlib.sha256(
        json.dumps(
            jsonable_encoder({"command": command, "target": target_id, "payload": payload}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    previous = session.scalar(
        select(ProcessedOperation).where(ProcessedOperation.user_id == user_id, ProcessedOperation.operation_id == key)
    )
    if previous:
        if previous.request_hash != digest:
            raise DomainError(
                "IDEMPOTENCY_CONFLICT", "This operation identifier was already used for a different request."
            )
        if previous.expires_at < now():
            raise DomainError("RESYNC_REQUIRED", "This operation is too old. Refresh server state before trying again.")
        return previous.response
    result = jsonable_encoder(action())
    session.add(
        ProcessedOperation(
            user_id=user_id,
            operation_id=key,
            request_hash=digest,
            response=result,
            expires_at=now() + timedelta(days=90),
        )
    )
    session.flush()
    return result


def require_revision(actual, expected):
    if actual != expected:
        raise DomainError(
            "STALE_REVISION",
            "This record changed on another device. Refresh it and review your action.",
            details={"current_revision": actual},
        )


def get_owned_application(session, user_id, application_id, include_voided=True):
    app = session.scalar(select(Application).where(Application.id == application_id, Application.user_id == user_id))
    if not app or (not include_voided and app.voided_at is not None):
        raise DomainError("NOT_FOUND", "Application not found.", 404)
    return app


def state_for(session, user_id, job_id):
    job = session.get(Job, job_id)
    if not job:
        raise DomainError("NOT_FOUND", "Job not found.", 404)
    if job.canonical_redirect_id:
        return state_for(session, user_id, job.canonical_redirect_id)
    state = session.scalar(select(UserJobState).where(UserJobState.user_id == user_id, UserJobState.job_id == job.id))
    if not state:
        state = UserJobState(id=uuid4(), user_id=user_id, job_id=job.id, revision=0, is_saved=False)
        session.add(state)
        session.flush()
    return job, state


def state_dict(state):
    return jsonable_encoder(
        {key: getattr(state, key) for key in ("is_saved", "saved_at", "viewed_at", "dismissed_at", "revision")}
    )


def pinned_state(session, user_id, state):
    data = state_dict(state)
    if state.is_saved:
        version = session.scalar(
            select(SavedJobVersion)
            .where(
                SavedJobVersion.user_id == user_id,
                SavedJobVersion.job_id == state.job_id,
                SavedJobVersion.ended_at.is_(None),
            )
            .order_by(SavedJobVersion.saved_at.desc(), SavedJobVersion.id)
            .limit(1)
        )
        if version:
            data["saved_snapshot_id"] = str(version.snapshot_id)
    return data


def effective_events(session, application_id, exclude=()):
    events = list(
        session.scalars(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.recorded_at, ApplicationEvent.id)
        )
    )
    superseded = {event.correction_of_event_id for event in events if event.correction_of_event_id} | set(exclude)
    return [
        event
        for event in events
        if event.id not in superseded
        and event.status is not None
        and event.event_type in ("APPLIED", "STATUS_CHANGED", "CORRECTION")
        and event.evidence.get("projection_applied", True)
    ]


def active_application(session, user_id, job_id):
    return session.scalar(
        select(Application).where(
            Application.user_id == user_id, Application.job_id == job_id, Application.voided_at.is_(None)
        )
    )


def state_event(session, user_id, state, event_type, before, operation_id):
    event = UserJobEvent(
        id=uuid4(),
        user_id=user_id,
        job_id=state.job_id,
        event_type=event_type,
        before=before,
        after=state_dict(state),
        operation_id=operation_id,
    )
    session.add(event)
    change(session, user_id, "user_job_state", state.job_id, state.revision)
    return event


def set_saved(session, user_id, job_id, payload, operation_id):
    lock_user(session, user_id)
    job, state = state_for(session, user_id, job_id)
    if payload.saved and active_application(session, user_id, job.id):
        raise DomainError("ACTIVE_APPLICATION", "This job has an active application and belongs in Applied Jobs.")
    if state.is_saved == payload.saved:
        return {"job_id": job.id, **state_dict(state)}
    require_revision(state.revision, payload.expected_revision)
    if payload.saved and not job.current_snapshot_id:
        raise DomainError("SNAPSHOT_UNAVAILABLE", "This job has no retained description to save.")
    before = state_dict(state)
    state.is_saved = payload.saved
    state.saved_at = now() if payload.saved else None
    state.revision += 1
    event = state_event(session, user_id, state, "SAVED" if payload.saved else "UNSAVED", before, operation_id)
    session.flush()
    if payload.saved:
        session.add(
            SavedJobVersion(
                user_id=user_id,
                job_id=job.id,
                snapshot_id=job.current_snapshot_id,
                saved_at=state.saved_at,
                event_id=event.id,
            )
        )
    else:
        for version in session.scalars(
            select(SavedJobVersion).where(
                SavedJobVersion.user_id == user_id, SavedJobVersion.job_id == job.id, SavedJobVersion.ended_at.is_(None)
            )
        ):
            version.ended_at = now()
    return {"job_id": job.id, **state_dict(state)}


def set_dismissed(session, user_id, job_id, payload, operation_id):
    lock_user(session, user_id)
    job, state = state_for(session, user_id, job_id)
    if bool(state.dismissed_at) == payload.dismissed:
        return {"job_id": job.id, **state_dict(state)}
    require_revision(state.revision, payload.expected_revision)
    before = state_dict(state)
    state.dismissed_at = now() if payload.dismissed else None
    state.revision += 1
    state_event(session, user_id, state, "DISMISSED" if payload.dismissed else "UNDISMISSED", before, operation_id)
    return {"job_id": job.id, **state_dict(state)}


def record_open(session, user_id, job_id, operation_id, application_open=False):
    lock_user(session, user_id)
    job, state = state_for(session, user_id, job_id)
    before = state_dict(state)
    if not state.viewed_at:
        state.viewed_at = now()
        state.revision += 1
    state_event(session, user_id, state, "APPLICATION_OPENED" if application_open else "VIEWED", before, operation_id)
    if not application_open:
        return {"job_id": job.id, **state_dict(state)}
    source = session.scalar(
        select(JobSource)
        .where(JobSource.job_id == job.id)
        .order_by(JobSource.last_verified.desc().nullslast(), JobSource.id)
    )
    return {
        "job_id": job.id,
        "url": (source.application_url or source.employer_url or source.source_url) if source else None,
        "availability": source.availability if source else job.availability,
        "last_verified": source.last_verified if source else None,
        "recorded_only": True,
        "revision": state.revision,
    }


def emit_application(session, app, event):
    session.add(event)
    change(session, app.user_id, "applications", app.id, app.revision, app.voided_at is not None)
    session.add(
        OutboxEvent(
            event_key=f"application-event:{event.id}",
            event_type="application.changed",
            payload={"user_id": str(app.user_id), "application_id": str(app.id), "event_id": str(event.id)},
        )
    )


def mark_applied(session, user_id, job_id, payload, operation_id):
    lock_user(session, user_id)
    job, state = state_for(session, user_id, job_id)
    existing = active_application(session, user_id, job.id)
    if existing:
        return {
            "application_id": existing.id,
            "event_id": None,
            "status": existing.current_status,
            "is_saved": False,
            "revision": state.revision,
            "application_revision": existing.revision,
            "can_undo": False,
            "already_applied": True,
        }
    require_revision(state.revision, payload.expected_revision)
    if not job.current_snapshot_id:
        raise DomainError("SNAPSHOT_UNAVAILABLE", "No job description snapshot is available to retain.")
    source = session.scalar(
        select(JobSource)
        .where(JobSource.job_id == job.id)
        .order_by(JobSource.last_verified.desc().nullslast(), JobSource.id)
    )
    group = session.get(EmployerGroup, job.employer_group_id)
    before = pinned_state(session, user_id, state)
    app = Application(
        id=uuid4(),
        user_id=user_id,
        job_id=job.id,
        title=job.title,
        company=group.canonical_name,
        application_url=(source.application_url or source.employer_url or source.source_url) if source else None,
        source_url=source.source_url if source else None,
        applied_at=payload.applied_at or now(),
        selected_snapshot_id=job.current_snapshot_id,
        current_status="APPLIED",
        revision=1,
        notes="",
        updated_at=now(),
    )
    session.add(app)
    session.flush()
    state.is_saved = False
    state.saved_at = None
    state.revision += 1
    state_event(session, user_id, state, "APPLIED", before, operation_id)
    for version in session.scalars(
        select(SavedJobVersion).where(
            SavedJobVersion.user_id == user_id, SavedJobVersion.job_id == job.id, SavedJobVersion.ended_at.is_(None)
        )
    ):
        version.ended_at = now()
    event = ApplicationEvent(
        id=uuid4(),
        application_id=app.id,
        event_type="APPLIED",
        status="APPLIED",
        effective_at=app.applied_at,
        operation_id=operation_id,
        evidence={"previous_job_state": before, "job_state_revision_after": state.revision},
    )
    emit_application(session, app, event)
    return {
        "application_id": app.id,
        "event_id": event.id,
        "status": app.current_status,
        "is_saved": False,
        "revision": state.revision,
        "application_revision": app.revision,
        "can_undo": True,
    }


def application_dict(app, clock=None):
    clock = clock or now()
    data = {
        k: getattr(app, k)
        for k in (
            "id",
            "job_id",
            "title",
            "company",
            "application_url",
            "source_url",
            "applied_at",
            "applied_date_source",
            "current_status",
            "revision",
            "voided_at",
            "selected_snapshot_id",
            "notes",
            "added_by_user",
            "updated_at",
        )
    }
    data["display_status"] = (
        "AWAITING_RESPONSE"
        if app.current_status == "APPLIED" and clock - app.applied_at >= timedelta(hours=24)
        else app.current_status
    )
    data["display_status_derived"] = data["display_status"] == "AWAITING_RESPONSE"
    return jsonable_encoder(data)


def create_manual(session, user_id, payload, operation_id):
    lock_user(session, user_id)
    # Exact URL equality can attach; company/title similarity never does.
    known_source = None
    if payload.application_url:
        candidates = list(
            session.scalars(select(JobSource).where(JobSource.application_url == payload.application_url))
        )
        candidates = [
            source
            for source in candidates
            if source.link_evidence.get("identity_match") is True
            or source.link_evidence.get("identity_matches") is True
        ]
        canonical = {}
        for source in candidates:
            candidate_job = session.get(Job, source.job_id)
            seen = set()
            while candidate_job.canonical_redirect_id and candidate_job.id not in seen:
                seen.add(candidate_job.id)
                candidate_job = session.get(Job, candidate_job.canonical_redirect_id)
            canonical[candidate_job.id] = source
        if len(canonical) == 1:
            known_source = next(iter(canonical.values()))
            canonical_job_id = next(iter(canonical))
    if known_source and active_application(session, user_id, canonical_job_id):
        raise DomainError("ACTIVE_APPLICATION", "This opening already has an application.")
    external_identity = payload.application_url or None
    if external_identity and session.scalar(
        select(Application).where(
            Application.user_id == user_id,
            Application.external_identity == external_identity,
            Application.voided_at.is_(None),
        )
    ):
        raise DomainError("ACTIVE_APPLICATION", "This job URL already has an application.")
    job = session.get(Job, canonical_job_id) if known_source else None
    app = Application(
        id=uuid4(),
        user_id=user_id,
        job_id=job.id if job else None,
        title=payload.title,
        company=payload.company,
        application_url=payload.application_url,
        source_url=payload.source_url,
        external_identity=external_identity,
        applied_at=payload.applied_at or now(),
        current_status="APPLIED",
        revision=1,
        notes=payload.notes,
        added_by_user=True,
        manual_description=payload.description,
        selected_snapshot_id=job.current_snapshot_id if job else None,
        updated_at=now(),
        applied_date_source="USER",
    )
    session.add(app)
    session.flush()
    evidence = {"added_by_user": True}
    if job:
        _, state = state_for(session, user_id, job.id)
        evidence["previous_job_state"] = pinned_state(session, user_id, state)
        state.is_saved = False
        state.saved_at = None
        state.revision += 1
        evidence["job_state_revision_after"] = state.revision
        state_event(session, user_id, state, "APPLIED", evidence["previous_job_state"], operation_id)
        for version in session.scalars(
            select(SavedJobVersion).where(
                SavedJobVersion.user_id == user_id, SavedJobVersion.job_id == job.id, SavedJobVersion.ended_at.is_(None)
            )
        ):
            version.ended_at = now()
    event = ApplicationEvent(
        id=uuid4(),
        application_id=app.id,
        event_type="APPLIED",
        status="APPLIED",
        effective_at=app.applied_at,
        operation_id=operation_id,
        evidence=evidence,
    )
    emit_application(session, app, event)
    return {**application_dict(app), "event_id": str(event.id)}


def add_status_event(
    session, user_id, application_id, payload, operation_id, actor="USER", source_reference=None, evidence=None
):
    lock_user(session, user_id)
    app = get_owned_application(session, user_id, application_id, False)
    prior = session.scalar(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == app.id, ApplicationEvent.operation_id == operation_id
        )
    )
    if prior:
        return {**application_dict(app), "event_id": str(prior.id)}
    require_revision(app.revision, payload.expected_revision)
    effective_at = payload.effective_at or now()
    evidence = {**(evidence or {}), "reason": payload.reason, "previous_status": app.current_status}
    meaningful = max(
        effective_events(session, app.id), key=lambda event: (event.effective_at, event.recorded_at), default=None
    )
    apply_status = True
    if actor == "EMAIL":
        if payload.status == "APPLIED" and app.current_status != "APPLIED":
            apply_status = False
        if meaningful and effective_at < meaningful.effective_at:
            apply_status = False
    evidence["projection_applied"] = apply_status
    if apply_status:
        app.current_status = payload.status
    app.revision += 1
    app.updated_at = now()
    event = ApplicationEvent(
        id=uuid4(),
        application_id=app.id,
        event_type="STATUS_CHANGED" if apply_status else "EVIDENCE_RECEIVED",
        status=payload.status,
        effective_at=effective_at,
        actor=actor,
        source_reference=source_reference,
        evidence=evidence,
        operation_id=operation_id,
    )
    emit_application(session, app, event)
    if apply_status:
        from app.notifications.service import create_notification

        create_notification(
            session,
            user_id,
            "APPLICATION_STATUS",
            "applications",
            app.id,
            f"{app.company}: {payload.status.replace('_', ' ').title()}"[:250],
            app.title,
            f"application-status:{event.id}",
        )
    return {**application_dict(app), "event_id": str(event.id)}


def patch_application(session, user_id, application_id, payload, operation_id):
    lock_user(session, user_id)
    app = get_owned_application(session, user_id, application_id, False)
    require_revision(app.revision, payload.expected_revision)
    before = {"notes": app.notes, "applied_at": app.applied_at.isoformat()}
    if payload.notes is not None:
        app.notes = payload.notes
    if payload.applied_at is not None:
        app.applied_at = payload.applied_at
        app.applied_date_source = "USER_CORRECTED"
    app.revision += 1
    app.updated_at = now()
    event = ApplicationEvent(
        id=uuid4(),
        application_id=app.id,
        event_type="METADATA_UPDATED",
        effective_at=now(),
        operation_id=operation_id,
        evidence={"before": before, "after": {"notes": app.notes, "applied_at": app.applied_at.isoformat()}},
    )
    emit_application(session, app, event)
    return application_dict(app)


def correct_event(session, user_id, application_id, payload, operation_id):
    lock_user(session, user_id)
    app = get_owned_application(session, user_id, application_id)
    target = session.scalar(
        select(ApplicationEvent).where(
            ApplicationEvent.id == payload.event_id, ApplicationEvent.application_id == app.id
        )
    )
    if not target:
        raise DomainError("NOT_FOUND", "The referenced application event was not found.", 404)
    existing = session.scalar(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == app.id, ApplicationEvent.correction_of_event_id == target.id
        )
    )
    if existing:
        return {**application_dict(app), "correction_event_id": str(existing.id), "already_corrected": True}
    require_revision(app.revision, payload.expected_revision)
    later = session.scalar(
        select(ApplicationEvent)
        .where(
            ApplicationEvent.application_id == app.id,
            ApplicationEvent.id != target.id,
            ApplicationEvent.recorded_at > target.recorded_at,
        )
        .limit(1)
    )
    if payload.action == "UNDO_APPLIED":
        if target.event_type != "APPLIED":
            raise DomainError("INVALID_CORRECTION", "Undo Applied must reference the original Applied event.")
        if later:
            raise DomainError(
                "LATER_ACTIVITY_CONFLICT",
                "Later application activity exists. Review the timeline before correcting this application.",
                details={"current_revision": app.revision, "later_event_id": str(later.id)},
            )
        if app.job_id:
            _, state = state_for(session, user_id, app.job_id)
            expected_state = target.evidence.get("job_state_revision_after")
            if expected_state is not None and state.revision != expected_state:
                raise DomainError(
                    "LATER_ACTIVITY_CONFLICT",
                    "Job state changed after Applied; the previous state cannot be restored automatically.",
                )
            before = state_dict(state)
            previous = target.evidence.get("previous_job_state", {})
            state.is_saved = bool(previous.get("is_saved", False))
            for key in ("saved_at", "viewed_at", "dismissed_at"):
                value = previous.get(key)
                setattr(state, key, datetime.fromisoformat(value) if value else None)
            state.revision += 1
            state_event(session, user_id, state, "APPLIED_CORRECTED", before, operation_id)
            if state.is_saved and app.selected_snapshot_id:
                session.add(
                    SavedJobVersion(
                        user_id=user_id,
                        job_id=app.job_id,
                        snapshot_id=UUID(previous["saved_snapshot_id"])
                        if previous.get("saved_snapshot_id")
                        else app.selected_snapshot_id,
                        saved_at=state.saved_at,
                    )
                )
        app.voided_at = now()
    else:
        if target.event_type == "APPLIED":
            raise DomainError("INVALID_CORRECTION", "Use Undo Applied to correct the original application.")
        previous_status = target.evidence.get("previous_status")
        if not previous_status:
            raise DomainError(
                "INVALID_CORRECTION", "This event has no restorable status. Edit its specific metadata instead."
            )
        remaining = [
            event
            for event in effective_events(session, app.id, exclude=(target.id,))
            if event.event_type != "CORRECTION"
        ]
        app.current_status = remaining[-1].status if remaining else "APPLIED"
        for link in session.scalars(select(EmailApplicationLink).where(EmailApplicationLink.event_id == target.id)):
            link.corrected_at = now()
    app.revision += 1
    app.updated_at = now()
    correction = ApplicationEvent(
        id=uuid4(),
        application_id=app.id,
        event_type="CORRECTION",
        status=app.current_status,
        effective_at=now(),
        operation_id=operation_id,
        correction_of_event_id=target.id,
        evidence={"reason": payload.reason, "action": payload.action},
    )
    emit_application(session, app, correction)
    return {
        **application_dict(app),
        "correction_event_id": str(correction.id),
        "restored_saved": state.is_saved if payload.action == "UNDO_APPLIED" and app.job_id else False,
    }
