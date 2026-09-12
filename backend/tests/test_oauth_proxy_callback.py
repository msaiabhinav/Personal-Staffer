from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.requests import Request


def request_for(path):
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"code=one-time-code&state=expected",
            "headers": [(b"host", b"attacker.invalid"), (b"x-forwarded-host", b"also-attacker.invalid")],
            "server": ("api", 8000),
            "client": ("127.0.0.1", 1),
        }
    )


def test_google_callback_uses_configured_https_authority(monkeypatch):
    import app.auth.router as module

    captured = []
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(google_redirect_uri="https://staffer.example/api/v1/auth/google/callback"),
    )
    monkeypatch.setattr(
        module,
        "complete_intent",
        lambda session, settings, state, url: captured.append(url) or (SimpleNamespace(id=uuid4()), {}, {}),
    )
    module.google_callback(request_for("/api/v1/auth/google/callback"), None, state="expected")
    assert captured == ["https://staffer.example/api/v1/auth/google/callback?code=one-time-code&state=expected"]


def test_mailbox_callback_uses_configured_https_authority(monkeypatch):
    import app.email.router as module

    captured = []
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(gmail_redirect_uri="https://staffer.example/api/v1/gmail/callback"),
    )

    class BoundaryReached(Exception):
        pass

    def exchange(session, settings, state, url, mailbox):
        captured.append(url)
        raise BoundaryReached()

    monkeypatch.setattr(module, "complete_intent", exchange)
    with pytest.raises(BoundaryReached):
        module.callback(request_for("/api/v1/gmail/callback"), None, state="expected")
    assert captured == ["https://staffer.example/api/v1/gmail/callback?code=one-time-code&state=expected"]
