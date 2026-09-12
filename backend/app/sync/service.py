"""Transactional per-user change feed.

Every domain writer MUST call ``lock_user`` before reading mutable user state.
PostgreSQL sequences alone do not order commits: a slow transaction could commit
cursor 10 after the client already saw cursor 11. The user row lock serializes
allocation AND commit, avoiding that lost-change race. Helpers never commit.
"""

import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import User, UserChange
from app.sync.contracts import SyncError, utc, validate_cursor, validate_limit

RETENTION_DAYS = 90


def lock_user(session: Session, user_id: UUID) -> User:
    with session.no_autoflush:
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise SyncError("NOT_FOUND", "Account not found.", 404)
    return user


def record_change(
    session: Session,
    user_id: UUID,
    entity_type: str,
    entity_id: UUID,
    revision: int,
    tombstone: bool = False,
) -> UserChange:
    if not re.fullmatch(r"[A-Za-z][A-Za-z_\-]{0,49}", entity_type):
        raise SyncError("INVALID_ENTITY_TYPE", "Invalid changed entity type.", 422)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise SyncError("INVALID_REVISION", "Revision must be a nonnegative integer.", 422)
    lock_user(session, user_id)
    change = UserChange(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        revision=revision,
        tombstone=tombstone,
        committed_at=datetime.now(UTC),
    )
    session.add(change)
    session.flush()
    return change


def changes_page(
    session: Session,
    user_id: UUID,
    cursor: int = 0,
    limit: int = 25,
    *,
    now: datetime | None = None,
) -> dict:
    validate_cursor(cursor)
    validate_limit(limit)
    cutoff = utc(now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    if cursor:
        previous = session.scalar(select(UserChange).where(UserChange.user_id == user_id, UserChange.cursor == cursor))
        if previous is None or utc(previous.committed_at) < cutoff:
            raise SyncError(
                "RESYNC_REQUIRED", "Sync history expired or cursor is unavailable. Download a fresh snapshot."
            )
    else:
        oldest = session.scalar(select(func.min(UserChange.committed_at)).where(UserChange.user_id == user_id))
        if oldest is not None and utc(oldest) < cutoff:
            raise SyncError("RESYNC_REQUIRED", "Download a fresh snapshot before syncing this account.")
    rows = list(
        session.scalars(
            select(UserChange)
            .where(UserChange.user_id == user_id, UserChange.cursor > cursor)
            .order_by(UserChange.cursor)
            .limit(limit + 1)
        )
    )
    more = len(rows) > limit
    page = rows[:limit]
    return {
        "items": [
            {
                "cursor": row.cursor,
                "entity_type": row.entity_type,
                "entity_id": str(row.entity_id),
                "revision": row.revision,
                "tombstone": row.tombstone,
                "committed_at": utc(row.committed_at).isoformat(),
            }
            for row in page
        ],
        "next_cursor": page[-1].cursor if page else cursor,
        "has_more": more,
    }
