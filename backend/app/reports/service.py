"""Report and priority delivery share a PostgreSQL user lock and durable ledger."""

from collections import Counter
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import (
    Application,
    CompanyCycle,
    CompanyCycleUsage,
    InitialDelivery,
    Job,
    Notification,
    OutboxEvent,
    Report,
    ReportJob,
    SearchProfile,
    SourceRegistry,
    User,
    UserChange,
    UserJobState,
    WorkItem,
)
from app.reports.selection import EASTERN, Candidate, cycle_for, release_at, select_regular


def _canonical_suppression(session, identities):
    """Delivery/application/dismissal on a merged predecessor also suppresses its canonical job."""
    mapping = dict(session.execute(select(Job.id, Job.canonical_redirect_id)).all())
    result = set()
    for identifier in identities:
        if identifier is None:
            continue
        visited = set()
        while identifier is not None:
            if identifier in visited:
                raise ValueError("Canonical redirect cycle")
            visited.add(identifier)
            result.add(identifier)
            identifier = mapping.get(identifier)
    return result


def _latest_candidates(session: Session, user_id: UUID, now: datetime):
    # Reevaluate current snapshots even when no previous evaluation exists or the old one
    # refers to a superseded snapshot/profile. The user lock protects profile/delivery writes.
    delivered = _canonical_suppression(
        session, session.scalars(select(InitialDelivery.job_id).where(InitialDelivery.user_id == user_id))
    )
    applied = _canonical_suppression(
        session,
        session.scalars(
            select(Application.job_id).where(Application.user_id == user_id, Application.voided_at.is_(None))
        ),
    )
    dismissed = _canonical_suppression(
        session,
        session.scalars(
            select(UserJobState.job_id).where(UserJobState.user_id == user_id, UserJobState.dismissed_at.is_not(None))
        ),
    )
    jobs = session.scalars(
        select(Job)
        .where(Job.canonical_redirect_id.is_(None), Job.current_snapshot_id.is_not(None))
        .order_by(Job.id)
        .with_for_update()
    ).all()
    candidates, records, rejected = [], {}, Counter()
    settings = get_settings()
    for job in jobs:
        if job.id in delivered or job.id in applied or job.id in dismissed:
            rejected["ALREADY_DELIVERED_APPLIED_OR_DISMISSED"] += 1
            continue
        if job.synthetic and not (settings.app_env == "local" and settings.demo_mode):
            rejected["SYNTHETIC_PRODUCTION_EXCLUDED"] += 1
            continue
        from app.jobs.pipeline import reevaluate_job

        evaluation = reevaluate_job(session, job.id, user_id, now=now)
        eligible = evaluation.decision == "ELIGIBLE"
        if not eligible:
            rejected[evaluation.decision] += 1
        if job.published_earliest is None:
            rejected["PUBLICATION_NOT_ESTABLISHED"] += 1
            continue
        candidate = Candidate(
            str(job.id),
            str(job.employer_group_id),
            job.published_earliest,
            evaluation.evidence.get("salary_band", "B"),
            eligible,
            evaluation.valid_until,
            bool(evaluation.evidence.get("priority_reasons")),
            False,
            False,
            False,
        )
        candidates.append(candidate)
        records[str(job.id)] = (job, evaluation)
    return candidates, records, dict(rejected)


def _notify(session, user_id, kind, target_type, target_id, title, body, key):
    notification = Notification(
        user_id=user_id,
        notification_type=kind,
        target_type=target_type,
        target_id=target_id,
        title=title,
        body=body,
        event_dedupe_key=key,
    )
    session.add(notification)
    session.flush()
    session.add(UserChange(user_id=user_id, entity_type="notifications", entity_id=notification.id, revision=1))
    session.add(
        OutboxEvent(event_key=key, event_type="NOTIFICATION", payload={"notification_id": str(notification.id)})
    )
    return notification


def _queue_people(session, job, user_id):
    key = f"people:initial:{job.id}"
    if session.scalar(select(WorkItem.id).where(WorkItem.task_key == key)):
        return
    work = WorkItem(task_key=key, task_type="PEOPLE_ENRICH", payload={"job_id": str(job.id), "user_id": str(user_id)})
    session.add(work)
    session.flush()
    session.add(OutboxEvent(event_key=f"work:{key}", event_type="WORK", payload={"work_id": str(work.id)}))


def build_report(
    session: Session, user_id: UUID, report_date: date | None = None, *, now: datetime | None = None
) -> Report:
    now = now or datetime.now(UTC)
    today = now.astimezone(EASTERN).date()
    target = report_date or today
    user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise ValueError("Unknown user")
    existing = session.scalar(select(Report).where(Report.user_id == user_id, Report.report_date == target))
    if existing:
        if existing.status != "FINALIZED":
            raise ValueError("An unfinished report requires explicit recovery; it cannot be presented as finalized")
        return existing
    if target != today or now < release_at(today):
        raise ValueError("Only the current Eastern date may be released, at or after 11:00 AM")
    user.cycle_anchor = user.cycle_anchor or today
    index, start, end = cycle_for(user.cycle_anchor, today)
    cycle = session.scalar(
        select(CompanyCycle).where(CompanyCycle.user_id == user_id, CompanyCycle.cycle_index == index)
    )
    if cycle is None:
        cycle = CompanyCycle(
            user_id=user_id, cycle_index=index, start_date=start, end_date=end, anchor_date=user.cycle_anchor
        )
        session.add(cycle)
        session.flush()
    used_groups = {
        str(x)
        for x in session.scalars(
            select(CompanyCycleUsage.employer_group_id).where(
                CompanyCycleUsage.user_id == user_id, CompanyCycleUsage.cycle_id == cycle.id
            )
        )
    }
    candidates, records, withheld = _latest_candidates(session, user_id, now)
    settings = get_settings()
    if settings.company_daily_limit < 2:
        counts = Counter()
        reduced = []
        for candidate in sorted(candidates, key=lambda c: (c.salary_band, -c.published_at.timestamp(), c.job_id)):
            if (
                candidate.eligible
                and not candidate.priority
                and counts[candidate.employer_group_id] < settings.company_daily_limit
            ):
                reduced.append(candidate)
                counts[candidate.employer_group_id] += 1
        candidates = reduced
    chosen = select_regular(candidates, now=now, used_groups=used_groups, limit=settings.daily_job_limit)
    sources = session.scalars(select(SourceRegistry)).all()
    failed = [
        {"source": s.connector_type, "tenant": s.tenant, "state": s.configuration_state}
        for s in sources
        if s.enabled and s.configuration_state != "HEALTHY"
    ]
    unconfigured = sum(not s.enabled or s.configuration_state == "NOT_CONFIGURED" for s in sources)
    partial = bool(failed) or not any(s.enabled for s in sources)
    profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == user_id))
    report = Report(
        user_id=user_id,
        report_date=today,
        cycle_id=cycle.id,
        intended_release=release_at(today),
        actual_release=now,
        status="BUILDING",
        profile_version=profile.version if profile else 1,
        summary={
            "count": len(chosen),
            "limit": settings.daily_job_limit,
            "partial_coverage": partial,
            "delayed": now > release_at(today) + timedelta(minutes=1),
            "failed_sources": failed,
            "unconfigured_sources": unconfigured,
            "withheld": withheld,
            "supply": "FEWER_QUALIFYING_JOBS" if len(chosen) < settings.daily_job_limit else "FULL",
            "no_configured_sources": not any(s.enabled for s in sources),
        },
    )
    session.add(report)
    session.flush()
    counts = Counter(c.employer_group_id for c in chosen)
    for position, candidate in enumerate(chosen):
        job, evaluation = records[candidate.job_id]
        session.add(
            ReportJob(
                report_id=report.id,
                job_id=job.id,
                snapshot_id=job.current_snapshot_id,
                selection_band=candidate.salary_band,
                selection_order=position,
                evaluation_id=evaluation.id,
            )
        )
        session.add(
            InitialDelivery(
                user_id=user_id,
                job_id=job.id,
                channel="DAILY",
                report_id=report.id,
                snapshot_id=job.current_snapshot_id,
                delivered_at=now,
            )
        )
        session.add(UserChange(user_id=user_id, entity_type="jobs", entity_id=job.id, revision=1))
        _queue_people(session, job, user_id)
    for group_id, count in counts.items():
        session.add(
            CompanyCycleUsage(
                user_id=user_id,
                cycle_id=cycle.id,
                employer_group_id=UUID(group_id),
                report_id=report.id,
                report_date=today,
                count=count,
            )
        )
    session.add(UserChange(user_id=user_id, entity_type="reports", entity_id=report.id, revision=1))
    _notify(
        session,
        user_id,
        "DAILY_REPORT",
        "reports",
        report.id,
        "Your daily report is ready",
        f"{len(chosen)} qualifying jobs" + (" · partial source coverage" if partial else ""),
        f"report:{report.id}",
    )
    session.flush()
    report.status = "FINALIZED"
    session.flush()
    return report


def deliver_priority(session: Session, user_id: UUID, *, now: datetime | None = None) -> list[UUID]:
    now = now or datetime.now(UTC)
    session.execute(select(User).where(User.id == user_id).with_for_update()).scalar_one()
    candidates, records, _ = _latest_candidates(session, user_id, now)
    delivered = []
    for c in candidates:
        if (
            not c.priority
            or not c.eligible
            or c.delivered
            or c.applied
            or c.dismissed
            or c.valid_until is None
            or c.valid_until < now
        ):
            continue
        job, _evaluation = records[c.job_id]
        key = f"priority:{user_id}:{job.id}"
        session.add(
            InitialDelivery(
                user_id=user_id,
                job_id=job.id,
                channel="PRIORITY",
                snapshot_id=job.current_snapshot_id,
                delivered_at=now,
                alert_reference=key,
            )
        )
        _notify(session, user_id, "PRIORITY_JOB", "jobs", job.id, job.title, ", ".join(job.priority_reasons), key)
        session.add(UserChange(user_id=user_id, entity_type="jobs", entity_id=job.id, revision=1))
        _queue_people(session, job, user_id)
        delivered.append(job.id)
    session.flush()
    return delivered
