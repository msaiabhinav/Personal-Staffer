from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ManualApplicationInput
from app.applications.service import (
    add_status_event,
    change,
    create_manual,
    execute_operation,
    lock_user,
    require_revision,
)
from app.auth.crypto import SecretBox, digest
from app.auth.dependencies import current_user
from app.auth.provider import GMAIL_SCOPE, GoogleProvider
from app.auth.router import LoginStart
from app.auth.service import begin_intent, complete_intent, failure, require_configured
from app.config import get_settings
from app.db.models import (
    Application,
    Device,
    EmailApplicationLink,
    EmailMessage,
    GmailConnection,
    GmailSyncState,
    OutboxEvent,
    ReviewItem,
    User,
    WorkItem,
    utcnow,
)
from app.db.session import get_session

router = APIRouter(tags=["gmail", "email review"])
DB = Annotated[Session, Depends(get_session)]
Owner = Annotated[User, Depends(current_user)]
Operation = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


class GmailConnect(LoginStart):
    selected_label: str | None = Field(default=None, max_length=255)


@router.post("/gmail/connect")
def connect(payload: GmailConnect, user: Owner, session: DB):
    device = session.get(Device, payload.device_id)
    if not device or device.user_id != user.id or device.revoked_at:
        raise failure(404, "DEVICE_NOT_FOUND", "An active signed-in device is required.")
    return begin_intent(session, get_settings(), payload, user_id=user.id, mailbox=True)


@router.get("/gmail/callback", include_in_schema=False)
def callback(request: Request, session: DB, state: str = "", error: str | None = None):
    if error:
        raise failure(401, "GMAIL_CONSENT_DENIED", "Gmail access was not granted.")
    settings = get_settings()
    callback_url = settings.gmail_redirect_uri + ("?" + request.url.query if request.url.query else "")
    intent, claims, token = complete_intent(session, settings, state, callback_url, mailbox=True)
    lock_user(session, intent.user_id)
    scopes = str(token.get("scope", "")).split()
    if GMAIL_SCOPE not in scopes:
        raise failure(403, "GMAIL_SCOPE_MISSING", "Grant read-only Gmail access to enable application updates.")
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == intent.user_id))
    if not token.get("refresh_token") and (not connection or not connection.refresh_token_encrypted):
        raise failure(
            409, "GMAIL_OFFLINE_GRANT_MISSING", "Google did not issue background access. Reconnect and approve consent."
        )
    if not connection:
        connection = GmailConnection(id=uuid4(), user_id=intent.user_id, google_identity=claims["email"])
        session.add(connection)
    if token.get("refresh_token"):
        connection.refresh_token_encrypted = SecretBox(settings.token_encryption_key).encrypt(token["refresh_token"])
    connection.google_identity = claims["email"]
    connection.granted_scopes = scopes
    if connection.selected_label != intent.selected_label:
        sync = session.scalar(select(GmailSyncState).where(GmailSyncState.connection_id == connection.id))
        if sync:
            sync.history_cursor = None
            sync.reconciliation_progress = {}
    connection.selected_label = intent.selected_label
    connection.revoked_at = None
    connection.sync_health = "CONNECTED"
    intent.redeemed_at = utcnow()
    session.flush()
    return RedirectResponse(
        f"personalstaffer://settings/gmail?flow_id={intent.id}",
        status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/gmail/status")
def status(user: Owner, session: DB):
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))
    configured = get_settings().integration_state("gmail")
    sync = (
        session.scalar(select(GmailSyncState).where(GmailSyncState.connection_id == connection.id))
        if connection
        else None
    )
    return {
        "state": connection.sync_health
        if connection
        else configured
        if configured == "NOT_CONFIGURED"
        else "NOT_CONNECTED",
        "mailbox": connection.google_identity if connection else None,
        "scopes": connection.granted_scopes if connection else [],
        "selected_label": connection.selected_label if connection else None,
        "last_success": sync.last_success if sync else None,
        "progress": sync.reconciliation_progress if sync else {},
        "read_only": True,
    }


@router.delete("/gmail/connection")
def disconnect(user: Owner, session: DB):
    lock_user(session, user.id)
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id).with_for_update())
    provider_revoked = False
    if connection:
        if connection.refresh_token_encrypted:
            try:
                GoogleProvider(get_settings()).revoke(
                    SecretBox(get_settings().token_encryption_key).decrypt(connection.refresh_token_encrypted)
                )
                provider_revoked = True
            except (httpx.HTTPError, ValueError):
                provider_revoked = False
        connection.refresh_token_encrypted = None
        connection.revoked_at = utcnow()
        connection.sync_health = "DISCONNECTED"
    return {
        "state": "DISCONNECTED",
        "stored_token_removed": True,
        "provider_revoked": provider_revoked,
        "provider_access_review_needed": bool(connection and not provider_revoked),
    }


def queue_work(session, user_id, task_type, payload, operation_id):
    key = f"{task_type}:{user_id}:{operation_id}"
    work = session.scalar(select(WorkItem).where(WorkItem.task_key == key))
    if not work:
        work = WorkItem(id=uuid4(), task_key=key, task_type=task_type, payload=payload)
        session.add(work)
        session.add(
            OutboxEvent(event_key=f"work:{work.id}", event_type="work.ready", payload={"work_id": str(work.id)})
        )
        session.flush()
    return {"work_id": str(work.id), "state": work.state}


@router.post("/gmail/sync", status_code=202)
def request_sync(user: Owner, session: DB, operation_id: Operation):
    require_configured(get_settings(), mailbox=True)
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user.id))
    if not connection or not connection.refresh_token_encrypted or connection.revoked_at:
        raise failure(409, "GMAIL_NOT_CONNECTED", "Connect Gmail before synchronizing.")
    return execute_operation(
        session,
        user.id,
        operation_id,
        "gmail.sync",
        connection.id,
        {},
        lambda: queue_work(session, user.id, "gmail.sync", {"user_id": str(user.id)}, operation_id),
    )


@router.get("/reviews")
def reviews(
    user: Owner,
    session: DB,
    state: Literal["OPEN", "RESOLVED", "DISMISSED"] = "OPEN",
    cursor: UUID | None = None,
    limit: int = Query(default=25, ge=1, le=100),
):
    query = select(ReviewItem).where(
        ReviewItem.user_id == user.id, ReviewItem.admin_only.is_(False), ReviewItem.state == state
    )
    if cursor:
        query = query.where(ReviewItem.id > cursor)
    rows = list(session.scalars(query.order_by(ReviewItem.id).limit(limit + 1)))
    return {
        "items": [
            {
                "id": str(row.id),
                "type": row.review_type,
                "target_id": str(row.target_id),
                "reason": row.reason,
                "evidence": row.evidence,
                "state": row.state,
                "revision": row.revision,
                "created_at": row.created_at,
            }
            for row in rows[:limit]
        ],
        "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
    }


@router.get("/reviews/{review_id}")
def review_detail(review_id: UUID, user: Owner, session: DB):
    row = session.scalar(
        select(ReviewItem).where(
            ReviewItem.id == review_id, ReviewItem.user_id == user.id, ReviewItem.admin_only.is_(False)
        )
    )
    if not row:
        raise failure(404, "REVIEW_NOT_FOUND", "Review item not found.")
    return {
        "id": str(row.id),
        "type": row.review_type,
        "target_id": str(row.target_id),
        "reason": row.reason,
        "evidence": row.evidence,
        "state": row.state,
        "revision": row.revision,
        "resolution": row.resolution,
    }


class ResolveReview(BaseModel):
    action: Literal["DISMISS", "LINK", "CREATE_APPLICATION"]
    expected_revision: int = Field(ge=1)
    application_id: UUID | None = None
    application_revision: int | None = Field(default=None, ge=1)
    status: Literal["APPLIED", "ASSESSMENT", "INTERVIEWING", "OFFER", "REJECTED"] | None = None
    reason: str = Field(min_length=1, max_length=2000)
    application: ManualApplicationInput | None = None


def resolve(session, user, review_id, payload, operation_id):
    lock_user(session, user.id)
    row = session.scalar(
        select(ReviewItem)
        .where(ReviewItem.id == review_id, ReviewItem.user_id == user.id, ReviewItem.admin_only.is_(False))
        .with_for_update()
    )
    if not row or row.review_type != "EMAIL_APPLICATION":
        raise failure(404, "REVIEW_NOT_FOUND", "Email review item not found.")
    require_revision(row.revision, payload.expected_revision)
    if row.state != "OPEN":
        raise failure(409, "REVIEW_ALREADY_RESOLVED", "This item was already resolved.")
    email = session.scalar(
        select(EmailMessage)
        .join(GmailConnection, GmailConnection.id == EmailMessage.connection_id)
        .where(EmailMessage.id == row.target_id, GmailConnection.user_id == user.id)
    )
    if not email:
        raise failure(404, "EMAIL_NOT_FOUND", "The supporting email was not found.")
    app = None
    result = {}
    if payload.action == "CREATE_APPLICATION":
        if not payload.application:
            raise failure(422, "APPLICATION_DETAILS_REQUIRED", "Supply company, title and the actual application date.")
        result = create_manual(session, user.id, payload.application, "review-create:" + digest(operation_id))
        app = session.get(Application, UUID(result["id"]))
    elif payload.action == "LINK":
        app = session.scalar(
            select(Application).where(
                Application.id == payload.application_id,
                Application.user_id == user.id,
                Application.voided_at.is_(None),
            )
        )
        if not app:
            raise failure(404, "APPLICATION_NOT_FOUND", "Choose an active application.")
        require_revision(app.revision, payload.application_revision)
    if app:
        link = session.scalar(
            select(EmailApplicationLink).where(
                EmailApplicationLink.email_id == email.id, EmailApplicationLink.application_id == app.id
            )
        )
        if not link:
            link = EmailApplicationLink(email_id=email.id, application_id=app.id)
            session.add(link)
        link.match_state = "USER_CONFIRMED"
        link.reviewed_at = utcnow()
        link.evidence = {"review_id": str(row.id), "reason": payload.reason}
        if payload.status:
            from types import SimpleNamespace

            result = add_status_event(
                session,
                user.id,
                app.id,
                SimpleNamespace(
                    expected_revision=app.revision,
                    status=payload.status,
                    reason=payload.reason,
                    effective_at=email.received_at,
                ),
                "review-status:" + digest(operation_id),
                actor="USER",
                source_reference=f"email-review:{row.id}",
                evidence={"email_id": str(email.id), "review_id": str(row.id)},
            )
            link.event_id = UUID(result["event_id"])
    row.state = "DISMISSED" if payload.action == "DISMISS" else "RESOLVED"
    row.resolved_at = utcnow()
    row.revision += 1
    row.resolution = {
        "action": payload.action,
        "reason": payload.reason,
        "application_id": str(app.id) if app else None,
        "status": payload.status,
        "actor": str(user.id),
    }
    change(session, user.id, "reviews", row.id, row.revision)
    return {"id": str(row.id), "state": row.state, "revision": row.revision, "resolution": row.resolution}


@router.post("/reviews/{review_id}/resolve")
def resolve_review(review_id: UUID, payload: ResolveReview, user: Owner, session: DB, operation_id: Operation):
    return execute_operation(
        session,
        user.id,
        operation_id,
        "email.review.resolve",
        review_id,
        payload.model_dump(mode="json"),
        lambda: resolve(session, user, review_id, payload, operation_id),
    )
