from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.applications.service import change, lock_user
from app.auth.crypto import SecretBox
from app.auth.dependencies import current_user
from app.auth.service import begin_intent, complete_intent, failure, redeem_intent, rotate_session
from app.config import get_settings
from app.db.models import AppSession, Device, User, utcnow
from app.db.session import get_session

router = APIRouter(tags=["authentication"])
DB = Annotated[Session, Depends(get_session)]
Owner = Annotated[User, Depends(current_user)]


class LoginStart(BaseModel):
    device_id: UUID
    platform: Literal["WINDOWS", "ANDROID", "windows", "android"]
    device_label: str = Field(default="Personal device", max_length=255)
    challenge: str = Field(min_length=43, max_length=43)


class LoginExchange(BaseModel):
    flow_id: UUID
    device_id: UUID
    verifier: str = Field(min_length=43, max_length=128)


class Refresh(BaseModel):
    refresh_token: str = Field(min_length=32, max_length=256)
    device_id: UUID


class PushToken(BaseModel):
    push_token: str = Field(min_length=10, max_length=4096)
    platform: Literal["ANDROID", "android"]


@router.post("/auth/login/start")
def login_start(payload: LoginStart, session: DB):
    return begin_intent(session, get_settings(), payload)


@router.get("/auth/google/callback", include_in_schema=False)
def google_callback(request: Request, session: DB, state: str = "", error: str | None = None):
    if error:
        raise failure(401, "GOOGLE_CONSENT_DENIED", "Google sign-in was not completed.")
    settings = get_settings()
    # TLS terminates at Caddy; never derive callback authority from untrusted Host/Forwarded input.
    callback_url = settings.google_redirect_uri + ("?" + request.url.query if request.url.query else "")
    intent, _, _ = complete_intent(session, settings, state, callback_url)
    return RedirectResponse(
        f"personalstaffer://auth?flow_id={intent.id}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.post("/auth/login/exchange")
def login_exchange(payload: LoginExchange, session: DB):
    return redeem_intent(session, get_settings(), payload.flow_id, payload.device_id, payload.verifier)


@router.post("/auth/refresh")
def refresh(payload: Refresh, session: DB):
    return rotate_session(session, get_settings(), payload.refresh_token, payload.device_id)


@router.post("/auth/logout")
def logout(request: Request, user: Owner, session: DB):
    session.execute(
        update(AppSession)
        .where(AppSession.id == request.state.app_session_id, AppSession.user_id == user.id)
        .values(revoked_at=utcnow())
    )
    return {"revoked": True}


@router.get("/me")
def me(request: Request, user: Owner):
    return {
        "id": str(user.id),
        "user_id": str(user.id),
        "email": user.verified_email,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "device_id": str(request.state.device_id),
    }


@router.get("/devices")
def devices(user: Owner, session: DB):
    rows = session.scalars(select(Device).where(Device.user_id == user.id).order_by(Device.created_at, Device.id))
    return {
        "items": [
            {
                "id": str(row.id),
                "platform": row.platform,
                "device_label": row.device_label,
                "last_seen": row.last_seen,
                "revoked_at": row.revoked_at,
            }
            for row in rows
        ],
        "next_cursor": None,
    }


@router.delete("/devices/{device_id}")
def revoke_device(device_id: UUID, user: Owner, session: DB):
    device = session.scalar(select(Device).where(Device.id == device_id, Device.user_id == user.id).with_for_update())
    if not device:
        raise failure(404, "DEVICE_NOT_FOUND", "Device not found.")
    device.revoked_at = utcnow()
    device.push_token_encrypted = None
    session.execute(update(AppSession).where(AppSession.device_id == device.id).values(revoked_at=utcnow()))
    return {"id": str(device.id), "revoked": True}


@router.put("/devices/{device_id}/push-token")
def register_push_token(device_id: UUID, payload: PushToken, user: Owner, session: DB):
    lock_user(session, user.id)
    device = session.scalar(select(Device).where(Device.id == device_id, Device.user_id == user.id).with_for_update())
    if not device or device.revoked_at:
        raise failure(404, "DEVICE_NOT_FOUND", "An active owned device is required.")
    if device.platform.upper() != payload.platform.upper():
        raise failure(409, "DEVICE_PLATFORM_MISMATCH", "Push registration does not match this device's platform.")
    if not get_settings().token_encryption_key:
        raise failure(503, "NOT_CONFIGURED", "Secure push-token storage is not configured.")
    device.push_token_encrypted = SecretBox(get_settings().token_encryption_key).encrypt(payload.push_token)
    device.last_seen = utcnow()
    device.revision += 1
    change(session, user.id, "devices", device.id, device.revision)
    return {"device_id": str(device.id), "registered": True, "revision": device.revision}
