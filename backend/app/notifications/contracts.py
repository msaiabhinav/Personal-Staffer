"""Safe internal destinations; never execute source-controlled URI payloads."""

from enum import StrEnum
from uuid import UUID


class NotificationError(Exception):
    def __init__(self, code: str, user_message: str, status_code: int = 422):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code
        self.retryable = False


class TargetType(StrEnum):
    JOB = "JOB"
    APPLICATION = "APPLICATION"
    REVIEW = "REVIEW"
    REPORT = "REPORT"
    SEARCH_RUN = "SEARCH_RUN"


COLLECTIONS = {
    TargetType.JOB: "jobs",
    TargetType.APPLICATION: "applications",
    TargetType.REVIEW: "reviews",
    TargetType.REPORT: "reports",
    TargetType.SEARCH_RUN: "search-runs",
}


def target(value: str | TargetType, target_id: str | UUID) -> tuple[TargetType, UUID]:
    """Only whitelisted target types and one UUID are accepted."""
    reverse = {collection: kind for kind, collection in COLLECTIONS.items()}
    try:
        kind = reverse[value] if value in reverse else TargetType(value)
        identifier = target_id if isinstance(target_id, UUID) else UUID(target_id)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise NotificationError("INVALID_DESTINATION", "This notification destination is invalid.") from exc
    return kind, identifier


def destination(value: str | TargetType, target_id: str | UUID) -> dict[str, str]:
    kind, identifier = target(value, target_id)
    path = f"/{COLLECTIONS[kind]}/{identifier}"
    return {
        "target_type": COLLECTIONS[kind],
        "target_id": str(identifier),
        "route": path,
        "destination": f"personalstaffer:/{path}",
        "deep_link": f"personalstaffer:/{path}",
    }
