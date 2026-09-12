import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest

from app.config.settings import Settings
from app.notifications.delivery import FCMSender, retry_after_seconds


def sender(transport):
    settings = Settings(fcm_credentials_file="injected-test", fcm_project_id="project-test")
    credentials = SimpleNamespace(token="test-access", refresh=lambda request: None)
    return FCMSender(settings, transport, credentials)


def notification():
    return SimpleNamespace(id=uuid4(), target_type="applications", target_id=uuid4(), title="Private job status")


def test_fcm_payload_has_only_minimal_ids_and_tag():
    row = notification()

    def handler(request):
        payload = json.loads(request.content)["message"]
        assert request.url.host == "fcm.googleapis.com"
        assert request.headers["Authorization"] == "Bearer test-access"
        assert payload["data"] == {
            "notification_id": str(row.id),
            "target_type": "applications",
            "target_id": str(row.target_id),
        }
        assert payload["android"]["notification"]["tag"] == str(row.id)
        assert "Private job status" not in request.content.decode()
        return httpx.Response(200, json={"name": "projects/project/messages/test"})

    assert sender(httpx.MockTransport(handler)).send("device-token", row)["state"] == "SENT"


def test_fcm_only_explicit_unregistered_invalidates_token():
    payload = {"error": {"details": [{"errorCode": "UNREGISTERED"}]}}
    assert (
        sender(httpx.MockTransport(lambda r: httpx.Response(404, json=payload))).send("token", notification())["state"]
        == "TOKEN_INVALID"
    )
    with pytest.raises(httpx.HTTPStatusError):
        sender(httpx.MockTransport(lambda r: httpx.Response(404, json={"error": {"message": "Unknown project"}}))).send(
            "token", notification()
        )


@pytest.mark.parametrize("code,state", [(403, "BLOCKED"), (429, "RATE_LIMITED"), (503, "UNAVAILABLE")])
def test_fcm_failure_states_and_retry_after(code, state):
    result = sender(httpx.MockTransport(lambda r: httpx.Response(code, json={}, headers={"Retry-After": "300"}))).send(
        "token", notification()
    )
    assert result["state"] == state
    if code in {429, 503}:
        assert result["retry_after_seconds"] == 300


def test_retry_after_http_date_and_invalid_header():
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)
    assert retry_after_seconds("Sat, 12 Sep 2026 12:05:00 GMT", now=now) == 300
    assert retry_after_seconds("nonsense", now=now) == 60
