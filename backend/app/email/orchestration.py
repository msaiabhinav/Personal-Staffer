"""Fetch outside database locks, then atomically apply one unchanged cursor page."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.applications.service import lock_user
from app.auth.crypto import SecretBox
from app.auth.provider import GMAIL_SCOPE, GoogleProvider
from app.db.models import GmailConnection, GmailSyncState, utcnow
from app.email.gmail import GmailAPI, GmailUnavailable, HistoryExpired
from app.email.service import synchronize


class RecordedPage:
    """A validated finite replay of a fetched provider page, with no network methods."""

    def __init__(self):
        self.values = {}

    @staticmethod
    def key(method, args):
        return method, tuple(x.isoformat() if isinstance(x, datetime) else x for x in args)

    def record(self, api, method, *args):
        key = self.key(method, args)
        try:
            value = getattr(api, method)(*args)
        except HistoryExpired as exc:
            self.values[key] = exc
            raise
        self.values[key] = value
        return value

    def _read(self, method, *args):
        key = self.key(method, args)
        if key not in self.values:
            raise RuntimeError("The synchronization plan changed; discard this page and retry")
        value = self.values[key]
        if isinstance(value, Exception):
            raise value
        return value

    def profile(self):
        return self._read("profile")

    def history(self, *args):
        return self._read("history", *args)

    def backfill(self, *args):
        return self._read("backfill", *args)

    def message(self, identifier):
        return self._read("message", identifier)


def _signature(connection, state):
    return (
        connection.id,
        connection.refresh_token_encrypted,
        connection.revoked_at,
        tuple(connection.granted_scopes),
        connection.selected_label,
        state.history_cursor if state else None,
        json.dumps(state.reconciliation_progress if state else {}, sort_keys=True),
    )


def synchronize_batched(factory, user_id, settings, *, api=None, provider=None):
    with factory() as session:
        connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id))
        if not connection or not connection.refresh_token_encrypted or connection.revoked_at:
            return {"state": "NOT_CONFIGURED" if not connection else "RECONNECT_REQUIRED", "processed": 0}
        if GMAIL_SCOPE not in connection.granted_scopes:
            return {"state": "RECONNECT_REQUIRED", "processed": 0}
        state = session.scalar(select(GmailSyncState).where(GmailSyncState.connection_id == connection.id))
        signature = _signature(connection, state)
        cursor = state.history_cursor if state else None
        progress = dict(state.reconciliation_progress or {}) if state else {}
        encrypted_token, label = connection.refresh_token_encrypted, connection.selected_label
    rotated_token = None
    if api is None:
        box = SecretBox(settings.token_encryption_key)
        try:
            token = (provider or GoogleProvider(settings)).refresh(encrypted_token, box)
        except Exception as exc:
            raise GmailUnavailable("RECONNECT_REQUIRED", "Gmail access could not be refreshed") from exc
        if token.get("refresh_token"):
            rotated_token = box.encrypt(token["refresh_token"])
        api = GmailAPI(token["access_token"])
    page = RecordedPage()
    # Freeze the page's first-backfill time; the replay receives this exact time.
    started_at = utcnow()
    if not cursor and progress.get("mode") != "BACKFILL":
        profile = page.record(api, "profile")
        progress = {
            "mode": "BACKFILL",
            "baseline": str(profile["historyId"]),
            "after": (started_at - timedelta(days=settings.gmail_backfill_days)).isoformat(),
            "page_token": None,
            "processed": 0,
        }
    if progress.get("mode") == "BACKFILL":
        batch = page.record(
            api, "backfill", datetime.fromisoformat(progress["after"]), progress.get("page_token"), label
        )
    else:
        try:
            batch = page.record(api, "history", cursor, progress.get("page_token"), label)
        except HistoryExpired:
            profile = page.record(api, "profile")
            progress = {
                "mode": "BACKFILL",
                "baseline": str(profile["historyId"]),
                "after": (started_at - timedelta(days=settings.gmail_backfill_days)).isoformat(),
                "page_token": None,
                "processed": 0,
            }
            batch = page.record(api, "backfill", datetime.fromisoformat(progress["after"]), None, label)
    for identifier in batch.message_ids:
        page.record(api, "message", identifier)
    # No external calls below this point: user actions cannot wait behind provider I/O.
    with factory() as session, session.begin():
        lock_user(session, user_id)
        connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id).with_for_update())
        state = (
            session.scalar(
                select(GmailSyncState).where(GmailSyncState.connection_id == connection.id).with_for_update()
            )
            if connection
            else None
        )
        if not connection or _signature(connection, state) != signature:
            return {"state": "PARTIAL", "processed": 0, "has_more": True, "reason": "SYNC_STATE_CHANGED_RETRY"}
        if rotated_token:
            connection.refresh_token_encrypted = rotated_token
        return synchronize(session, user_id, settings, api=page, frozen_now=started_at)
