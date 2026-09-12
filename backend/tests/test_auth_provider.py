from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from authlib.oauth2.rfc6749.errors import MismatchingStateException
from cryptography.fernet import Fernet
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import RSAKey

from app.auth.crypto import SecretBox, challenge, digest
from app.auth.provider import GoogleProvider


def config():
    return SimpleNamespace(
        google_client_id="client-id",
        google_client_secret="server-only",
        gmail_redirect_uri="https://staffer.example/api/v1/gmail/callback",
    )


def test_oauth_code_flow_state_nonce_pkce_and_no_secret_in_url():
    url = GoogleProvider(config(), httpx.MockTransport(lambda r: httpx.Response(200))).authorize(
        "https://staffer.example/api/v1/auth/google/callback", "state", "nonce", "a" * 64
    )
    params = parse_qs(urlsplit(url).query)
    assert params["response_type"] == ["code"]
    assert params["state"] == ["state"] and params["nonce"] == ["nonce"]
    assert params["code_challenge"] == [challenge("a" * 64)]
    assert params["code_challenge_method"] == ["S256"]
    assert "server-only" not in url
    assert "gmail.readonly" not in url


def test_provider_token_encryption_and_hashes():
    box = SecretBox(Fernet.generate_key().decode())
    encrypted = box.encrypt("secret")
    assert encrypted != "secret" and box.decrypt(encrypted) == "secret"
    assert digest("secret") != "secret"
    with pytest.raises(ValueError):
        SecretBox("")


@pytest.mark.parametrize("bad_claim", [None, "nonce", "aud", "iss", "exp", "email_verified"])
def test_oidc_signed_claim_contract(bad_claim):
    key = RSAKey.generate_key(2048)
    key.ensure_kid()
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "iss": "https://accounts.google.com",
        "sub": "subject-123",
        "aud": "client-id",
        "nonce": "nonce",
        "iat": now,
        "exp": now + 600,
        "email": "owner@example.com",
        "email_verified": True,
    }
    if bad_claim:
        claims[bad_claim] = {
            "nonce": "wrong",
            "aud": "other-client",
            "iss": "https://evil.invalid",
            "exp": now - 1000,
            "email_verified": False,
        }[bad_claim]
    token = jwt.encode({"alg": "RS256", "kid": key.kid}, claims, key)

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            assert b"code_verifier=" in request.content
            return httpx.Response(200, json={"access_token": "access", "token_type": "Bearer", "id_token": token})
        return httpx.Response(200, json={"keys": [key.as_dict(private=False)]})

    provider = GoogleProvider(config(), httpx.MockTransport(handler))
    args = (
        "https://staffer.example/callback",
        "https://staffer.example/callback?code=code&state=state",
        "state",
        "nonce",
        "a" * 64,
    )
    if bad_claim:
        with pytest.raises((JoseError, ValueError)):
            provider.exchange(*args)
    else:
        identity, _ = provider.exchange(*args)
        assert identity["sub"] == "subject-123"


def test_oauth_mismatched_state_never_calls_token_endpoint():
    def handler(request):
        pytest.fail("Mismatched state reached token endpoint")

    provider = GoogleProvider(config(), httpx.MockTransport(handler))
    with pytest.raises(MismatchingStateException):
        provider.exchange(
            "https://staffer.example/callback",
            "https://staffer.example/callback?code=code&state=wrong",
            "state",
            "nonce",
            "a" * 64,
        )
