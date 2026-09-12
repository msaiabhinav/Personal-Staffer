"""Bounded public HTTP requests with pinned DNS and no ambient proxy credentials.

Sockets connect to an already validated numeric IP; TLS still validates the original
hostname. Every redirect resolves independently. This avoids the check-then-resolve
DNS rebinding flaw in URL-only SSRF filters. Managed environments without public DNS
will fail explicitly instead of switching to an unsafe transport.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import json
import math
import random
import socket
import ssl
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit


class SourceHTTPError(Exception):
    def __init__(
        self, code: str, message: str, *, status: int | None = None, retryable: bool = False, retry_after=None
    ):
        super().__init__(message)
        self.code, self.status, self.retryable = code, status, retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class HTTPResult:
    status_code: int
    body: bytes
    final_url: str
    headers: Mapping[str, str]

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self):
        try:
            return json.loads(self.body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise SourceHTTPError("INVALID_JSON", "Source response was not valid JSON") from exc


def is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(value.split("%", 1)[0])
    mapped = address.ipv4_mapped if address.version == 6 else None
    return (
        address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and (mapped is None or mapped.is_global and not mapped.is_multicast and not mapped.is_reserved)
    )


def validate_url(url: str) -> tuple[str, str, int]:
    try:
        p = urlsplit(url)
        port = p.port or (443 if p.scheme == "https" else 80)
    except ValueError as exc:
        raise SourceHTTPError("UNSAFE_URL", "Invalid source URL") from exc
    if p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password:
        raise SourceHTTPError("UNSAFE_URL", "Only public HTTP(S) URLs without credentials are allowed")
    if port not in {80, 443} or "\\" in url or any(ord(c) < 33 for c in url):
        raise SourceHTTPError("UNSAFE_URL", "Unsupported source port or invalid URL characters")
    host = p.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise SourceHTTPError("UNSAFE_ADDRESS", "Local source destinations are forbidden")
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        address = None
    if address is not None and (not is_public_address(host) or "%" in host):
        raise SourceHTTPError("UNSAFE_ADDRESS", "Source destination is not a public address")
    return p.scheme, host, port


def public_addresses(host: str, port: int) -> list[tuple[int, str]]:
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SourceHTTPError("DNS_UNAVAILABLE", "Public source DNS resolution failed", retryable=True) from exc
    addresses = list(dict.fromkeys((row[0], row[4][0]) for row in rows))
    if not addresses:
        raise SourceHTTPError("DNS_UNAVAILABLE", "No public source address resolved", retryable=True)
    for _, address in addresses:
        if not is_public_address(address):
            raise SourceHTTPError("UNSAFE_ADDRESS", "DNS resolved to a non-public source address")
    return addresses


_DNS_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="source-dns")
_DNS_SLOTS = threading.BoundedSemaphore(4)


class SafeHTTPClient:
    def __init__(
        self,
        *,
        connect_timeout: float = 10,
        timeout: float = 30,
        max_bytes: int = 8 * 1024 * 1024,
        max_redirects: int = 3,
        attempts: int = 3,
        resolver: Callable = public_addresses,
    ):
        self.connect_timeout, self.timeout = connect_timeout, timeout
        self.max_bytes, self.max_redirects = max_bytes, max_redirects
        self.attempts, self.resolver = min(max(attempts, 1), 3), resolver

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> HTTPResult:
        return self.request("GET", url, headers=headers)

    def post_json(self, url: str, payload: dict, *, headers: dict[str, str] | None = None) -> HTTPResult:
        return self.request("POST", url, headers=headers, body=json.dumps(payload).encode())

    def request(self, method: str, url: str, *, headers=None, body=None) -> HTTPResult:
        if method not in {"GET", "POST"}:
            raise ValueError("Only connector GET and read-only search POST are supported")
        deadline = time.monotonic() + self.timeout
        for attempt in range(self.attempts):
            try:
                result = self._redirects(method, url, headers or {}, body, deadline)
                if (result.status_code == 429 or result.status_code >= 500) and attempt + 1 < self.attempts:
                    delay = self._retry_delay(result.headers.get("retry-after"), attempt)
                    if time.monotonic() + delay < deadline:
                        time.sleep(delay)
                        continue
                return result
            except (OSError, TimeoutError, http.client.HTTPException) as exc:
                if attempt + 1 >= self.attempts or time.monotonic() + 1 >= deadline:
                    raise SourceHTTPError("NETWORK_ERROR", "Public source request failed", retryable=True) from exc
                time.sleep(min(2**attempt + random.random() / 4, max(0, deadline - time.monotonic())))
        raise SourceHTTPError("REQUEST_FAILED", "Source request exhausted retries")

    @staticmethod
    def _retry_delay(value: str | None, attempt: int) -> float:
        if value:
            try:
                numeric = float(value)
                if math.isfinite(numeric):
                    return min(365 * 86400, max(0, numeric))
            except ValueError:
                try:
                    return max(0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
                except (ValueError, TypeError):
                    pass
        return 2**attempt + random.random() / 4

    def _redirects(self, method, url, headers, body, deadline):
        current = url
        for redirects in range(self.max_redirects + 1):
            validate_url(current)
            result = self._request_once(method, current, headers, body, deadline)
            if result.status_code not in {301, 302, 303, 307, 308}:
                return result
            location = result.headers.get("location")
            if not location:
                raise SourceHTTPError("INVALID_REDIRECT", "Source redirect omitted destination")
            if redirects == self.max_redirects:
                raise SourceHTTPError("TOO_MANY_REDIRECTS", "Source redirect limit exceeded")
            target = urljoin(current, location)
            old, new = urlsplit(current), urlsplit(target)
            if old.scheme == "https" and new.scheme != "https":
                raise SourceHTTPError("UNSAFE_REDIRECT", "HTTPS source cannot redirect to unencrypted HTTP")
            if old.netloc != new.netloc:
                headers = {
                    k: v
                    for k, v in headers.items()
                    if k.lower() not in {"authorization", "authorization-key", "cookie", "x-api-key"}
                }
            if result.status_code == 303 or (result.status_code in {301, 302} and method == "POST"):
                method, body = "GET", None
            current = target
        raise AssertionError("unreachable")

    def _request_once(self, method, url, headers, body, deadline):
        scheme, host, port = validate_url(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SourceHTTPError("TIMEOUT", "Source request exceeded total timeout", retryable=True)
        if not _DNS_SLOTS.acquire(timeout=min(self.connect_timeout, remaining)):
            raise SourceHTTPError("DNS_BUSY", "Source DNS concurrency limit reached", retryable=True)
        future = _DNS_POOL.submit(self.resolver, host, port)
        future.add_done_callback(lambda _: _DNS_SLOTS.release())
        try:
            addresses = future.result(timeout=min(self.connect_timeout, remaining))
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise SourceHTTPError("DNS_TIMEOUT", "Source DNS resolution timed out", retryable=True) from exc
        # Validate injected/custom resolvers as well as the production resolver.
        for _, addr in addresses:
            if not is_public_address(addr):
                raise SourceHTTPError("UNSAFE_ADDRESS", "DNS resolved to a non-public source address")
        if not addresses:
            raise SourceHTTPError("DNS_UNAVAILABLE", "No public address resolved", retryable=True)
        family, address = addresses[0]
        timeout = min(self.connect_timeout, deadline - time.monotonic())
        if timeout <= 0:
            raise SourceHTTPError("TIMEOUT", "Source request exceeded total timeout", retryable=True)
        conn = (
            http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
            if scheme == "https"
            else http.client.HTTPConnection(host, port, timeout=timeout)
        )

        def pinned_connection(*args, **kwargs):
            sock = socket.socket(family, socket.SOCK_STREAM)
            try:
                sock.settimeout(timeout)
                sock.connect((address, port))
                if sock.getpeername()[0] != address:
                    raise SourceHTTPError("UNSAFE_ADDRESS", "Connected peer did not match pinned address")
                return sock
            except BaseException:
                sock.close()
                raise

        conn._create_connection = pinned_connection
        request_headers = {
            "User-Agent": "PersonalStaffer/0.1 public-job-research",
            "Accept-Encoding": "identity",
            "Accept": "application/json,text/html;q=0.9",
        }
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        for key, value in headers.items():
            if key.lower() not in {"host", "connection", "accept-encoding", "content-length"}:
                request_headers[key] = value
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        try:
            conn.request(method, path, body=body, headers=request_headers)
            conn.sock.settimeout(max(0.001, deadline - time.monotonic()))
            response = conn.getresponse()
            result_headers = {k.lower(): v for k, v in response.getheaders()}
            if response.status >= 300:
                # Redirect/rate/block states need headers, not untrusted error-page bodies.
                return HTTPResult(response.status, b"", url, result_headers)
            if result_headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                raise SourceHTTPError("UNSUPPORTED_ENCODING", "Compressed source response refused by bounded reader")
            try:
                advertised = int(result_headers.get("content-length", "0"))
            except ValueError:
                advertised = 0
            if advertised > self.max_bytes:
                raise SourceHTTPError("PAYLOAD_TOO_LARGE", "Source response exceeds byte limit")
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SourceHTTPError("TIMEOUT", "Source request exceeded total timeout", retryable=True)
                if conn.sock is not None:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(65536, self.max_bytes - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > self.max_bytes:
                    raise SourceHTTPError("PAYLOAD_TOO_LARGE", "Source response exceeds byte limit")
                chunks.append(chunk)
            return HTTPResult(response.status, b"".join(chunks), url, result_headers)
        finally:
            conn.close()
