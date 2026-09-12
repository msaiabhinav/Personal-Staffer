from datetime import UTC, datetime


class SyncError(Exception):
    def __init__(self, code: str, user_message: str, status_code: int = 409):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.status_code = status_code
        self.retryable = False


def utc(value: datetime) -> datetime:
    # Production columns use timestamptz; naive input from external callers is invalid.
    if value.tzinfo is None or value.utcoffset() is None:
        raise SyncError("INVALID_TIMESTAMP", "An explicit timezone is required.", 422)
    return value.astimezone(UTC)


def validate_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 100:
        raise SyncError("INVALID_PAGE_SIZE", "Page size must be from 1 to 100.", 422)
    return value


def validate_cursor(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SyncError("INVALID_CURSOR", "Sync cursor must be a nonnegative integer.", 422)
    return value
