"""Read-only Gmail API paging; cursors are committed by the domain transaction."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import httpx


class GmailUnavailable(RuntimeError):
    def __init__(self, state: str, reason: str):
        super().__init__(reason)
        self.state, self.reason = state, reason


class HistoryExpired(GmailUnavailable):
    def __init__(self):
        super().__init__("RESYNC_REQUIRED", "Gmail history expired; bounded reconciliation is required")


@dataclass(frozen=True)
class MessageBatch:
    message_ids: tuple[str, ...]
    next_page_token: str | None
    history_cursor: str | None


def _error_reason(response, status) -> str:
    """Return Google's error `status`/`reason` codes only; never the message body or headers."""
    try:
        error = response.json().get("error", {})
        codes = {error.get("status")} | {d.get("reason") for d in error.get("errors", []) if isinstance(d, dict)}
        codes |= {
            d.get("reason")
            for d in error.get("details", [])
            if isinstance(d, dict) and d.get("@type", "").endswith("ErrorInfo")
        }
        codes.discard(None)
        return f"HTTP {status} " + ("/".join(sorted(str(c) for c in codes)) if codes else "no reason code")
    except ValueError:
        return f"HTTP {status} non-JSON error"


class GmailAPI:
    def __init__(self, access_token: str, transport=None):
        self.access_token, self.transport = access_token, transport

    def get(self, route, params=None):
        try:
            with httpx.Client(timeout=30, transport=self.transport, follow_redirects=False) as client:
                response = client.get(
                    "https://gmail.googleapis.com/gmail/v1/users/me/" + route,
                    headers={"Authorization": "Bearer " + self.access_token},
                    params=params,
                )
            if response.status_code in {401, 403}:
                # Google's structured reason (e.g. insufficientPermissions, accessNotConfigured,
                # dailyLimitExceeded) is operational diagnosis, not mailbox content or a credential.
                raise GmailUnavailable(
                    "RECONNECT_REQUIRED",
                    "Gmail authorization needs reconnection or permission review: "
                    + _error_reason(response, response.status_code),
                )
            if response.status_code == 404 and route == "history":
                raise HistoryExpired()
            if response.status_code == 429:
                raise GmailUnavailable("RATE_LIMITED", "Gmail rate limit reached; synchronization will retry")
            response.raise_for_status()
            if len(response.content) > 4_000_000:
                raise GmailUnavailable("FAILED", "Gmail response exceeds safe processing limit")
            return response.json()
        except httpx.HTTPError as exc:
            raise GmailUnavailable("UNAVAILABLE", "Gmail request failed; no cursor was advanced") from exc

    def profile(self):
        return self.get("profile")

    def history(self, cursor: str, page_token=None, label=None):
        params = {"startHistoryId": cursor, "historyTypes": ["messageAdded", "labelAdded"], "maxResults": 100}
        if page_token:
            params["pageToken"] = page_token
        if label:
            params["labelId"] = label
        payload = self.get("history", params)
        ids = set()
        for history in payload.get("history", []):
            for kind in ("messagesAdded", "labelsAdded"):
                for entry in history.get(kind, []):
                    if (
                        not label
                        or label in entry.get("message", {}).get("labelIds", [])
                        or label in entry.get("labelIds", [])
                    ):
                        ids.add(entry["message"]["id"])
        return MessageBatch(
            tuple(sorted(ids)),
            payload.get("nextPageToken"),
            str(payload["historyId"]) if payload.get("historyId") else None,
        )

    def backfill(self, after: datetime, page_token=None, label=None):
        # A bounded job-related search, never a full mailbox import. Labels narrow
        # processing but do not narrow the provider's gmail.readonly grant.
        query = f'after:{int(after.timestamp())} {{application interview assessment recruiter recruiting "offer of employment" "position closed"}}'
        params = {"q": query, "maxResults": 100, "includeSpamTrash": "false"}
        if page_token:
            params["pageToken"] = page_token
        if label:
            params["labelIds"] = label
        payload = self.get("messages", params)
        return MessageBatch(tuple(row["id"] for row in payload.get("messages", [])), payload.get("nextPageToken"), None)

    def message(self, identifier: str):
        if not identifier.isalnum():
            raise GmailUnavailable("FAILED", "Invalid Gmail message identifier")
        return self.get("messages/" + identifier, {"format": "full"})
