"""Google confidential backend authorization-code/OIDC adapter.

Provider endpoints are fixed, never taken from incoming token claims.
"""

from __future__ import annotations

import hmac

import httpx
from authlib.integrations.httpx_client import OAuth2Client
from authlib.oidc.core import CodeIDToken
from joserfc import jwt
from joserfc.jwk import KeySet

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class GoogleProvider:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.transport = transport

    def client(self, redirect_uri: str, *, state: str | None = None, scope="openid email profile"):
        return OAuth2Client(
            self.settings.google_client_id,
            self.settings.google_client_secret,
            redirect_uri=redirect_uri,
            scope=scope,
            state=state,
            token_endpoint_auth_method="client_secret_post",
            code_challenge_method="S256",
            timeout=30,
            transport=self.transport,
            follow_redirects=False,
        )

    def authorize(self, redirect_uri: str, state: str, nonce: str, verifier: str, mailbox=False) -> str:
        scope = "openid email profile" + (" " + GMAIL_SCOPE if mailbox else "")
        with self.client(redirect_uri, state=state, scope=scope) as client:
            extra = {"access_type": "offline", "prompt": "consent"} if mailbox else {"prompt": "select_account"}
            uri, _ = client.create_authorization_url(
                AUTHORIZE_URL, state=state, nonce=nonce, code_verifier=verifier, **extra
            )
            return uri

    def exchange(self, redirect_uri: str, callback_url: str, state: str, nonce: str, verifier: str):
        with self.client(redirect_uri, state=state) as client:
            token = client.fetch_token(TOKEN_URL, authorization_response=callback_url, code_verifier=verifier)
        if not token.get("id_token"):
            raise ValueError("Provider did not return an identity token")
        with httpx.Client(timeout=15, transport=self.transport, follow_redirects=False) as client:
            response = client.get(JWKS_URL)
            response.raise_for_status()
            keys = KeySet.import_key_set(response.json())
        decoded = jwt.decode(token["id_token"], keys, algorithms=["RS256"])
        claims = CodeIDToken(
            decoded.claims,
            decoded.header,
            options={
                "iss": {"essential": True, "values": ["https://accounts.google.com", "accounts.google.com"]},
                "aud": {"essential": True, "value": self.settings.google_client_id},
                "exp": {"essential": True},
                "iat": {"essential": True},
                "sub": {"essential": True},
            },
            params={
                "nonce": nonce,
                "client_id": self.settings.google_client_id,
                "access_token": token.get("access_token"),
            },
        )
        claims.validate(leeway=60)
        if not isinstance(claims.get("sub"), str) or not claims["sub"]:
            raise ValueError("Missing provider subject")
        if claims.get("email_verified") is not True or not claims.get("email"):
            raise ValueError("A verified Google email is required")
        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise ValueError("Invalid identity nonce")
        return dict(claims), dict(token)

    def refresh(self, encrypted_refresh: str, box):
        # No scope on refresh: Authlib would otherwise send the client's default sign-in scope
        # and Google would downscope the access token, dropping gmail.readonly
        # (ACCESS_TOKEN_SCOPE_INSUFFICIENT on every mailbox call).
        with self.client(self.settings.gmail_redirect_uri, scope=None) as client:
            return dict(client.refresh_token(TOKEN_URL, refresh_token=box.decrypt(encrypted_refresh)))

    def revoke(self, refresh_token: str):
        with httpx.Client(timeout=15, transport=self.transport, follow_redirects=False) as client:
            result = client.post(REVOKE_URL, data={"token": refresh_token})
            result.raise_for_status()
