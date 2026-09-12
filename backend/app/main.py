from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.errors import DomainError, domain_error_handler
from app.api.router import router as api_router
from app.auth.router import router as auth_router
from app.config import get_settings
from app.demo import router as demo_router
from app.email.router import router as email_router
from app.notifications.contracts import NotificationError
from app.people.router import router as people_router
from app.sync.contracts import SyncError

VERSION = "0.1.0"
get_settings()  # Fail startup on unsafe production combinations.
app = FastAPI(
    title="Personal Staffer",
    version=VERSION,
    docs_url="/api/v1/docs",
    redoc_url=None,
    swagger_ui_oauth2_redirect_url="/api/v1/docs/oauth2-redirect",
    openapi_url="/api/v1/openapi.json",
)


class AuthRequestLimiter:
    """Bounded guard for the baseline single API process, keyed by actual peer.

    Forwarding headers cannot select a bucket. A global ceiling also prevents new
    UUIDs or rotating peers creating unbounded login intents.
    """

    def __init__(self, capacity=60, *, clock=time.monotonic):
        self.capacity, self.clock = capacity, clock
        self.peers = OrderedDict()
        self.global_requests = deque()

    def allow(self, peer):
        now = self.clock()
        while self.global_requests and self.global_requests[0] <= now - 60:
            self.global_requests.popleft()
        if len(self.global_requests) >= self.capacity * 4:
            return False
        window = self.peers.setdefault(peer, deque())
        self.peers.move_to_end(peer)
        if len(self.peers) > 2048:
            self.peers.popitem(last=False)
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= self.capacity:
            return False
        window.append(now)
        self.global_requests.append(now)
        return True


class RequestSafetyMiddleware:
    AUTH_PATHS = frozenset(
        {
            "/api/v1/auth/login/start",
            "/api/v1/auth/login/exchange",
            "/api/v1/auth/refresh",
            "/api/v1/auth/demo",
            "/api/v1/auth/google/callback",
            "/api/v1/gmail/callback",
        }
    )

    def __init__(self, app, *, max_bytes=4 * 1024 * 1024, auth_capacity=60):
        self.app, self.max_bytes = app, max_bytes
        self.limiter = AuthRequestLimiter(auth_capacity)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope.get("headers", [])}
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                length = int(content_length)
                if length < 0:
                    raise ValueError("negative length")
            except ValueError:
                return await self.reject(
                    scope, receive, send, 400, "INVALID_REQUEST_LENGTH", "Request length is invalid."
                )
            if length > self.max_bytes:
                return await self.reject(
                    scope, receive, send, 413, "REQUEST_TOO_LARGE", "Request exceeds the supported size."
                )
        if scope.get("path") in self.AUTH_PATHS:
            peer = (scope.get("client") or ("unknown",))[0]
            if not self.limiter.allow(peer):
                return await self.reject(
                    scope, receive, send, 429, "AUTH_RATE_LIMITED", "Too many sign-in requests. Try again shortly."
                )
        total = 0

        async def bounded_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail={"code": "REQUEST_TOO_LARGE", "user_message": "Request exceeds the supported size."},
                    )
            return message

        await self.app(scope, bounded_receive, send)

    @staticmethod
    async def reject(scope, receive, send, status, code, message):
        response = JSONResponse(
            status_code=status,
            content={
                "code": code,
                "user_message": message,
                "retryable": status == 429,
                "request_id": str(uuid4()),
                "details": {},
            },
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                **({"Retry-After": "60"} if status == 429 else {}),
            },
        )
        await response(scope, receive, send)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001 - last API boundary must redact unexpected exception text.
        logging.getLogger("personal_staffer").error(
            "request_failed request_id=%s error_type=%s", request.state.request_id, type(exc).__name__
        )
        response = JSONResponse(
            status_code=503 if isinstance(exc, SQLAlchemyError) else 500,
            content={
                "code": "DEPENDENCY_UNAVAILABLE" if isinstance(exc, SQLAlchemyError) else "INTERNAL_ERROR",
                "user_message": "The service could not complete this request. Try again.",
                "retryable": True,
                "request_id": request.state.request_id,
                "details": {},
            },
        )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


app.add_exception_handler(DomainError, domain_error_handler)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic's raw errors include input values. Never echo OAuth/session/email input.
    return JSONResponse(
        status_code=422,
        content={
            "code": "VALIDATION_ERROR",
            "user_message": "Check the request fields.",
            "retryable": False,
            "request_id": request.state.request_id,
            "details": {"fields": [".".join(str(x) for x in e["loc"]) for e in exc.errors()]},
        },
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": detail.get("code", "REQUEST_FAILED"),
            "user_message": detail.get("user_message", "The request could not be completed."),
            "retryable": exc.status_code >= 500,
            "request_id": request.state.request_id,
            "details": {},
        },
    )


@app.get("/api/v1/health/live")
def live():
    return {"status": "alive"}


@app.get("/api/v1/health/ready")
def ready():
    import redis

    from app.db.readiness import schema_is_current
    from app.db.session import get_engine

    try:
        settings = get_settings()
        with get_engine().connect() as connection:
            if not schema_is_current(connection):
                return JSONResponse(status_code=503, content={"status": "not_ready"})
        redis.Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
    except (SQLAlchemyError, redis.RedisError, ValueError):
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


@app.get("/api/v1/version")
def version():
    return {
        "backend_version": VERSION,
        "api_version": "v1",
        "minimum_client_version": "0.1.0",
        "latest_client_version": "0.1.0",
        "release_artifacts": [],
        "update_mode": "MANUAL_VERIFIED_INSTALL",
        "demo_mode": get_settings().app_env == "local" and get_settings().demo_mode,
    }


app.add_exception_handler(NotificationError, domain_error_handler)
app.add_exception_handler(SyncError, domain_error_handler)
app.include_router(api_router)
app.include_router(demo_router)
for router in (auth_router, email_router, people_router):
    app.include_router(router, prefix="/api/v1")


app.add_middleware(RequestSafetyMiddleware, auth_capacity=get_settings().api_auth_requests_per_minute)
