from __future__ import annotations

from datetime import UTC, datetime, timedelta
from secrets import randbelow
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import OutboxEvent, WorkItem


def enqueue(session: Session, task_type: str, payload: dict, key: str) -> WorkItem:
    now = datetime.now(UTC)
    identifier = session.scalar(
        insert(WorkItem)
        .values(
            id=uuid4(),
            task_key=key,
            task_type=task_type,
            payload=payload,
            state="PENDING",
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        .on_conflict_do_nothing(index_elements=["task_key"])
        .returning(WorkItem.id)
    )
    if identifier:
        session.add(OutboxEvent(event_key=f"work:{key}", event_type="WORK", payload={"work_id": str(identifier)}))
    else:
        identifier = session.scalar(select(WorkItem.id).where(WorkItem.task_key == key))
    session.flush()
    return session.get(WorkItem, identifier)


LOST_MESSAGE_MINUTES = 10


def reconcile(session: Session, *, now=None) -> int:
    """Requeue lost messages as well as expired leases; Redis is never authoritative."""
    now = now or datetime.now(UTC)
    # A published message can legitimately wait behind long source runs; re-publishing it
    # every couple of minutes only floods the broker with duplicates of the same work.
    lost_events = session.scalars(
        select(OutboxEvent)
        .where(
            OutboxEvent.state == "DISPATCHED", OutboxEvent.dispatched_at < now - timedelta(minutes=LOST_MESSAGE_MINUTES)
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    for event in lost_events:
        event.state, event.next_attempt_at, event.lease_expires_at = "RETRY", now, None
    rows = session.scalars(
        select(WorkItem)
        .where(
            WorkItem.state.in_(["PENDING", "QUEUED", "RUNNING", "RETRY", "DEFERRED"]),
            WorkItem.next_attempt_at <= now,
            or_(WorkItem.lease_expires_at.is_(None), WorkItem.lease_expires_at <= now),
        )
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    for row in rows:
        if row.attempts >= 3 and row.state != "DEFERRED":
            row.state, row.last_error = "FAILED", "ATTEMPT_LIMIT"
            continue
        row.state, row.lease_owner = "QUEUED", None
        row.lease_expires_at = now + timedelta(minutes=LOST_MESSAGE_MINUTES)
        # A new dispatch event is okay: work key remains the business-effect boundary.
        event_key = f"reconcile:{row.id}:{int(now.timestamp()) // 60}"
        session.execute(
            insert(OutboxEvent)
            .values(
                id=uuid4(),
                event_key=event_key,
                event_type="WORK",
                payload={"work_id": str(row.id)},
                state="PENDING",
                attempts=0,
                created_at=now,
                next_attempt_at=now,
            )
            .on_conflict_do_nothing(index_elements=["event_key"])
        )
    return len(rows)


# Broker priority (0 = first). Inbox and mail sync must never wait behind long source scans:
# a few search-style sources with several queries each can keep both worker slots busy for
# most of an hour, and the owner's Gmail sync would otherwise starve.
WORK_PRIORITY = {
    "NOTIFICATION_DELIVERY": 0,
    "GMAIL_SYNC": 1,
    "BUILD_REPORT": 2,
    "SEARCH_SOURCE": 6,
    "PEOPLE_ENRICH": 7,
}


def event_priority(session, event) -> int:
    if event.event_type in {"WORK", "work.ready"}:
        work_id = (event.payload or {}).get("work_id")
        row = session.get(WorkItem, UUID(work_id)) if work_id else None
        if row is None:
            return 5
        if row.task_type == "SEARCH_SOURCE" and (row.payload or {}).get("report_preparation"):
            return 3  # The 10:30 preparation pass feeds today's report.
        return WORK_PRIORITY.get(row.task_type, 5)
    return 0  # notification.created / application.changed are tiny and user-facing.


def _publish(publish, event_id, priority):
    try:
        return publish(event_id, priority)
    except TypeError:
        return publish(event_id)  # Single-argument publishers (tests, older callers).


def dispatch_once(session_factory, publish, *, now=None) -> int:
    now = now or datetime.now(UTC)
    with session_factory() as session, session.begin():
        events = session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.state.in_(["PENDING", "RETRY", "DISPATCHING"]),
                OutboxEvent.next_attempt_at <= now,
                or_(OutboxEvent.lease_expires_at.is_(None), OutboxEvent.lease_expires_at <= now),
            )
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(50)
        ).all()
        ids = []
        for event in events:
            event.state, event.lease_owner = "DISPATCHING", str(uuid4())
            event.lease_expires_at = now + timedelta(minutes=2)
            event.attempts += 1
            ids.append((event.id, event.lease_owner, event.attempts, event_priority(session, event)))
    count = 0
    for event_id, claim_owner, attempts, priority in ids:
        try:
            _publish(publish, str(event_id), priority)
            values = {"state": "DISPATCHED", "dispatched_at": datetime.now(UTC), "lease_expires_at": None}
            count += 1
        except Exception as exc:  # noqa: BLE001 - Broker implementations raise distinct transport errors.
            values = {
                "state": "RETRY",
                "last_error": type(exc).__name__,
                "lease_expires_at": None,
                "next_attempt_at": now + timedelta(seconds=min(3600, 2 ** min(attempts, 11))),
            }
        with session_factory() as session, session.begin():
            # A fast worker may already have committed PROCESSED. Never regress
            # that state to DISPATCHED after publication returns.
            session.execute(
                update(OutboxEvent)
                .where(
                    OutboxEvent.id == event_id,
                    OutboxEvent.state == "DISPATCHING",
                    OutboxEvent.lease_owner == claim_owner,
                )
                .values(**values)
            )
    return count


TERMINAL_STATES = {"SUCCEEDED", "NOT_CONFIGURED", "FAILED", "PARTIAL", "RECONNECT_REQUIRED", "BLOCKED", "TOKEN_INVALID"}
RETRY_RESULTS = {"FAILED", "FAILURE", "UNAVAILABLE", "RATE_LIMITED", "RETRY", "DEGRADED"}
SUCCESS_RESULTS = {
    "SUCCEEDED",
    "READY",
    "HEALTHY",
    "CONNECTED",
    "SYNCING",
    "RECORDED",
    "MISSING",
    "NO_CREDIBLE_PROFILES",
    "PARTIALLY_FOUND",
}


def result_state(result: dict, attempts: int):
    """Keep truthful provider/coverage states separate from successful execution."""
    state = result.get("state", "SUCCEEDED")
    if state in RETRY_RESULTS:
        return "FAILED" if attempts >= 3 else "RETRY"
    if state == "PENDING_BUDGET":
        return "DEFERRED"
    if state in {"NOT_CONFIGURED", "RECONNECT_REQUIRED", "BLOCKED", "TOKEN_INVALID", "PARTIAL"}:
        return state
    if state in SUCCESS_RESULTS:
        return "SUCCEEDED"
    return "FAILED" if attempts >= 3 else "RETRY"


def execute_work(session_factory, work_id: UUID, handler):
    lease_owner = str(uuid4())
    now = datetime.now(UTC)
    with session_factory() as session, session.begin():
        row = session.scalar(select(WorkItem).where(WorkItem.id == work_id).with_for_update())
        if not row or row.state in TERMINAL_STATES:
            return "NOOP"
        if row.state in {"RETRY", "DEFERRED"} and row.next_attempt_at > now:
            return "NOT_DUE"
        if row.state == "RUNNING" and row.lease_expires_at and row.lease_expires_at > now:
            return "LEASED"
        row.state, row.lease_owner, row.lease_expires_at = "RUNNING", lease_owner, now + timedelta(minutes=15)
        row.attempts += 1
        task_type, payload = row.task_type, row.payload
    try:
        with session_factory() as session, session.begin():
            session.info["work_id"] = work_id
            result = handler(session, task_type, payload) or {}
            row = session.scalar(select(WorkItem).where(WorkItem.id == work_id).with_for_update())
            if row.lease_owner != lease_owner:
                raise RuntimeError("Work lease lost")
            row.state = result_state(result, row.attempts)
            row.result, row.lease_expires_at = result, None
            row.completed_at = None if row.state in {"RETRY", "DEFERRED"} else datetime.now(UTC)
            if row.state == "RETRY":
                row.last_error = str(result.get("state", "DEPENDENCY_FAILED"))[:200]
                row.next_attempt_at = datetime.now(UTC) + timedelta(
                    seconds=max(30 * 2**row.attempts, result.get("retry_after_seconds", 0)) + randbelow(15)
                )
            elif row.state == "DEFERRED":
                row.next_attempt_at = (datetime.now(UTC) + timedelta(days=1)).replace(
                    hour=0, minute=0, second=5, microsecond=0
                )
            return row.state
    except Exception as exc:
        with session_factory() as session, session.begin():
            row = session.scalar(select(WorkItem).where(WorkItem.id == work_id).with_for_update())
            if row and row.lease_owner == lease_owner:
                row.state = "FAILED" if row.attempts >= 3 else "RETRY"
                row.last_error, row.lease_expires_at = type(exc).__name__, None
                row.next_attempt_at = datetime.now(UTC) + timedelta(seconds=30 * 2**row.attempts)
        raise
