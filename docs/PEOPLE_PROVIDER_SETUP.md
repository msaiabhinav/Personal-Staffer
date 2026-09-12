# Public People enrichment

Status: the public-search adapter, evidence filters, PostgreSQL cache, committed
query budgets, durable refresh endpoint and alphabetical group presentation are
implemented. No public-search key was supplied. Real personnel coverage, result
quality, provider permission for retained snippets and operating cost have not
been validated. M6 live discovery remains **Not configured**, not complete.

## Implemented optional provider

An optional Brave Search API adapter calls its documented
`https://api.search.brave.com/res/v1/web/search` endpoint using the backend-only
`X-Subscription-Token` header. It requests English U.S. public web results, parses
titles/snippets and normalizes actual LinkedIn `/in/` URLs. It does not browse
LinkedIn profiles, collect LinkedIn cookies, log in, message anyone or use
LinkedIn as a job source.

Activation is a deployment choice after a public-result pilot and review of the
provider's current plan and storage terms. No subscription was purchased. Set:

```text
PEOPLE_SEARCH_PROVIDER=brave
PEOPLE_SEARCH_API_KEY=<server-side secret>
PEOPLE_DAILY_QUERY_BUDGET=400
```

An empty provider/key or unsupported provider has a visible NOT_CONFIGURED
enrichment run; it does not fabricate profiles or claim successful live coverage.
The adapter boundary accepts deterministic replay transports for tests. A new
provider must implement the same typed public-result contract and receive its
own compatibility/terms review.

## Evidence policy and display

Only actual HTTPS LinkedIn profile URLs returned by the provider are accepted;
tracking query parameters and fragments are removed. Nonprofile paths,
look-alike hosts, credentials in URLs and unsupported schemes are rejected.

The initial deterministic parser requires the profile result title to identify
a person's name, relevant current role and exact employer name. Former/retired
roles and results older than 30 days are withheld from new enrichment. Search
results remain labelled `SEARCH_RESULT_ONLY`: a freshly retrieved search result
does **not** prove the underlying profile is current or publicly reachable.
Cards display the evidence date and limitation.

The four display groups, in order, are:

1. Recruiter or HR.
2. Hiring Manager.
3. Same Hiring Team.
4. Same Department/Relevant Department Leader.

Recruiters/HR at the employer may be LIKELY; responsibility for the particular
opening is explicitly unconfirmed. Hiring Manager is CONFIRMED only when retained
job evidence actually names that person. Relevant department leaders require
department evidence and a relevant leadership role. A generic same-company
analyst is never assumed to be on the same hiring team. The current adapter
does not automatically populate Same Hiring Team without sufficient evidence.
Names are alphabetized within groups, with no percentages or ranking scores.
Display is limited to ten supported profiles per job; it may be zero.

Shared canonical profile identities are deduplicated in PostgreSQL, and
job-person evidence is retained separately. Missing people never change job
eligibility, daily quota, report publication or saved/application history.
Historical stale links remain visible with their previous evidence date and a
stale label; they are not presented as freshly verified.

## Query and cost bounds

At most eight targeted queries are constructed per job, usually three employer
recruiting queries plus any explicitly evidenced department/named-person queries.
Company/query results are reused from a one-day cache. The initial daily budget
is 400 provider requests per UTC calendar day across the backend. This is an
engineering limit, not a dollar estimate. `cost_units` currently counts reserved
provider requests; it is not a claim about a provider's bill.

Every uncached request is reserved and **committed before HTTP** while holding a
global PostgreSQL budget lock. A failed or interrupted request may still consume
one reservation because it may have been billed. It is not silently refunded on
worker retry. This prevents two devices or workers from independently exceeding
the configured budget. HTTP occurs outside the database transaction.

Budget exhaustion yields PENDING_BUDGET. Partial supported results are retained;
the run does not pretend the search completed. Provider authentication failures,
quota limits, request errors and unreadable payloads expose the corresponding
UNAVAILABLE/RATE_LIMITED state and safe reason. The enrichment run records
queries, discovered/approved counts and request units.

`POST /api/v1/jobs/{id}/people-refresh` requires an owned retained job and an
`Idempotency-Key`, queues `people.enrich`, and returns 202 with a work reference.
`GET /jobs/{id}/people` returns run state and cards. `GET /people` groups by owned
job with job/company filters and cursor pagination.

## Pilot needed before provider selection is final

Compare current provider pricing and retention terms using its official account
information. With an authorized key, measure supported public results for
watchlist employers, a university/academic medical center, and NYC/Bay Area
startups. Manually audit current employment and role relationships where public
evidence permits it; retain limitations when profile access is blocked. Report
queries per job, zero-result and supported-result counts, stale evidence rate,
coverage by relationship group, and actual billed cost. A result quality or terms
failure is a reason to keep the integration disabled or implement another
legitimate provider, not to fill cards with invented people.

Run tests from `backend/`:

```text
uv run pytest -q tests/test_people_discovery.py
TEST_DATABASE_URL=postgresql+psycopg://... uv run pytest -q tests/test_auth_email_people_postgres.py
```

Primary source checked during implementation:
[Brave Search API documentation](https://api-dashboard.search.brave.com/).
The public documentation establishes request shape, not actual result quality
or permission for a particular subscription's storage behavior.
