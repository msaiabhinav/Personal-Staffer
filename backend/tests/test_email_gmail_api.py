from datetime import UTC, datetime

import httpx
import pytest

from app.email.gmail import GmailAPI, GmailUnavailable, HistoryExpired


def test_gmail_api_uses_get_readonly_and_job_bounded_search():
    def handler(request):
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer test-access"
        assert request.url.host == "gmail.googleapis.com"
        query = request.url.params["q"]
        assert "after:" in query and "application" in query
        assert request.url.params["labelIds"] == "Label_1"
        return httpx.Response(200, json={"messages": [{"id": "abc123"}], "nextPageToken": "page2"})

    api = GmailAPI("test-access", httpx.MockTransport(handler))
    batch = api.backfill(datetime(2026, 8, 13, tzinfo=UTC), label="Label_1")
    assert batch.message_ids == ("abc123",) and batch.next_page_token == "page2"


def test_history_expired_reconnect_rate_limit_states():
    for status, error, state in [
        (404, HistoryExpired, "RESYNC_REQUIRED"),
        (401, GmailUnavailable, "RECONNECT_REQUIRED"),
        (403, GmailUnavailable, "RECONNECT_REQUIRED"),
        (429, GmailUnavailable, "RATE_LIMITED"),
    ]:
        api = GmailAPI("test", httpx.MockTransport(lambda req, code=status: httpx.Response(code)))
        with pytest.raises(error) as caught:
            api.history("123")
        assert caught.value.state == state


def test_history_deduplicates_added_and_label_added_messages():
    payload = {
        "historyId": "300",
        "history": [
            {
                "messagesAdded": [{"message": {"id": "a1"}}],
                "labelsAdded": [{"message": {"id": "a1"}}, {"message": {"id": "a2"}}],
            }
        ],
    }
    api = GmailAPI("test", httpx.MockTransport(lambda req: httpx.Response(200, json=payload)))
    batch = api.history("100")
    assert batch.message_ids == ("a1", "a2") and batch.history_cursor == "300"
