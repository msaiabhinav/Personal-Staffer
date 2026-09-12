"""FCM is a retryable hint; the inbox is the source of truth."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from sqlalchemy import select

from app.applications.service import lock_user
from app.auth.crypto import SecretBox
from app.config import get_settings
from app.db.models import Device, Notification, NotificationDelivery


def retry_after_seconds(value: str | None, *, now=None) -> int:
    if not value:
        return 60
    try:
        return max(60, int(value))
    except ValueError:
        try:
            return max(60, int((parsedate_to_datetime(value) - (now or datetime.now(UTC))).total_seconds()))
        except (ValueError, TypeError):
            return 60


class FCMSender:
    def __init__(self, settings, transport=None, credentials=None):
        self.settings, self.transport = settings, transport
        self.credentials = credentials

    def send(self, device_token, notification):
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account

        settings = self.settings
        if settings.integration_state("fcm") != "CONFIGURED" or (
            self.credentials is None and not Path(settings.fcm_credentials_file).is_file()
        ):
            return {"state": "NOT_CONFIGURED"}
        credentials = self.credentials or service_account.Credentials.from_service_account_file(
            settings.fcm_credentials_file, scopes=["https://www.googleapis.com/auth/firebase.messaging"]
        )
        credentials.refresh(Request())
        with httpx.Client(timeout=30, transport=self.transport, follow_redirects=False) as client:
            response = client.post(
                f"https://fcm.googleapis.com/v1/projects/{settings.fcm_project_id}/messages:send",
                headers={"Authorization": f"Bearer {credentials.token}"},
                json={
                    "message": {
                        "token": device_token,
                        "notification": {"title": "Personal Staffer", "body": "You have an update."},
                        "data": {
                            "notification_id": str(notification.id),
                            "target_type": notification.target_type,
                            "target_id": str(notification.target_id),
                        },
                        "android": {"notification": {"tag": str(notification.id)}, "priority": "normal"},
                    }
                },
            )
            if response.status_code >= 400:
                try:
                    error = response.json().get("error", {})
                except ValueError:
                    error = {}
                codes = {detail.get("errorCode") for detail in error.get("details", []) if isinstance(detail, dict)}
                if "UNREGISTERED" in codes:
                    return {"state": "TOKEN_INVALID", "reason": "FCM_UNREGISTERED"}
                if response.status_code in {401, 403}:
                    return {"state": "BLOCKED", "reason": "FCM_PERMISSION_DENIED"}
                if response.status_code == 429:
                    return {
                        "state": "RATE_LIMITED",
                        "reason": "FCM_RATE_LIMIT",
                        "retry_after_seconds": retry_after_seconds(response.headers.get("Retry-After")),
                    }
                if response.status_code >= 500:
                    return {
                        "state": "UNAVAILABLE",
                        "reason": "FCM_UNAVAILABLE",
                        "retry_after_seconds": retry_after_seconds(response.headers.get("Retry-After")),
                    }
                # A 404 alone can mean a missing project, not an invalid token.
            response.raise_for_status()
            return {"state": "SENT", "reference": response.json().get("name")}


def deliver(session, notification_id, *, sender=None):
    settings = get_settings()
    notification = session.get(Notification, notification_id)
    if not notification:
        return {"state": "MISSING"}
    lock_user(session, notification.user_id)
    outcomes = []
    retry_delay = 60
    for device in session.scalars(
        select(Device).where(Device.user_id == notification.user_id, Device.revoked_at.is_(None))
    ):
        if device.platform.upper() != "ANDROID":
            continue  # Windows native toasts follow the authenticated inbox change feed.
        row = session.scalar(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.notification_id == notification.id,
                NotificationDelivery.device_id == device.id,
                NotificationDelivery.channel == "FCM",
            )
            .with_for_update()
        )
        if row is None:
            row = NotificationDelivery(notification_id=notification.id, device_id=device.id, channel="FCM", attempts=0)
            session.add(row)
        if row.state in {"SENT", "TOKEN_INVALID"}:
            continue
        if row.attempts >= 3:
            row.state = "FAILED"
            outcomes.append(row.state)
            continue
        if not device.push_token_encrypted or (sender is None and settings.integration_state("fcm") != "CONFIGURED"):
            row.state = "NOT_CONFIGURED"
            outcomes.append(row.state)
            continue
        row.attempts += 1
        row.last_attempt = datetime.now(UTC)
        try:
            result = (sender or FCMSender(settings)).send(
                SecretBox(settings.token_encryption_key).decrypt(device.push_token_encrypted), notification
            )
            row.state = result["state"]
            row.last_error = result.get("reason")
            row.provider_reference = result.get("reference")
            retry_delay = max(retry_delay, result.get("retry_after_seconds", 60))
            if row.state == "TOKEN_INVALID":
                device.push_token_encrypted = None
        except Exception as exc:  # noqa: BLE001 - Persist any provider failure for bounded retry.
            row.state, row.last_error = "RETRY" if row.attempts < 3 else "FAILED", type(exc).__name__
        outcomes.append(row.state)
    if any(state in {"RETRY", "RATE_LIMITED", "UNAVAILABLE"} for state in outcomes):
        summary = "RETRY"
    elif "FAILED" in outcomes:
        summary = "FAILED"
    elif "BLOCKED" in outcomes:
        summary = "BLOCKED"
    elif outcomes and all(state == "NOT_CONFIGURED" for state in outcomes):
        summary = "NOT_CONFIGURED"
    else:
        summary = "RECORDED"
    return {"state": summary, "deliveries": outcomes, "retry_after_seconds": retry_delay}
