from datetime import UTC, date, datetime
from uuid import UUID, uuid4

from celery import Celery
from sqlalchemy import select

from app.config import get_settings
from app.db.models import GmailConnection, OutboxEvent, SourceRegistry
from app.db.session import session_factory
from app.workers.service import enqueue, execute_work, reconcile

settings = get_settings()
celery_app = Celery("personal_staffer", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.schedule_timezone,
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=660,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 900, "queue_order_strategy": "priority"},
    task_default_priority=5,
    beat_schedule={"durable-minute": {"task": "staffer.tick", "schedule": 60.0}},
)


def handle_work(session, task_type, payload):
    user_id = UUID(payload["user_id"]) if payload.get("user_id") else None
    if task_type in {"BUILD_REPORT", "reports.build"}:
        from app.reports.service import build_report

        report = build_report(session, user_id, date.fromisoformat(payload["date"]))
        return {"report_id": str(report.id)}
    if task_type in {"SEARCH_SOURCE", "SOURCE_SEARCH", "search.run"}:
        from app.jobs.orchestration import run_source_batched
        from app.reports.service import deliver_priority

        factory = session_factory()
        run = run_source_batched(
            factory,
            UUID(payload["source_id"]),
            user_id,
            query=payload.get("query", ""),
            run_id=session.info.get("work_id"),
            max_elapsed_seconds=360,
        )
        # Search checkpoints are already committed. This caller transaction only
        # publishes eligible priority jobs and the worker result, with no network I/O.
        deliver_priority(session, user_id)
        source = session.get(SourceRegistry, UUID(payload["source_id"]))
        state = "PARTIAL" if run.state == "DEFERRED" else run.state
        if source.configuration_state in {"BLOCKED", "NOT_CONFIGURED"}:
            state = source.configuration_state
        return {
            "run_id": str(run.id),
            "state": state,
            "coverage_state": run.state,
            "source_health": source.configuration_state,
            "counts": run.counts,
            "retry_after": run.coverage.get("retry_after"),
        }
    if task_type in {"GMAIL_SYNC", "gmail.sync"}:
        from app.email.orchestration import synchronize_batched

        result = synchronize_batched(session_factory(), user_id, settings)
        if result.get("has_more"):
            enqueue(session, "GMAIL_SYNC", payload, f"gmail:continue:{user_id}:{uuid4()}")
        return result
    if task_type in {"PEOPLE_ENRICH", "people.enrich"}:
        from app.people.service import enrich

        # People owns short transactions so its query budget commits before provider I/O.
        return enrich(user_id, UUID(payload["job_id"]), settings, session_maker=session_factory())
    if task_type == "NOTIFICATION_DELIVERY":
        from app.notifications.delivery import deliver

        return deliver(session, UUID(payload["notification_id"]))
    raise ValueError(f"Unsupported task type: {task_type}")


@celery_app.task(name="staffer.event")
def process_event(event_id):
    factory = session_factory()
    with factory() as session:
        event = session.get(OutboxEvent, UUID(event_id))
        if not event or event.state == "PROCESSED":
            return
        event_type, payload = event.event_type, event.payload
    if event_type in {"WORK", "work.ready"}:
        try:
            execute_work(factory, UUID(payload["work_id"]), handle_work)
        except Exception as exc:
            from app.email.gmail import GmailUnavailable

            if isinstance(exc, GmailUnavailable):
                from app.db.models import WorkItem

                with factory() as session, session.begin():
                    work = session.get(WorkItem, UUID(payload["work_id"]))
                    user_id = UUID(work.payload["user_id"])
                    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id))
                    if connection:
                        connection.sync_health = exc.state
                    if exc.state in {"RECONNECT_REQUIRED", "NOT_CONFIGURED", "BLOCKED"}:
                        work.state, work.completed_at = exc.state, datetime.now(UTC)
                        work.result = {"state": exc.state, "processed": 0}
            raise
    elif event_type in {"NOTIFICATION", "notification.created"}:
        with factory() as session, session.begin():
            enqueue(session, "NOTIFICATION_DELIVERY", payload, f"notify:{payload['notification_id']}")
    elif event_type != "application.changed":
        raise ValueError("Unknown outbox event type")
    # application.changed already commits projections and inbox entries in its original transaction.
    with factory() as session, session.begin():
        event = session.get(OutboxEvent, UUID(event_id))
        event.state, event.lease_expires_at = "PROCESSED", None


@celery_app.task(name="staffer.tick")
def tick():
    from app.workers.schedule import schedule_due

    with session_factory()() as session, session.begin():
        schedule_due(session)
        reconcile(session)
