from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.db.models import GmailConnection, Report, SearchRun, SourceRegistry, User
from app.reports.selection import EASTERN, recovery_dates, release_at
from app.workers.service import enqueue


def source_interval(source):
    tags = {str(tag).upper() for tag in source.pool_tags or []}
    if "WATCHLIST" in tags:
        return 900
    if "CONNECTICUT" in tags:
        return 1800
    if tags.intersection({"UNIVERSITY", "NYC", "BAY_AREA", "NYC_STARTUP", "BAY_AREA_STARTUP"}):
        return 3600
    return 28800 if source.connector_type == "jobspy" or source.connector_type.startswith("jobspy:") else 14400


def schedule_due(session, *, now=None):
    now = now or datetime.now(UTC)
    today = now.astimezone(EASTERN).date()
    counts = 0
    for user in session.scalars(select(User)):
        # Serialize schedules with user actions; unique keys protect multiple Beat instances.
        session.execute(select(User).where(User.id == user.id).with_for_update())
        last = session.scalar(select(func.max(Report.report_date)).where(Report.user_id == user.id))
        due, missed = recovery_dates(now=now, last_report_date=last)
        for missed_day in missed:
            stamp = datetime.combine(missed_day, datetime.min.time(), tzinfo=EASTERN).astimezone(UTC)
            if not session.scalar(
                select(SearchRun.id).where(
                    SearchRun.user_id == user.id, SearchRun.scheduled_at == stamp, SearchRun.state == "MISSED"
                )
            ):
                session.add(
                    SearchRun(
                        user_id=user.id,
                        scheduled_at=stamp,
                        started_at=now,
                        finished_at=now,
                        state="MISSED",
                        errors=[{"code": "SERVER_OUTAGE", "date": str(missed_day)}],
                    )
                )
        sources = session.scalars(select(SourceRegistry).where(SourceRegistry.enabled.is_(True))).all()
        for source in sources:
            retry_after = (source.capabilities or {}).get("runtime_retry_after")
            if retry_after:
                try:
                    retry_at = datetime.fromisoformat(str(retry_after))
                except (TypeError, ValueError):
                    retry_at = None
                if retry_at and retry_at.tzinfo is not None and retry_at > now:
                    continue
            seconds = source_interval(source)
            # Stable per-source phase keeps subsequent polling distributed.
            phase = int(source.id.hex[:8], 16) % seconds
            bucket = (int(now.timestamp()) - phase) // seconds
            enqueue(
                session,
                "SEARCH_SOURCE",
                {"source_id": str(source.id), "user_id": str(user.id)},
                f"source:{user.id}:{source.id}:{bucket}",
            )
            counts += 1
            # Start a dedicated preparation pass at 10:30 Eastern, regardless
            # of the ordinary source cadence. Unique date keys survive restarts.
            if now >= release_at(today) - timedelta(minutes=30):
                enqueue(
                    session,
                    "SEARCH_SOURCE",
                    {"source_id": str(source.id), "user_id": str(user.id), "report_preparation": str(today)},
                    f"report-prep:{user.id}:{source.id}:{today}",
                )
                counts += 1
        # Schedule release after searches in this transaction. The report domain
        # re-evaluates retained evidence at commit; slow/failed sources remain
        # explicitly partial. No indefinite provider wait delays valid results.
        if due:
            enqueue(session, "BUILD_REPORT", {"user_id": str(user.id), "date": str(today)}, f"report:{user.id}:{today}")
            counts += 1
        connection = session.scalar(
            select(GmailConnection).where(GmailConnection.user_id == user.id, GmailConnection.revoked_at.is_(None))
        )
        if connection and connection.refresh_token_encrypted:
            enqueue(session, "GMAIL_SYNC", {"user_id": str(user.id)}, f"gmail:{user.id}:{int(now.timestamp()) // 300}")
    return counts
