from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    def __init__(self, code, user_message, status_code=409, retryable=False, details=None):
        self.code = code
        self.user_message = user_message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        super().__init__(user_message)


async def domain_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.code,
            "user_message": exc.user_message,
            "retryable": exc.retryable,
            "request_id": getattr(request.state, "request_id", str(uuid4())),
            "details": getattr(exc, "details", {}),
        },
    )
