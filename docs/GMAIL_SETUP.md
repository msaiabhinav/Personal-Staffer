# Google sign-in and Gmail setup

Status: backend OAuth, application sessions, read-only mailbox synchronization,
deterministic matching, review and correction code are implemented. No Google
project, owner account, consent grant or live mailbox was supplied. Live sign-in,
background grant renewal and Windows/Android browser callbacks remain unverified.
Credentials must be configured securely on the backend; do not paste them into
chat or place them in Flutter defines.

## Google project and server client

1. Create or choose an authorized Google Cloud project and enable the Gmail API.
2. Configure the OAuth consent screen for the private application's actual use.
   Add the intended user as a test user if the project is in Testing. Check the
   current Google verification/publishing requirements before sustained use.
3. Create a **Web application** OAuth client for the confidential backend callback
   flow used here. Do not create a secret-bearing desktop flow and embed its
   secret in the client. Register the exact HTTPS redirect URIs:
   `https://YOUR-BACKEND/api/v1/auth/google/callback` and
   `https://YOUR-BACKEND/api/v1/gmail/callback`.
4. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`,
   `GMAIL_REDIRECT_URI`, `OWNER_ALLOWED_EMAIL` and `TOKEN_ENCRYPTION_KEY` in the
   server secret environment. `OWNER_GOOGLE_SUBJECT` can additionally pin the
   Google subject before enrollment. The first verified allowlisted login stores
   Google's stable subject in PostgreSQL; later logins match that subject.
5. Generate the Fernet encryption key once in a secure shell:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   Preserve it separately from the database in protected recovery storage.
   Replacing it without re-encrypting existing provider tokens makes those tokens
   unreadable and requires reconnection. Database dumps contain encrypted Google
   refresh tokens and hashed opaque app session tokens, not their plaintext.

The application requests `openid email profile` for sign-in. Gmail connection is
a separate authenticated action requesting `gmail.readonly` with offline access.
It does not send, delete, modify or mark email as read. A selected Gmail label
limits processing, not the underlying breadth of the read-only grant.

## Device callback and session contract

The installed client generates a cryptographically random 43–128 character
verifier and a base64url SHA-256 challenge. Start login with:

```json
{"device_id":"UUID","platform":"WINDOWS","device_label":"My PC","challenge":"BASE64URL_SHA256"}
```

`POST /api/v1/auth/login/start` returns `authorization_url`, `flow_id` and
`expires_at`. Open the authorization URL in the system browser. The backend uses
Authlib authorization code flow with provider PKCE, state and nonce and validates
the signed Google ID token (issuer, audience, expiry, verified email and nonce).
The ten-minute flow stores a separate device challenge.

The callback redirects to `personalstaffer://auth?flow_id=UUID`. This URL contains
no session or Google credentials. The client redeems it with
`POST /api/v1/auth/login/exchange` and `{flow_id, device_id, verifier}`. A different
device/verifier is rejected. Polling before completion returns `AUTH_PENDING`.
Windows protocol registration and Android launch handling must be tested using
the native integration checklist before release.

Opaque access tokens expire after 15 minutes by default. `POST /auth/refresh`
accepts `{refresh_token,device_id}` and rotates both tokens. Retained hashes detect
replay of a previously used refresh token and revoke that device's sessions.
Refresh expiry defaults to 30 days. `/auth/logout` revokes the current session;
`DELETE /devices/{id}` revokes the device. A revoked device must sign in again.

## Connect and synchronize Gmail

`POST /api/v1/gmail/connect` requires an authenticated owned device and the same
device/platform/label/challenge fields as login, with optional `selected_label`.
Open its returned Google consent URL. The callback requires the same Google
subject as the signed-in account, checks `gmail.readonly`, and encrypts the
background refresh token. It redirects to
`personalstaffer://settings/gmail?flow_id=UUID` after connection.

Settings reads `/gmail/status` to show mailbox, scopes, selected label, last
successful sync and continuation progress. `POST /gmail/sync` with an
`Idempotency-Key` queues `gmail.sync` durable work. It never reads a mailbox in the
UI request. Default polling is five minutes.

The first backfill is limited to job-related messages from the preceding
`GMAIL_BACKFILL_DAYS` (default 30, configured maximum 90). The Gmail profile history
baseline is captured **before** backfill, then subsequent history polling catches
mail arriving during backfill. Each task handles at most one page, retaining its
continuation. History IDs advance only in the transaction that commits messages,
application events or reviews; intermediate history pages retain the old final
cursor. A 404 expired history response triggers a fresh bounded reconciliation.
Message IDs deduplicate all retries. Unrelated messages are not stored.

Matching and status interpretation are independent. An employer/requisition,
known linked thread, or consistent company/title/application-date match is
required. Sender domain alone cannot identify a job. Ambiguous identities,
unmatched confirmations, unknown templates, generic status updates and
forwarded/conditional messages enter review. Confirmed messages use the same
application event service as manual changes. Delayed confirmations do not regress
Interviewing. Corrections retain the email link and are never applied repeatedly
on every sync.

Automatic updates also require a single actual From address, a single trusted-boundary `mx.google.com` Authentication-Results header with aligned DMARC pass, and an exact employer domain or a previously user-confirmed sender for that application. Shared ATS senders require initial manual review. Spam, trash, sent, draft and self-sent mail cannot automate a status. This is conservative screening, not proof against imported headers or a compromised mailbox/employer account.

Quoted HTML chains, attached RFC822 messages and forwarded content do not supply automatic status evidence. MIME size/depth/part limits and malformed encoding route the message to review. Mailbox fetches happen outside database user locks; a state comparison discards a stale page before effects commit. The retained evidence separates sender trust, application identity and status meaning.

`GET /reviews`, `GET /reviews/{id}` and `POST /reviews/{id}/resolve` support
DISMISS, LINK and CREATE_APPLICATION. Resolution requires `expected_revision`, a
reason and `Idempotency-Key`. Linking includes the target application revision;
creating includes the actual company/title/date and optional real URLs. No URL
or application is invented. Resolving a status is an explicit user decision.

## Reconnection and disconnect

Expired/revoked grants produce `RECONNECT_REQUIRED`, preserving job search,
manual tracking and existing application evidence. Quota/network failures show
`RATE_LIMITED` or `UNAVAILABLE`; cursor and event changes roll back together.
Google Testing-mode grants may expire after seven days when restricted scopes
are used. Consent/publishing status must be checked rather than assuming an
indefinite background grant.

`DELETE /gmail/connection` attempts Google revocation and always removes the
stored refresh token. The response reports whether provider revocation succeeded;
if not, remove access in the Google account's third-party access settings as
well. Retained application evidence survives disconnect.

## Verification and remaining release checks

Run from `backend/`:

```text
uv run pytest -q tests/test_auth_provider.py tests/test_email_parser.py tests/test_email_gmail_api.py
TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest -q tests/test_auth_email_people_postgres.py
```

The PostgreSQL tests create and remove their own random schema. Use an isolated
test database. They check device-bound redemption, refresh replay revocation,
stable subject ownership, correct email effects, ambiguous review, correction
dedupe, cursor rollback/pagination, expired history, and People budgets.

Required live checks: actual allowed-owner login; rejection of a different Google
account; deny/accept Gmail consent; initial 30-day processing and known-message
review; restart/refresh; expired/revoked token; actual Windows and Samsung callback
activation. No such checks have been claimed as executed without credentials.

Primary compatibility sources checked during implementation:
[Authlib OAuth clients](https://docs.authlib.org/en/stable/oauth2/client/http/index.html),
[Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect),
[Gmail synchronization](https://developers.google.com/workspace/gmail/api/guides/sync),
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes), and
[Google token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).
