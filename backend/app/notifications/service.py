"""Authoritative inbox; push failure never deletes or replaces database history.

All functions participate in the caller's transaction and never commit.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.db.models import Notification, OutboxEvent
from app.notifications.contracts import COLLECTIONS, NotificationError, destination, target
from app.sync.contracts import validate_limit
from app.sync.service import lock_user, record_change


def as_dict(row: Notification) -> dict:
    return {
        "id": str(row.id),
        "type": row.notification_type,
        **destination(row.target_type, row.target_id),
        "title": row.title,
        "body": row.body,
        "created_at": row.created_at.isoformat(),
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "revision": row.revision,
    }


def create_notification(
    session: Session,
    user_id: UUID,
    type: str,
    target_type: str,
    target_id: UUID,
    title: str,
    body: str,
    event_dedupe_key: str,
) -> Notification:
    kind, identifier = target(target_type, target_id)
    if not type or len(type) > 50 or not title.strip() or len(title) > 250 or len(body) > 2000:
        raise NotificationError("INVALID_NOTIFICATION", "Notification content is invalid.")
    if not event_dedupe_key or len(event_dedupe_key) > 250:
        raise NotificationError("INVALID_EVENT_KEY", "A bounded event deduplication key is required.")
    lock_user(session, user_id)
    existing = session.scalar(
        select(Notification).where(Notification.user_id == user_id, Notification.event_dedupe_key == event_dedupe_key)
    )
    if existing:
        if (existing.notification_type, existing.target_type, existing.target_id) != (
            type,
            COLLECTIONS[kind],
            identifier,
        ):
            raise NotificationError("EVENT_KEY_CONFLICT", "The event key already identifies another notification.", 409)
        return existing
    row = Notification(
        user_id=user_id,
        notification_type=type,
        target_type=COLLECTIONS[kind],
        target_id=identifier,
        title=title,
        body=body,
        event_dedupe_key=event_dedupe_key,
        created_at=datetime.now(UTC),
        revision=1,
    )
    session.add(row)
    session.flush()
    record_change(session, user_id, "notifications", row.id, row.revision)
    # Transport handlers fetch authorized notification/device state using only this ID.
    session.add(
        OutboxEvent(
            event_key=f"notification:{row.id}",
            event_type="notification.created",
            payload={"notification_id": str(row.id), "user_id": str(user_id)},
        )
    )
    session.flush()
    return row


def _owned(session: Session, user_id: UUID, notification_id: UUID) -> Notification:
    row = session.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    if row is None:
        raise NotificationError("NOT_FOUND", "Notification not found.", 404)
    return row


def unread_count(session: Session, user_id: UUID) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


def list_notifications(
    session: Session,
    user_id: UUID,
    *,
    unread_only: bool = False,
    cursor: UUID | None = None,
    limit: int = 25,
) -> dict:
    validate_limit(limit)
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if cursor:
        previous = _owned(session, user_id, cursor)
        query = query.where(tuple_(Notification.created_at, Notification.id) < (previous.created_at, previous.id))
    rows = list(
        session.scalars(query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1))
    )
    page = rows[:limit]
    return {
        "items": [as_dict(row) for row in page],
        "next_cursor": str(page[-1].id) if len(rows) > limit else None,
        "has_more": len(rows) > limit,
        "unread_count": unread_count(session, user_id),
    }


def set_read(
    session: Session,
    user_id: UUID,
    notification_id: UUID,
    read: bool = True,
    expected_revision: int | None = None,
) -> dict:
    lock_user(session, user_id)
    row = _owned(session, user_id, notification_id)
    already_satisfied = (row.read_at is not None) == read
    if not already_satisfied:
        if expected_revision is not None and row.revision != expected_revision:
            raise NotificationError(
                "REVISION_CONFLICT", "This notification changed on another device. Refresh before retrying.", 409
            )
        row.read_at = datetime.now(UTC) if read else None
        row.revision += 1
        record_change(session, user_id, "notifications", row.id, row.revision)
        session.flush()
    return {"notification": as_dict(row), "unread_count": unread_count(session, user_id)}


def open_notification(session: Session, user_id: UUID, notification_id: UUID) -> dict:
    result = set_read(session, user_id, notification_id, True)
    row = result["notification"]
    return {
        "notification_id": row["id"],
        **destination(row["target_type"], row["target_id"]),
        "unread_count": result["unread_count"],
        "revision": row["revision"],
    }
