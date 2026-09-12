from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.crypto import digest
from app.auth.service import failure
from app.db.models import AppSession, Device, User, utcnow
from app.db.session import get_session

bearer = HTTPBearer(auto_error=False)


def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise failure(401, "SESSION_REQUIRED", "Sign in to continue.")
    row = session.scalar(
        select(AppSession).where(
            AppSession.access_token_hash == digest(credentials.credentials),
            AppSession.revoked_at.is_(None),
            AppSession.access_expires_at > utcnow(),
            AppSession.expires_at > utcnow(),
        )
    )
    if not row:
        raise failure(401, "SESSION_EXPIRED", "Your session expired. Reconnect or sign in again.")
    device = session.get(Device, row.device_id)
    user = session.get(User, row.user_id)
    if not device or device.revoked_at or not user or device.user_id != user.id:
        raise failure(401, "DEVICE_REVOKED", "This device session has been revoked.")
    request.state.app_session_id = row.id
    request.state.device_id = row.device_id
    return user
