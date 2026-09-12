import socket

import pytest

from app.connectors.safe_http import (
    HTTPResult,
    SafeHTTPClient,
    SourceHTTPError,
    is_public_address,
    public_addresses,
    validate_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "https://10.1.1.1/",
        "http://172.16.3.2/",
        "http://192.168.1.1/",
        "http://[::1]/",
        "https://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "https://localhost/",
        "https://test.internal/",
        "https://user:pass@example.com/",
        "https://example.com:8080/",
        "https://example.com/\n",
        "http://224.0.0.1/",
        "https://[ff02::1]/",
    ],
)
def test_unsafe_destination_rejected(url):
    with pytest.raises(SourceHTTPError):
        validate_url(url)


def test_public_http_and_preserved_query_are_allowed():
    assert validate_url("https://jobs.example.com/apply?gh_jid=123") == ("https", "jobs.example.com", 443)
    assert is_public_address("8.8.8.8")


def test_mixed_dns_public_private_fails_whole_request(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 443)),
        ],
    )
    with pytest.raises(SourceHTTPError, match="non-public"):
        public_addresses("evil.example", 443)


def test_redirect_to_metadata_is_rejected_before_second_request(monkeypatch):
    client = SafeHTTPClient()
    calls = []

    def fake(method, url, headers, body, deadline):
        calls.append(url)
        return HTTPResult(302, b"", url, {"location": "https://169.254.169.254/latest/meta-data/"})

    monkeypatch.setattr(client, "_request_once", fake)
    with pytest.raises(SourceHTTPError):
        client.get("https://safe.example/job")
    assert len(calls) == 1


def test_redirect_dns_rebinding_is_revalidated(monkeypatch):
    client = SafeHTTPClient(resolver=lambda host, port: [(socket.AF_INET, "127.0.0.1")])
    # Even injected resolvers must pass the public-address gate before opening a socket.
    with pytest.raises(SourceHTTPError):
        client.get("https://rebind.example/job")


def test_redirect_loop_bounded_and_cross_origin_secrets_removed(monkeypatch):
    client = SafeHTTPClient(max_redirects=2)
    seen = []

    def fake(method, url, headers, body, deadline):
        seen.append(dict(headers))
        return HTTPResult(302, b"", url, {"location": "https://other.example/job"})

    monkeypatch.setattr(client, "_request_once", fake)
    with pytest.raises(SourceHTTPError, match="redirect limit"):
        client.get("https://first.example/job", headers={"Authorization-Key": "secret"})
    assert len(seen) == 3 and "Authorization-Key" not in seen[1]


def test_retry_after_long_delay_does_not_ignore_limit_or_sleep_past_budget(monkeypatch):
    client = SafeHTTPClient(timeout=0.1)
    calls = []
    monkeypatch.setattr(
        client, "_request_once", lambda *a: calls.append(a) or HTTPResult(429, b"", a[1], {"retry-after": "3600"})
    )
    result = client.get("https://example.com/jobs")
    assert result.status_code == 429 and len(calls) == 1


def test_response_size_cap_in_reader_and_pinned_numeric_connection(monkeypatch):
    import http.client

    connected = []

    class FakeSocket:
        def settimeout(self, value):
            pass

        def connect(self, address):
            connected.append(address)

        def getpeername(self):
            return ("8.8.8.8", 443)

        def close(self):
            pass

    class FakeResponse:
        status = 200

        def getheaders(self):
            return [("Content-Length", "1000")]

        def read1(self, n):
            raise AssertionError("Content-Length cap should stop before body")

    class FakeConnection:
        def __init__(self, *a, **kw):
            self.sock = None

        def request(self, *a, **kw):
            self.sock = self._create_connection()

        def getresponse(self):
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(socket, "socket", lambda *a: FakeSocket())
    monkeypatch.setattr(http.client, "HTTPSConnection", FakeConnection)
    client = SafeHTTPClient(max_bytes=100, resolver=lambda host, port: [(socket.AF_INET, "8.8.8.8")])
    with pytest.raises(SourceHTTPError, match="byte limit"):
        client.get("https://example.com/job?id=123")
    assert connected == [("8.8.8.8", 443)]
