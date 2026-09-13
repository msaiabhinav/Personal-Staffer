"""Versioned client API. Source candidate administration is separate from delivered views."""

import base64
import json
from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.api.errors import DomainError
from app.api.schemas import *
from app.applications import service as application_service
from app.auth.dependencies import current_user
from app.db.models import *
from app.db.session import get_session
from app.notifications import service as notification_service
from app.notifications.contracts import NotificationError
from app.sync import service as sync_service
from app.sync.contracts import SyncError

router = APIRouter(prefix="/api/v1")
USER_DEPENDENCY = Depends(current_user)
SESSION_DEPENDENCY = Depends(get_session)


def _page(session, statement, column, cursor, limit, serializer, descending=True, sort_column=None):
    model = column.class_
    if sort_column is None:
        sort_column = {
            Application: Application.applied_at,
            Report: Report.report_date,
            JobSnapshot: JobSnapshot.fetched_at,
            WatchlistEntry: WatchlistEntry.created_at,
            SearchRun: SearchRun.started_at,
            EmployerGroup: EmployerGroup.canonical_name,
            Job: func.coalesce(Job.published_at, Job.published_latest, Job.published_earliest),
        }.get(model, column)
    if cursor:
        try:
            data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            identifier = UUID(data["id"])
            value = data["sort"]
            kind = sort_column.type.python_type
            if value is not None and kind in (datetime, date):
                value = kind.fromisoformat(value)
            elif value is not None and kind is UUID:
                value = UUID(value)
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise DomainError("INVALID_CURSOR", "Invalid page cursor.", 422)
        id_after = column < identifier if descending else column > identifier
        if value is None:
            statement = statement.where(and_(sort_column.is_(None), id_after))
        else:
            after = sort_column < value if descending else sort_column > value
            statement = statement.where(or_(after, sort_column.is_(None), and_(sort_column == value, id_after)))
    query = (
        statement.add_columns(sort_column.label("_page_sort"))
        .order_by(
            sort_column.desc().nullslast() if descending else sort_column.asc().nullslast(),
            column.desc() if descending else column.asc(),
        )
        .limit(limit + 1)
    )
    rows = list(session.execute(query))
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more:
        record, sort_value = rows[-1]
        data = jsonable_encoder({"id": str(record.id), "sort": sort_value})
        next_cursor = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return {"items": [serializer(row[0]) for row in rows], "next_cursor": next_cursor, "has_more": has_more}


def _columns(record, omit=()):
    return jsonable_encoder(
        {column.key: getattr(record, column.key) for column in record.__table__.columns if column.key not in omit}
    )


def _accessible_job(session, user_id, job_id):
    job = session.get(Job, job_id)
    if not job:
        raise DomainError("NOT_FOUND", "Job not found.", 404)
    while job.canonical_redirect_id:
        job = session.get(Job, job.canonical_redirect_id)
    delivered = session.scalar(
        select(InitialDelivery.id).where(InitialDelivery.user_id == user_id, InitialDelivery.job_id == job.id)
    )
    state = session.scalar(
        select(UserJobState.id).where(UserJobState.user_id == user_id, UserJobState.job_id == job.id)
    )
    app = session.scalar(select(Application.id).where(Application.user_id == user_id, Application.job_id == job.id))
    if not (delivered or state or app):
        raise DomainError("NOT_FOUND", "Job not found.", 404)
    return job


def _job(session, user_id, job, snapshot_id=None):
    state = session.scalar(select(UserJobState).where(UserJobState.user_id == user_id, UserJobState.job_id == job.id))
    if snapshot_id is None and state and state.is_saved:
        saved_version = session.scalar(
            select(SavedJobVersion)
            .where(
                SavedJobVersion.user_id == user_id, SavedJobVersion.job_id == job.id, SavedJobVersion.ended_at.is_(None)
            )
            .order_by(SavedJobVersion.saved_at.desc(), SavedJobVersion.id)
            .limit(1)
        )
        snapshot_id = saved_version.snapshot_id if saved_version else None
    snapshot = (
        session.get(JobSnapshot, snapshot_id or job.current_snapshot_id)
        if snapshot_id or job.current_snapshot_id
        else None
    )
    group = session.get(EmployerGroup, job.employer_group_id)
    evaluation = session.scalar(
        select(JobEvaluation)
        .where(
            JobEvaluation.job_id == job.id,
            JobEvaluation.snapshot_id == (snapshot.id if snapshot else None),
            or_(JobEvaluation.user_id == user_id, JobEvaluation.user_id.is_(None)),
        )
        .order_by(JobEvaluation.evaluated_at.desc(), JobEvaluation.id)
        .limit(1)
    )
    rules = (
        list(session.scalars(select(RuleResult).where(RuleResult.evaluation_id == evaluation.id))) if evaluation else []
    )
    app = application_service.active_application(session, user_id, job.id)
    enrichment = session.scalar(
        select(EnrichmentRun)
        .where(EnrichmentRun.job_id == job.id)
        .order_by(EnrichmentRun.started_at.desc(), EnrichmentRun.id)
        .limit(1)
    )
    snapshot_payload = _columns(snapshot, ("raw_evidence_reference",)) if snapshot else None
    if snapshot_payload:
        fields = dict(snapshot_payload["structured_fields"])
        relevance = (evaluation.evidence or {}).get("relevance", {}) if evaluation else {}
        facts = (evaluation.evidence or {}).get("facts", []) if evaluation else []
        evidence_fields = fields.get("job_evidence", {})
        fields.update(
            {
                "summary": relevance.get("summary"),
                "match_reason": relevance.get("reason"),
                "matched_skills": relevance.get("direct_skills", []),
                "missing_skills": relevance.get("missing_requested_skills", []),
                "related_skills": relevance.get("related_skills", {}),
                "employment_type": evidence_fields.get("employment_type"),
                "salary": evidence_fields.get("salary"),
            }
        )
        experience_clauses = []
        for fact in facts:
            if fact.get("field") == "experience":
                for reference in fact.get("evidence", []):
                    if reference.get("text"):
                        experience_clauses.append(reference["text"])
        if experience_clauses:
            fields["experience"] = "; ".join(dict.fromkeys(experience_clauses))
        snapshot_payload["structured_fields"] = fields
    return {
        **_columns(job),
        "company": group.canonical_name,
        "snapshot": snapshot_payload,
        "state": application_service.state_dict(state)
        if state
        else {"is_saved": False, "saved_at": None, "viewed_at": None, "dismissed_at": None, "revision": 0},
        "sources": [
            _columns(source, ("link_evidence",))
            for source in session.scalars(select(JobSource).where(JobSource.job_id == job.id).order_by(JobSource.id))
        ],
        "application_id": str(app.id) if app else None,
        "eligibility": {
            "decision": evaluation.decision,
            "evaluated_at": evaluation.evaluated_at,
            "rules": [_columns(rule) for rule in rules],
        }
        if evaluation
        else None,
        "people_enrichment_state": enrichment.state if enrichment else "NOT_CONFIGURED",
    }


def _app_details(session, user_id, app):
    snapshot = session.get(JobSnapshot, app.selected_snapshot_id) if app.selected_snapshot_id else None
    return {
        **application_service.application_dict(app),
        "snapshot": _columns(snapshot, ("raw_evidence_reference",))
        if snapshot
        else (
            {"id": None, "description": app.manual_description, "origin": "MANUAL"} if app.manual_description else None
        ),
        "manual_description": app.manual_description,
        "events": [
            _columns(event)
            for event in session.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.application_id == app.id)
                .order_by(ApplicationEvent.recorded_at, ApplicationEvent.id)
            )
        ],
    }


def _mutation(session, user, key, command, target, payload, action):
    return application_service.execute_operation(session, user.id, key, command, target, payload, action)


DEFAULT_FAMILIES = [
    "Data analysis",
    "Business analysis",
    "Business intelligence",
    "Operations and revenue",
    "AI and machine learning",
    "Analytics engineering",
    "Deployment",
    "Domain analysis",
]
DEFAULT_SKILLS = [
    "SQL",
    "Power BI",
    "Python",
    "Excel",
    "machine learning",
    "Snowflake",
    "AI",
    "LLMs",
    "forecasting",
    "business analysis",
    "Tableau",
    "VLOOKUP",
    "XLOOKUP",
    "Qlik",
    "pandas",
    "Databricks",
    "statistics",
    "data analysis",
]


def _profile(session, user):
    profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == user.id))
    if not profile:
        application_service.lock_user(session, user.id)
        profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == user.id))
        if profile:
            return profile
        profile = SearchProfile(
            user_id=user.id,
            role_families=DEFAULT_FAMILIES,
            skills=DEFAULT_SKILLS,
            aliases={
                "Power BI": ["PowerBI", "PowwerBI"],
                "AI": ["artificial intelligence"],
                "LLMs": ["large language models"],
            },
        )
        session.add(profile)
        session.flush()
        session.add(SearchProfileVersion(user_id=user.id, version=1, payload=_columns(profile)))
        application_service.change(session, user.id, "profile", profile.id, 1)
    return profile


@router.get("/profile")
def profile(user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    return _columns(_profile(session, user))


@router.patch("/profile")
def patch_profile(
    payload: ProfilePatch,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    def action():
        profile = _profile(session, user)
        application_service.require_revision(profile.revision, payload.expected_revision)
        for name, value in payload.model_dump(exclude_none=True, exclude={"expected_revision"}).items():
            setattr(profile, name, value)
        profile.version += 1
        profile.revision += 1
        session.add(SearchProfileVersion(user_id=user.id, version=profile.version, payload=_columns(profile)))
        application_service.change(session, user.id, "profile", profile.id, profile.revision)
        return _columns(profile)

    return _mutation(session, user, key, "profile", user.id, payload.model_dump(mode="json"), action)


@router.get("/watchlist")
def watchlist(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return _page(
        session,
        select(WatchlistEntry).where(WatchlistEntry.user_id == user.id, WatchlistEntry.enabled.is_(True)),
        WatchlistEntry.id,
        cursor,
        limit,
        lambda entry: {
            **_columns(entry),
            "company": session.get(EmployerGroup, entry.employer_group_id).canonical_name
            if entry.employer_group_id
            else entry.requested_name,
            "resolution_state": "REGISTERED" if entry.employer_group_id else "PENDING",
        },
    )


@router.post("/watchlist")
def add_watchlist(
    payload: WatchlistInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    def action():
        if payload.employer_group_id:
            group = session.get(EmployerGroup, payload.employer_group_id)
            if not group:
                raise DomainError(
                    "EMPLOYER_UNRESOLVED",
                    "Select a registered employer group or submit a company name for resolution.",
                    422,
                )
            identity = WatchlistEntry.employer_group_id == payload.employer_group_id
        else:
            identity = and_(
                WatchlistEntry.employer_group_id.is_(None),
                func.lower(WatchlistEntry.requested_name) == payload.company_name.lower(),
            )
        entry = session.scalar(select(WatchlistEntry).where(WatchlistEntry.user_id == user.id, identity))
        if not entry:
            entry = WatchlistEntry(
                user_id=user.id, employer_group_id=payload.employer_group_id, requested_name=payload.company_name
            )
            session.add(entry)
            session.flush()
        elif not entry.enabled:
            entry.enabled = True
            entry.revision += 1
        application_service.change(session, user.id, "watchlist", entry.id, entry.revision)
        return {
            **_columns(entry),
            "company": group.canonical_name if payload.employer_group_id else entry.requested_name,
            "resolution_state": "REGISTERED" if entry.employer_group_id else "PENDING",
        }

    return _mutation(session, user, key, "watchlist.add", user.id, payload.model_dump(mode="json"), action)


@router.delete("/watchlist/{entry_id}")
def delete_watchlist(
    entry_id: UUID,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    def action():
        entry = session.scalar(
            select(WatchlistEntry).where(WatchlistEntry.id == entry_id, WatchlistEntry.user_id == user.id)
        )
        if not entry:
            raise DomainError("NOT_FOUND", "Watchlist entry not found.", 404)
        if entry.enabled:
            entry.enabled = False
            entry.revision += 1
            application_service.change(session, user.id, "watchlist", entry.id, entry.revision, True)
        return _columns(entry)

    return _mutation(session, user, key, "watchlist.delete", entry_id, {}, action)


@router.get("/employer-groups")
def employer_groups(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    keyword: str = "",
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return _page(
        session,
        select(EmployerGroup).where(EmployerGroup.canonical_name.ilike(f"%{keyword}%")),
        EmployerGroup.id,
        cursor,
        limit,
        _columns,
    )


@router.get("/jobs")
def jobs(
    scope: Literal["today", "history", "priority"] = "today",
    posted_within_hours: int | None = Query(None, description="Freshness window: 24, 48 or 72 hours"),
    work_arrangement: str | None = None,
    family: str | None = None,
    company: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
):
    # Query strings arrive as text; an int Literal would reject the client's own "72" with 422.
    if posted_within_hours is not None and posted_within_hours not in (24, 48, 72):
        raise DomainError("VALIDATION_ERROR", "posted_within_hours must be 24, 48 or 72.", 422)
    stmt = select(Job).join(InitialDelivery, InitialDelivery.job_id == Job.id).where(InitialDelivery.user_id == user.id)
    if scope == "today":
        today = datetime.now(ZoneInfo("America/New_York")).date()
        stmt = stmt.join(Report, Report.id == InitialDelivery.report_id).where(Report.report_date == today)
    elif scope == "priority":
        stmt = stmt.where(InitialDelivery.channel == "PRIORITY")
    publication_order = func.coalesce(Job.published_at, Job.published_latest, Job.published_earliest)
    if posted_within_hours:
        oldest_possible = func.coalesce(Job.published_earliest, Job.published_at)
        stmt = stmt.where(oldest_possible >= datetime.now(UTC) - timedelta(hours=posted_within_hours))
    if work_arrangement:
        stmt = stmt.where(Job.work_arrangement == work_arrangement)
    if family:
        stmt = stmt.where(Job.role_family == family)
    if company:
        stmt = stmt.join(EmployerGroup).where(EmployerGroup.canonical_name.ilike(f"%{company}%"))
    if keyword:
        stmt = stmt.where(Job.title.ilike(f"%{keyword}%"))
    if source:
        stmt = stmt.where(
            Job.id.in_(select(JobSource.job_id).join(SourceRegistry).where(SourceRegistry.connector_type == source))
        )
    # Cursor stores publication and ID for an immutable/stable newest-first feed.
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            published = datetime.fromisoformat(decoded["published"]) if decoded["published"] else None
            job_id = UUID(decoded["id"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            raise DomainError("INVALID_CURSOR", "Invalid job page cursor.", 422)
        stmt = stmt.where(
            or_(
                publication_order < published,
                publication_order.is_(None),
                and_(publication_order == published, Job.id > job_id),
            )
            if published
            else and_(publication_order.is_(None), Job.id > job_id)
        )
    rows = list(session.scalars(stmt.order_by(publication_order.desc().nullslast(), Job.id).limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "published": (
                        rows[-1].published_at or rows[-1].published_latest or rows[-1].published_earliest
                    ).isoformat()
                    if (rows[-1].published_at or rows[-1].published_latest or rows[-1].published_earliest)
                    else None,
                    "id": str(rows[-1].id),
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
        if more
        else None
    )
    return {"items": [_job(session, user.id, row) for row in rows], "next_cursor": next_cursor, "has_more": more}


@router.get("/jobs/{job_id}")
def job_detail(job_id: UUID, user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    return _job(session, user.id, _accessible_job(session, user.id, job_id))


@router.get("/jobs/{job_id}/evidence")
def job_evidence(job_id: UUID, user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    job = _accessible_job(session, user.id, job_id)
    evaluations = list(
        session.scalars(
            select(JobEvaluation)
            .where(
                JobEvaluation.job_id == job.id, or_(JobEvaluation.user_id == user.id, JobEvaluation.user_id.is_(None))
            )
            .order_by(JobEvaluation.evaluated_at.desc(), JobEvaluation.id)
        )
    )
    return {
        "items": [
            {
                **_columns(evaluation),
                "rules": [
                    _columns(rule)
                    for rule in session.scalars(select(RuleResult).where(RuleResult.evaluation_id == evaluation.id))
                ],
            }
            for evaluation in evaluations
        ],
        "next_cursor": None,
        "has_more": False,
    }


@router.get("/jobs/{job_id}/snapshots")
def job_snapshots(
    job_id: UUID,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    job = _accessible_job(session, user.id, job_id)
    return _page(
        session,
        select(JobSnapshot).where(JobSnapshot.job_id == job.id),
        JobSnapshot.id,
        cursor,
        limit,
        lambda row: _columns(row, ("raw_evidence_reference",)),
    )


@router.post("/jobs/{job_id}/view")
def view_job(
    job_id: UUID,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    _accessible_job(session, user.id, job_id)
    return _mutation(
        session, user, key, "view", job_id, {}, lambda: application_service.record_open(session, user.id, job_id, key)
    )


@router.post("/jobs/{job_id}/application-open")
def open_job(
    job_id: UUID,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    _accessible_job(session, user.id, job_id)
    return _mutation(
        session,
        user,
        key,
        "open",
        job_id,
        {},
        lambda: application_service.record_open(session, user.id, job_id, key, True),
    )


@router.put("/jobs/{job_id}/saved")
def save_job(
    job_id: UUID,
    payload: SaveInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    _accessible_job(session, user.id, job_id)
    return _mutation(
        session,
        user,
        key,
        "save",
        job_id,
        payload.model_dump(mode="json"),
        lambda: application_service.set_saved(session, user.id, job_id, payload, key),
    )


@router.put("/jobs/{job_id}/dismissed")
def dismiss_job(
    job_id: UUID,
    payload: DismissInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    _accessible_job(session, user.id, job_id)
    return _mutation(
        session,
        user,
        key,
        "dismiss",
        job_id,
        payload.model_dump(mode="json"),
        lambda: application_service.set_dismissed(session, user.id, job_id, payload, key),
    )


@router.post("/jobs/{job_id}/apply")
def apply_job(
    job_id: UUID,
    payload: ApplyInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    _accessible_job(session, user.id, job_id)
    return _mutation(
        session,
        user,
        key,
        "apply",
        job_id,
        payload.model_dump(mode="json"),
        lambda: application_service.mark_applied(session, user.id, job_id, payload, key),
    )


@router.get("/saved-jobs")
def saved_jobs(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return _page(
        session,
        select(Job)
        .join(UserJobState, UserJobState.job_id == Job.id)
        .where(UserJobState.user_id == user.id, UserJobState.is_saved.is_(True)),
        Job.id,
        cursor,
        limit,
        lambda row: _job(session, user.id, row),
        sort_column=UserJobState.saved_at,
    )


@router.get("/applications")
def applications(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    status: str | None = None,
    keyword: str | None = None,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    stmt = select(Application).where(Application.user_id == user.id, Application.voided_at.is_(None))
    if status == "AWAITING_RESPONSE":
        stmt = stmt.where(
            Application.current_status == "APPLIED", Application.applied_at <= datetime.now(UTC) - timedelta(hours=24)
        )
    elif status:
        stmt = stmt.where(Application.current_status == status)
    if keyword:
        stmt = stmt.where(or_(Application.title.ilike(f"%{keyword}%"), Application.company.ilike(f"%{keyword}%")))
    return _page(session, stmt, Application.id, cursor, limit, application_service.application_dict)


@router.post("/applications")
def manual_application(
    payload: ManualApplicationInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "manual",
        user.id,
        payload.model_dump(mode="json"),
        lambda: application_service.create_manual(session, user.id, payload, key),
    )


@router.get("/applications/{application_id}")
def application_detail(application_id: UUID, user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    return _app_details(session, user.id, application_service.get_owned_application(session, user.id, application_id))


@router.patch("/applications/{application_id}")
def update_application(
    application_id: UUID,
    payload: ApplicationPatch,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "notes",
        application_id,
        payload.model_dump(mode="json"),
        lambda: application_service.patch_application(session, user.id, application_id, payload, key),
    )


@router.post("/applications/{application_id}/events")
def status_event(
    application_id: UUID,
    payload: StatusInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "status",
        application_id,
        payload.model_dump(mode="json"),
        lambda: application_service.add_status_event(session, user.id, application_id, payload, key),
    )


@router.post("/applications/{application_id}/corrections")
def correction(
    application_id: UUID,
    payload: CorrectionInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "correction",
        application_id,
        payload.model_dump(mode="json"),
        lambda: application_service.correct_event(session, user.id, application_id, payload, key),
    )


@router.get("/dashboard")
def dashboard(user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    apps = list(
        session.scalars(
            select(Application)
            .where(Application.user_id == user.id, Application.voided_at.is_(None))
            .order_by(Application.applied_at.desc(), Application.id)
        )
    )
    items = [application_service.application_dict(app) for app in apps]
    counts = {}
    for item in items:
        counts[item["display_status"]] = counts.get(item["display_status"], 0) + 1
    gmail = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))
    return {
        "total": len(items),
        "counts": counts,
        "items": items,
        "email_sync_health": gmail.sync_health if gmail else "NOT_CONFIGURED",
    }


def _report(session, user_id, report):
    rows = session.execute(
        select(ReportJob, Job)
        .join(Job, Job.id == ReportJob.job_id)
        .where(ReportJob.report_id == report.id)
        .order_by(Job.published_at.desc(), Job.id)
    ).all()
    return {
        **_columns(report),
        "jobs": [_job(session, user_id, job, member.snapshot_id) for member, job in rows],
        "count": len(rows),
    }


@router.get("/reports")
def reports(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return _page(
        session,
        select(Report).where(Report.user_id == user.id),
        Report.id,
        cursor,
        limit,
        lambda row: {
            **_columns(row),
            "count": session.scalar(select(func.count()).select_from(ReportJob).where(ReportJob.report_id == row.id)),
        },
    )


@router.get("/reports/today")
def today_report(user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    today = datetime.now(ZoneInfo("America/New_York")).date()
    row = session.scalar(select(Report).where(Report.user_id == user.id, Report.report_date == today))
    if not row:
        return {"report": None, "state": "NOT_RELEASED", "report_date": today}
    return _report(session, user.id, row)


@router.get("/reports/companies")
def previously_shown_companies(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    statement = select(CompanyCycleUsage).where(CompanyCycleUsage.user_id == user.id)

    def render(row):
        group = session.get(EmployerGroup, row.employer_group_id)
        cycle = session.get(CompanyCycle, row.cycle_id)
        return {
            **_columns(row),
            "company": group.canonical_name,
            "cycle_start": cycle.start_date,
            "cycle_end_exclusive": cycle.end_date,
            "next_regular_eligibility_date": cycle.end_date,
        }

    return _page(
        session, statement, CompanyCycleUsage.id, cursor, limit, render, sort_column=CompanyCycleUsage.report_date
    )


@router.get("/reports/{report_id}")
def report_detail(report_id: UUID, user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    row = session.scalar(select(Report).where(Report.id == report_id, Report.user_id == user.id))
    if not row:
        raise DomainError("NOT_FOUND", "Report not found.", 404)
    return _report(session, user.id, row)


@router.get("/notifications")
def notifications(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    unread_only: bool = False,
    cursor: UUID | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return notification_service.list_notifications(
        session, user.id, unread_only=unread_only, cursor=cursor, limit=limit
    )


@router.get("/notifications/unread-count")
def unread_count(user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    return {"unread_count": notification_service.unread_count(session, user.id)}


@router.post("/notifications/read-all")
def read_all_notifications(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "notification.read_all",
        user.id,
        {},
        lambda: notification_service.mark_all_read(session, user.id),
    )


@router.post("/notifications/delete-all")
def delete_all_notifications(
    payload: DeleteNotificationsInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "notification.delete_all",
        user.id,
        payload.model_dump(),
        lambda: notification_service.delete_all(session, user.id, read_only=payload.read_only),
    )


@router.put("/notifications/{notification_id}/read")
def read_notification(
    notification_id: UUID,
    payload: ReadInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "notification.read",
        notification_id,
        payload.model_dump(),
        lambda: notification_service.set_read(session, user.id, notification_id, payload.read),
    )


@router.post("/notifications/{notification_id}/open")
def open_notification(
    notification_id: UUID,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    return _mutation(
        session,
        user,
        key,
        "notification.open",
        notification_id,
        {},
        lambda: notification_service.open_notification(session, user.id, notification_id),
    )


@router.get("/sync/changes")
def sync_changes(
    cursor: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
):
    return sync_service.changes_page(session, user.id, cursor=cursor, limit=limit)


@router.post("/sync/operations")
def sync_operations(payload: SyncOperations, user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    mapping = {
        "save": (SaveInput, application_service.set_saved),
        "apply": (ApplyInput, application_service.mark_applied),
        "dismiss": (DismissInput, application_service.set_dismissed),
        "notes": (ApplicationPatch, application_service.patch_application),
        "status": (StatusInput, application_service.add_status_event),
        "correction": (CorrectionInput, application_service.correct_event),
    }
    results = []
    for operation in payload.operations:
        try:
            with session.begin_nested():
                schema, handler = mapping[operation.command]
                command_payload = schema.model_validate(operation.payload)
                if operation.command in ("save", "apply", "dismiss"):
                    _accessible_job(session, user.id, operation.target_id)
                result = _mutation(
                    session,
                    user,
                    operation.operation_id,
                    operation.command,
                    operation.target_id,
                    command_payload.model_dump(mode="json"),
                    lambda handler=handler, operation=operation, command_payload=command_payload: handler(
                        session, user.id, operation.target_id, command_payload, operation.operation_id
                    ),
                )
                results.append({"operation_id": operation.operation_id, "status": "accepted", "result": result})
        except (DomainError, NotificationError, SyncError) as error:
            results.append(
                {
                    "operation_id": operation.operation_id,
                    "status": "conflict" if error.status_code == 409 else "error",
                    "error": {
                        "code": error.code,
                        "user_message": error.user_message,
                        "retryable": error.retryable,
                        "details": getattr(error, "details", {}),
                    },
                }
            )
        except ValidationError:
            results.append(
                {
                    "operation_id": operation.operation_id,
                    "status": "error",
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "user_message": "The queued command contains invalid fields.",
                        "retryable": False,
                    },
                }
            )
    return {"results": results}


@router.get("/search-runs")
def search_runs(
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    cursor: str | None = None,
    limit: int = Query(25, ge=1, le=100),
):
    return _page(session, select(SearchRun).where(SearchRun.user_id == user.id), SearchRun.id, cursor, limit, _columns)


@router.get("/search-runs/{run_id}")
def search_run(run_id: UUID, user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    row = session.scalar(select(SearchRun).where(SearchRun.id == run_id, SearchRun.user_id == user.id))
    if not row:
        raise DomainError("NOT_FOUND", "Search run not found.", 404)
    return {
        **_columns(row),
        "connectors": [
            _columns(item) for item in session.scalars(select(ConnectorRun).where(ConnectorRun.search_run_id == run_id))
        ],
    }


@router.get("/connectors/health")
def connector_health(user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY):
    return {
        "items": [
            _columns(row)
            for row in session.scalars(
                select(SourceRegistry).order_by(SourceRegistry.connector_type, SourceRegistry.tenant)
            )
        ]
    }


@router.post("/sync/snapshot")
def sync_snapshot_start(
    user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY, limit: int = Query(25, ge=1, le=100)
):
    from app.sync.snapshot import start_snapshot

    return start_snapshot(session, user.id, limit=limit)


@router.get("/sync/snapshot/{snapshot_id}")
def sync_snapshot_page(
    snapshot_id: UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
):
    from app.sync.snapshot import snapshot_page

    return snapshot_page(session, user.id, snapshot_id, offset=offset, limit=limit)


from app.api.admin import router as admin_router

router.include_router(admin_router)
