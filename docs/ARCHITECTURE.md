# Architecture

A modular monolith exposes one versioned authenticated API. Flutter/Riverpod/go_router clients use an encrypted Drift/SQLite cache and OS-protected session/key storage. PostgreSQL is authoritative. Opaque app session secrets are stored hashed; Google mailbox refresh tokens use separate Fernet encryption.

## Domain flow

Connectors produce typed source payloads and per-field provenance. SafeHTTP pins vetted public IPs and checks redirects, byte limits, timeouts and application identity. `jobs/pipeline.py` stores immutable snapshots, identities, extracted facts and append-only evaluations. Brand rotation groups never automatically become legal employers. An audited employer register supplies actual entity proof. Unknown or conflicting proof withholds delivery.

`reports/service.py` locks the owning user and re-evaluates retained evidence at delivery. Shared 32-day calendar cycles reserve companies only with frozen report membership. Database guards cap50 slots and2 jobs per company. The initial-delivery ledger survives cycles and prevents the same opening appearing as new. Salary determines selection priority, while final presentation remains newest first. Priority delivery uses the same hard gates and initial ledger.

Save/Apply/status/correction commands hold the user lock, check expected revision and record idempotency results in the same transaction as state, event history and change cursors. Apply opens and explicit Applied are separate actions. Corrections target events and preserve later independent history. Immutable snapshots keep saved/applied source evidence available after source deletion.

WorkItems and OutboxEvents survive Redis loss. Dispatcher uses leases and compare-and-set state changes; workers impose bounded attempts. Reconciliation covers expired leases and lost dispatched messages. External push is at-least-once: provider acceptance followed by process failure can repeat a hint, but inbox/application/report database effects stay deduplicated.

Gmail identity matching and status meaning are independent deterministic decisions. Ambiguity creates a review item. Source and Gmail network fetches run outside user database locks; short transactions persist each source result or a complete Gmail page. A Gmail history cursor commits only with the page's fetched evidence and effects, and a compare-and-set guard discards stale concurrent fetches. Sender authentication and employer association are separate checks before an automatic mail update; untrusted or quoted content goes to review. People query budgets commit before each provider request; current relationship evidence controls alphabetical groups, never scores. Neither email nor People unavailability stops manual tracking or job evaluation.

## Deployment boundaries

Production Compose has API, worker, Beat, dispatcher, PostgreSQL, Redis and Caddy. API/worker/scheduler use one image. Only Caddy exposes80/443; no database/broker ports are published. Private app and migration roles are separate. A single VPS remains a single point of failure. Encrypted off-server backups and a clean restore gate are required before use.

## Compatibility

API and client start at0.1.0, `/api/v1`. Version manifest truthfully has no published download URLs. Update by installing a separately verified native artifact and applying explicit migrations with the owner role. Generated OpenAPI is retained in `openapi.json`. Three reviewed migration files define the current schema; inspect the actual migration head before updating.
