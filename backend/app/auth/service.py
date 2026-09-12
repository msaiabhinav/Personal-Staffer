from __future__ import annotations

import hmac
import re
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, text, update

from app.api.errors import DomainError
from app.auth.crypto import SecretBox, challenge, digest, new_secret
from app.auth.provider import GoogleProvider
from app.db.models import AppSession, Device, LoginIntent, User, utcnow


def failure(status: int, code: str, message: str, retryable=False):
    return DomainError(code, message, status, retryable)


def require_configured(settings, mailbox=False):
    if settings.integration_state("gmail" if mailbox else "google") != "CONFIGURED":
        raise failure(
            503,
            "NOT_CONFIGURED",
            "Google mailbox access is not configured." if mailbox else "Google sign-in is not configured.",
        )


def begin_intent(session, settings, payload, *, user_id=None, mailbox=False, provider=None):
    require_configured(settings, mailbox)
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", payload.challenge):
        raise failure(422, "INVALID_CHALLENGE", "A SHA-256 device challenge is required.")
    now = utcnow()
    # Bound pending intents per device. Expired intents are harmless and may be
    # removed by maintenance after audit retention.
    pending = list(
        session.scalars(
            select(LoginIntent.id)
            .where(
                LoginIntent.device_id == payload.device_id,
                LoginIntent.expires_at > now,
                LoginIntent.redeemed_at.is_(None),
            )
            .limit(6)
        )
    )
    if len(pending) >= 5:
        raise failure(429, "LOGIN_RATE_LIMITED", "Too many pending sign-in attempts. Wait a few minutes.", True)
    verifier, state, nonce = new_secret(), new_secret(), new_secret()
    intent = LoginIntent(
        id=uuid4(),
        device_id=payload.device_id,
        purpose="GMAIL" if mailbox else "LOGIN",
        state_hash=digest(state),
        challenge=payload.challenge,
        nonce=nonce,
        platform=payload.platform.upper(),
        device_label=payload.device_label,
        user_id=user_id,
        selected_label=getattr(payload, "selected_label", None),
        expires_at=now + timedelta(minutes=10),
        code_verifier_encrypted=SecretBox(settings.token_encryption_key).encrypt(verifier),
    )
    session.add(intent)
    session.flush()
    redirect_uri = settings.gmail_redirect_uri if mailbox else settings.google_redirect_uri
    url = (provider or GoogleProvider(settings)).authorize(redirect_uri, state, nonce, verifier, mailbox)
    return {"flow_id": str(intent.id), "authorization_url": url, "expires_at": intent.expires_at.isoformat()}


def enroll_owner(session, settings, claims):
    subject, email = claims["sub"], claims["email"]
    # Serialize initial enrollment across callbacks even when no user exists yet.
    session.execute(text("SELECT pg_advisory_xact_lock(783210419)"))
    if settings.owner_google_subject and not hmac.compare_digest(subject, settings.owner_google_subject):
        raise failure(403, "OWNER_ONLY", "This Google account is not the configured owner.")
    users = list(session.scalars(select(User).with_for_update()))
    if users:
        owner = next((u for u in users if hmac.compare_digest(u.google_subject, subject)), None)
        if not owner:
            raise failure(403, "OWNER_ONLY", "This Google account is not the enrolled owner.")
        owner.verified_email = email
        return owner
    if not settings.owner_allowed_email or not hmac.compare_digest(
        email.casefold(), settings.owner_allowed_email.casefold()
    ):
        raise failure(403, "OWNER_ONLY", "This Google account is not allowed to enroll.")
    owner = User(
        id=uuid4(), google_subject=subject, verified_email=email, display_name=str(claims.get("name", ""))[:255]
    )
    session.add(owner)
    session.flush()
    return owner


def complete_intent(session, settings, state: str, callback_url: str, *, mailbox=False, provider=None):
    require_configured(settings, mailbox)
    intent = session.scalar(select(LoginIntent).where(LoginIntent.state_hash == digest(state)).with_for_update())
    if (
        not intent
        or intent.expires_at <= utcnow()
        or intent.completed_at
        or intent.redeemed_at
        or intent.purpose != ("GMAIL" if mailbox else "LOGIN")
    ):
        raise failure(401, "INVALID_LOGIN_INTENT", "This sign-in request is invalid or expired.")
    try:
        claims, token = (provider or GoogleProvider(settings)).exchange(
            settings.gmail_redirect_uri if mailbox else settings.google_redirect_uri,
            callback_url,
            state,
            intent.nonce,
            SecretBox(settings.token_encryption_key).decrypt(intent.code_verifier_encrypted),
        )
    except Exception as exc:
        # No raw provider response or callback URL enters application errors.
        raise failure(
            401, "GOOGLE_SIGN_IN_FAILED", "Google sign-in could not be verified. Start a new sign-in."
        ) from exc
    owner = enroll_owner(session, settings, claims)
    if mailbox and intent.user_id != owner.id:
        raise failure(403, "MAILBOX_ACCOUNT_MISMATCH", "Connect the same Google account used to sign in.")
    intent.user_id = owner.id
    intent.completed_at = utcnow()
    intent.code_verifier_encrypted = None
    return intent, claims, token


def issue_session(session, settings, user_id, device_id):
    now, access, refresh = utcnow(), new_secret(), new_secret()
    row = AppSession(
        user_id=user_id,
        device_id=device_id,
        refresh_token_hash=digest(refresh),
        access_token_hash=digest(access),
        access_expires_at=now + timedelta(minutes=settings.access_token_minutes),
        expires_at=now + timedelta(days=settings.refresh_token_days),
    )
    session.add(row)
    session.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "user_id": str(user_id),
        "device_id": str(device_id),
        "expires_in": settings.access_token_minutes * 60,
    }


def redeem_intent(session, settings, flow_id: UUID, device_id: UUID, verifier: str):
    intent = session.scalar(select(LoginIntent).where(LoginIntent.id == flow_id).with_for_update())
    if not intent or intent.expires_at <= utcnow() or intent.redeemed_at or intent.purpose != "LOGIN":
        raise failure(401, "INVALID_LOGIN_INTENT", "This sign-in request is invalid or expired.")
    if (
        intent.device_id != device_id
        or not re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier)
        or not hmac.compare_digest(intent.challenge, challenge(verifier))
    ):
        raise failure(403, "DEVICE_VERIFIER_MISMATCH", "Sign-in must be completed on the device that started it.")
    if not intent.completed_at or not intent.user_id:
        raise failure(409, "AUTH_PENDING", "Complete Google sign-in in your browser.", True)
    device = session.scalar(select(Device).where(Device.id == device_id).with_for_update())
    if device and device.user_id != intent.user_id:
        raise failure(403, "DEVICE_OWNER_MISMATCH", "This device identifier belongs to another account.")
    if device:
        device.revoked_at = None
        device.last_seen = utcnow()
    else:
        session.add(
            Device(id=device_id, user_id=intent.user_id, platform=intent.platform, device_label=intent.device_label)
        )
        session.flush()
    intent.redeemed_at = utcnow()
    return issue_session(session, settings, intent.user_id, device_id)


def rotate_session(session, settings, refresh_token: str, device_id: UUID):
    row = session.scalar(
        select(AppSession).where(AppSession.refresh_token_hash == digest(refresh_token)).with_for_update()
    )
    if not row or row.device_id != device_id:
        raise failure(401, "INVALID_REFRESH_SESSION", "Sign in again to continue.")
    if row.revoked_at:
        session.execute(update(AppSession).where(AppSession.device_id == row.device_id).values(revoked_at=utcnow()))
        # Persist replay revocation despite the subsequent 401 exception.
        session.commit()
        raise failure(401, "REFRESH_TOKEN_REUSED", "A previously used session token was replayed. Sign in again.")
    device = session.get(Device, row.device_id)
    if row.expires_at <= utcnow() or not device or device.revoked_at:
        raise failure(401, "SESSION_EXPIRED", "Sign in again to continue.")
    row.revoked_at = utcnow()
    row.last_used_at = utcnow()
    return issue_session(session, settings, row.user_id, device_id)
