"""Frozen initial pages: replace the local account projection, then pull deltas.

All writers take the user lock; paging never leaves a database transaction open.
Only explicitly listed user-facing fields are serialized, never provider tokens.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    Application,
    ApplicationEvent,
    EmployerGroup,
    InitialDelivery,
    Job,
    JobEvaluation,
    JobSnapshot,
    JobSource,
    Notification,
    Report,
    ReportJob,
    ReviewItem,
    SavedJobVersion,
    SearchProfile,
    SyncSnapshot,
    UserJobState,
    WatchlistEntry,
)
from app.notifications.service import as_dict as notification_dict
from app.sync.contracts import SyncError, utc, validate_cursor, validate_limit
from app.sync.service import lock_user, record_change

SNAPSHOT_TTL = timedelta(hours=1)


def _json(value):
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(item) for item in value]
    return value


def _item(row, entity_type, fields, *, tombstone=False):
    return {
        "entity_type": entity_type,
        "entity_id": str(row.job_id if isinstance(row, UserJobState) else row.id),
        "revision": getattr(row, "revision", 1),
        "tombstone": tombstone,
        "data": {name: _json(getattr(row, name)) for name in fields.split()},
    }


def start_snapshot(session: Session, user_id: UUID, limit: int = 25, *, now: datetime | None = None) -> dict:
    """Caller commits before returning. Final-page cursor is the atomic boundary."""
    validate_limit(limit)
    now = utc(now or datetime.now(UTC))
    lock_user(session, user_id)
    session.execute(delete(SyncSnapshot).where(SyncSnapshot.user_id == user_id, SyncSnapshot.expires_at <= now))
    definitions = [
        (UserJobState, "user_job_state", "id job_id viewed_at is_saved saved_at dismissed_at revision"),
        (
            Application,
            "applications",
            "id job_id title company application_url source_url applied_at applied_date_source current_status revision voided_at selected_snapshot_id manual_description notes added_by_user updated_at",
        ),
        (
            SearchProfile,
            "profile",
            "id version revision role_families skills aliases geography work_arrangements salary_preferences ruleset_version",
        ),
        (WatchlistEntry, "watchlist", "id employer_group_id requested_name enabled created_at revision"),
        (ReviewItem, "reviews", "id review_type target_id reason evidence state resolved_at resolution revision"),
        (Report, "reports", "id report_date cycle_id intended_release actual_release status profile_version summary"),
        (InitialDelivery, "initial_delivery", "id job_id channel report_id snapshot_id delivered_at"),
        (SavedJobVersion, "saved_job_version", "id job_id snapshot_id saved_at ended_at event_id"),
    ]
    items, app_ids, report_ids, job_ids, snapshot_ids, group_ids = [], set(), set(), set(), set(), set()
    for model, entity_type, fields in definitions:
        query = select(model).where(model.user_id == user_id).order_by(model.id)
        if model is ReviewItem:
            query = query.where(ReviewItem.admin_only.is_(False))
        for row in session.scalars(query):
            items.append(
                _item(row, entity_type, fields, tombstone=isinstance(row, Application) and row.voided_at is not None)
            )
            if isinstance(row, WatchlistEntry) and row.employer_group_id:
                group_ids.add(row.employer_group_id)
            if isinstance(row, Application):
                app_ids.add(row.id)
                if row.selected_snapshot_id:
                    snapshot_ids.add(row.selected_snapshot_id)
            if isinstance(row, Report):
                report_ids.add(row.id)
            if getattr(row, "job_id", None):
                job_ids.add(row.job_id)
            if getattr(row, "snapshot_id", None):
                snapshot_ids.add(row.snapshot_id)
    for row in session.scalars(select(Notification).where(Notification.user_id == user_id).order_by(Notification.id)):
        items.append(
            {
                "entity_type": "notifications",
                "entity_id": str(row.id),
                "revision": row.revision,
                "tombstone": False,
                "data": notification_dict(row),
            }
        )
    if app_ids:
        for row in session.scalars(
            select(ApplicationEvent).where(ApplicationEvent.application_id.in_(app_ids)).order_by(ApplicationEvent.id)
        ):
            items.append(
                _item(
                    row,
                    "application_event",
                    "id application_id event_type status effective_at recorded_at actor source_reference evidence correction_of_event_id",
                )
            )
    if report_ids:
        for row in session.scalars(select(ReportJob).where(ReportJob.report_id.in_(report_ids)).order_by(ReportJob.id)):
            items.append(
                _item(row, "report_job", "id report_id job_id snapshot_id selection_band selection_order evaluation_id")
            )
            job_ids.add(row.job_id)
            snapshot_ids.add(row.snapshot_id)
    if job_ids:
        for row in session.scalars(select(Job).where(Job.id.in_(job_ids)).order_by(Job.id)):
            group_ids.add(row.employer_group_id)
            items.append(
                _item(
                    row,
                    "job",
                    "id employer_group_id title locations work_arrangement published_at published_earliest published_latest publication_precision first_seen availability current_snapshot_id canonical_redirect_id salary_min salary_max salary_currency salary_interval priority_reasons role_family synthetic",
                )
            )
            if row.current_snapshot_id:
                snapshot_ids.add(row.current_snapshot_id)
        for row in session.scalars(select(JobSource).where(JobSource.job_id.in_(job_ids)).order_by(JobSource.id)):
            items.append(
                _item(
                    row,
                    "job_source",
                    "id job_id source_url employer_url application_url final_observed_url last_seen last_verified availability",
                )
            )
    if group_ids:
        for row in session.scalars(
            select(EmployerGroup).where(EmployerGroup.id.in_(group_ids)).order_by(EmployerGroup.id)
        ):
            items.append(_item(row, "employer_group", "id canonical_name pool_tags"))
    if snapshot_ids:
        for row in session.scalars(
            select(JobSnapshot).where(JobSnapshot.id.in_(snapshot_ids)).order_by(JobSnapshot.id)
        ):
            items.append(
                _item(
                    row,
                    "job_snapshot",
                    "id job_id source_id fetched_at description content_hash content_complete structured_fields",
                )
            )
        seen_evaluations = set()
        evaluations = (
            select(JobEvaluation)
            .where(
                JobEvaluation.snapshot_id.in_(snapshot_ids),
                or_(JobEvaluation.user_id == user_id, JobEvaluation.user_id.is_(None)),
            )
            .order_by(JobEvaluation.snapshot_id, JobEvaluation.evaluated_at.desc(), JobEvaluation.id.desc())
        )
        for row in session.scalars(evaluations):
            if row.snapshot_id in seen_evaluations:
                continue
            seen_evaluations.add(row.snapshot_id)
            items.append(
                _item(
                    row,
                    "job_evaluation",
                    "id job_id snapshot_id profile_version ruleset_version evaluated_at decision valid_until evidence",
                )
            )
    snapshot_id = uuid4()
    # A dormant account must receive a fresh usable cursor too. Existing clients
    # treat sync_boundary as a no-op, never as an entity to fetch.
    boundary = record_change(session, user_id, "sync_boundary", snapshot_id, 0)
    snapshot = SyncSnapshot(
        id=snapshot_id,
        user_id=user_id,
        boundary_cursor=boundary.cursor,
        items=items,
        created_at=now,
        expires_at=now + SNAPSHOT_TTL,
    )
    session.add(snapshot)
    session.flush()
    return snapshot_page(session, user_id, snapshot_id, 0, limit, now=now)


def snapshot_page(
    session: Session, user_id: UUID, snapshot_id: UUID, offset: int = 0, limit: int = 25, *, now: datetime | None = None
) -> dict:
    validate_limit(limit)
    validate_cursor(offset)
    now = utc(now or datetime.now(UTC))
    snapshot = session.scalar(
        select(SyncSnapshot).where(SyncSnapshot.id == snapshot_id, SyncSnapshot.user_id == user_id)
    )
    if snapshot is None:
        raise SyncError("NOT_FOUND", "Sync snapshot not found.", 404)
    if utc(snapshot.expires_at) <= now:
        raise SyncError("RESYNC_REQUIRED", "The snapshot expired. Start a fresh snapshot.")
    if offset > len(snapshot.items):
        raise SyncError("INVALID_OFFSET", "Snapshot offset is outside its item range.", 422)
    page = snapshot.items[offset : offset + limit]
    next_offset = offset + len(page)
    has_more = next_offset < len(snapshot.items)
    return {
        "snapshot_id": str(snapshot.id),
        "boundary_cursor": snapshot.boundary_cursor,
        "items": page,
        "next_offset": next_offset if has_more else None,
        "next_cursor": None if has_more else snapshot.boundary_cursor,
        "has_more": has_more,
        "expires_at": utc(snapshot.expires_at).isoformat(),
    }
