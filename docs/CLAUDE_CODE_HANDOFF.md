# Personal Staffer — Complete Claude Code Handoff

**Handoff date:** September 12, 2026  
**Product status:** Implementation checkpoint; not release-accepted  
**Current priority:** Windows desktop application first  
**Repository:** <https://github.com/msaiabhinav/Personal-Staffer>  
**Published branch:** `feature/personal-staffer-core`  
**Published commit:** `35338e6f3fad8256a14d41fab3c5c9aac09749d2`  
**Implementation commit:** `a852668e07ad85ddbd883e2a1c7e99334ef97473`  
**GitHub Actions run:** <https://github.com/msaiabhinav/Personal-Staffer/actions/runs/34701723350>

## 1. Instructions to Claude Code

You are taking over an existing, substantial codebase. Do not regenerate the project, replace its architecture, reduce it to a mock, or turn it into a website. Read this file and every canonical document listed below before changing code. Inspect `git status`, the active branch, the latest commits, and any user modifications first. Preserve all existing work.

The immediate objective is to run and debug the real Windows desktop application on the user's Asus Vivobook Pro 15. Android is still in scope, but it is deliberately deferred until the Windows desktop workflow passes physical-device acceptance.

Work autonomously through anything that does not need the user's physical action or credentials. Ask only for genuine blockers such as administrator approval for installing a missing tool, Google consent in a system browser, or access to an external service. Never request passwords, session cookies, recovery codes, private keys, or broad account access in chat.

For every defect:

1. Capture exact reproduction steps and output.
2. Identify the root cause rather than masking the symptom.
3. Make the smallest safe correction.
4. Add or update a regression test.
5. Rerun the failed check and related security checks.
6. Update the progress evidence honestly.

After the first complete desktop build, run two full debugging/verification loops. A skipped or unexecuted test is never a pass. Do not claim device behavior from Linux tests or compilation alone.

## 2. Canonical documents and precedence

Read these completely in this order:

1. `docs/BUILD_SPECIFICATION.md` — authoritative product contract.
2. `docs/REQUIREMENTS.md` — PR-01 through PR-25 implementation map.
3. `docs/POLICY_DEFAULTS.md` — hard eligibility/evidence semantics.
4. `docs/ARCHITECTURE.md` — current architecture and transactional design.
5. `docs/BUILD_STATUS.md` — implementation and verification state.
6. `docs/TEST_RESULTS.md` — exact executed checks and limitations.
7. `docs/SECURITY_REVIEW.md` — findings, fixes, controls, residual risk.
8. `docs/KNOWN_LIMITATIONS.md` — unfinished and externally blocked gates.
9. `docs/CONTINUATION.md` — next executable actions.
10. `docs/WINDOWS_SETUP.md` — desktop toolchain, build and device acceptance.
11. `docs/ANDROID_SETUP.md` — later Samsung work.
12. `docs/DEPLOYMENT.md`, `docs/BACKUP_RESTORE.md`, `docs/GMAIL_SETUP.md`, `docs/EVERIFY_WORKFLOW.md`, `docs/PEOPLE_PROVIDER_SETUP.md`, `docs/SOURCE_CAPABILITIES.md`, and `docs/JOBSPY_SETUP.md`.
13. `README.md`, `Readme.txt`, `.env.example`, `requirements.txt`, `backend/requirements-dev.txt`, and `.github/workflows/ci.yml`.

Later explicit user instructions take precedence over this handoff. Do not change hard policy silently. Record a material architectural deviation in an ADR with the reason and requirement impact.

## 3. What the user is building

Personal Staffer is a private, single-user job-discovery and application-tracking product. It is an installed native application, not a public website or browser SaaS.

Target devices:

- Windows first: Asus Vivobook Pro 15, 24 GB RAM, 2 TB SSD, Intel Ultra 9, NVIDIA RTX 3050 6 GB.
- Android later: Samsung Galaxy S25 Ultra.
- Both clients eventually share the same cloud backend state.
- Cloud searches and scheduling must continue while either device is asleep or offline.

Identity and platform decisions:

- App name: **Personal Staffer**.
- Single authorized owner: `msaiabhinav2000@gmail.com`.
- Gmail is the chosen mailbox provider.
- `msaiabhinav2000@proton.me` was explicitly withdrawn and must not be configured.
- Google sign-in and Gmail read-only consent are separate authorization flows.
- Never request the user's Gmail password.
- No resume is required or collected.
- USA jobs only.
- No iPhone client is required.
- No public multi-user SaaS is required.

The product should discover trustworthy openings, explain why they qualify or were withheld, preserve evidence, link to the real application destination, and track the user's application history safely.

Core flow:

`discover → retrieve real posting → normalize evidence → enforce hard eligibility → evaluate relevance → deduplicate → deliver/notify → save/apply/track/correct`

The goal is up to 50 new qualifying regular jobs at 11:00 AM America/New_York. Never weaken policy or fabricate jobs to reach 50. Priority jobs are additional and still pass every hard eligibility rule.

## 4. Explicit exclusions

Do not add or enable any of the following unless the user later changes scope explicitly:

- Resume upload, parsing, extraction, or resume-driven onboarding.
- Automatic job applications.
- LinkedIn login or LinkedIn job scraping.
- Automatic LinkedIn connection requests.
- Automatic email, LinkedIn, or other message sending.
- Runtime LLM APIs, local LLM serving, RAG, MCP, Kafka, or microservices as initial dependencies.
- GPU dependence for normal operation.
- A browser-first/public website replacing the installed clients.
- Fuzzy E-Verify approval based on employer brand names.
- Synthetic/demo evidence in real operation.

People functionality may show up to ten relevant public LinkedIn profile links per job with retained relationship evidence. It must not log in to LinkedIn, rank people by invented percentages, or send messages.

## 5. Product requirements that must remain intact

The authoritative wording is PR-01 through PR-25 in `docs/BUILD_SPECIFICATION.md`. The following is an operational summary, not a replacement:

| Area | Required behavior |
|---|---|
| Clients | Installed Windows and Android clients, shared server state, Windows delivered first. |
| Identity | One owner, Google sign-in, Gmail selected, no resume. |
| Geography | Explicit U.S. workplace or explicit U.S.-remote eligibility; generic “remote” is insufficient. |
| Employment | Credibly confirmed full-time. Exclude contract, temporary, part-time, seasonal, internship, per-diem, freelance, and consulting engagements. |
| E-Verify | Current proof for the actual legal employing entity. Search miss means unknown, not nonparticipation. Unknown/conflicting identity is withheld. |
| Sponsorship | Explicit no-sponsorship/no-transfer/citizen-or-PR/visa-candidate restrictions fail. Silence in a complete JD may pass this exclusion rule but displays `NOT_STATED`. |
| Clearance | Required clearance, Public Trust, suitability, or ability to obtain/maintain fails. Preferred-only is flagged. Normal background checks do not fail. |
| Experience | Exact 4 years, 2–4, and up to 4 pass. `4+`, at least/minimum/more than 4, or a mandatory range above 4 fail. `1+`, `2+`, and `3+` pass unless another mandatory higher clause exists. Missing/ambiguous experience is review. |
| Freshness | Full JD, active actionable opening, and supported publication age no more than 72 hours. First-seen and updated timestamps do not manufacture freshness. |
| Relevance | Match approved role families and substantive duties, not incidental keywords. |
| Salary | $80,000 annual USD is preferred, not a hard floor. Undisclosed remains eligible; lower compensation may fill later slots. Never invent annual conversions. |
| Daily report | Maximum 50 regular jobs, maximum 2 per company, salary-band selection followed by newest-first presentation. |
| Rotation | Shared 32-day employer cycle plus permanent duplicate/repost suppression. |
| Priority | Watchlist, qualifying universities/academic medical centers, and Connecticut-specific openings are additional to regular quota and cycle. They never bypass hard gates. |
| Startup pools | Dedicated New York City and Bay Area employer pools supplement nationwide search. Pool location does not overwrite job location or create priority by itself. |
| Sources | Official employer pages and ATS sources preferred; specialized sources supported where qualified; JobSpy excludes LinkedIn and is currently security-blocked. |
| Job records | Full retained JD snapshot, evidence, source/original links, and actual application destination. |
| Saved jobs | Persist until explicitly unsaved or applied; no age-based deletion. |
| Applications | Permanent source/JD snapshot, status events, corrections, manual external application entry, and durable history. Opening an Apply link does not mark Applied. |
| Gmail | Read-only status discovery, conservative identity/sender checks, ambiguous changes routed to review, correctable automatic effects. |
| Notifications | Persistent inbox, unread count, deduplicated events, exact navigation target. |
| Sync | Cross-device, explicit pending states, account-bound offline queue, revision/idempotency conflict protection, safe resnapshot/tombstones. |
| Operations | Search history, source health, partial-coverage explanations, backups/restore, secure installation/update instructions. |

Initial role families include data analysis, business analysis, business systems analysis, business intelligence/reporting/insights, operations/revenue/growth, AI and machine learning, analytics engineering, forward deployment, healthcare, supply chain, finance, research data, and university/academic medical analytics. Titles alone are insufficient.

Initial skill vocabulary includes SQL, Power BI/PowerBI/PowwerBI, Python, Excel, machine learning, Snowflake, AI, LLMs, forecasting, business analysis, Tableau, VLOOKUP/XLOOKUP, Qlik, pandas, Databricks, statistics, and data analysis. Preserve aliases and distinguish exact skills from related technologies.

Priority employer seeds:

- HCA Healthcare
- Henry Ford Health
- Infosys
- Cognizant
- Tata Consultancy Services (TCS)
- Thermo Fisher Scientific
- Walmart
- Amazon
- Microsoft
- Tesla
- Analog Devices

## 6. Exact client information architecture

The five navigation items and order are contractually fixed:

1. Notifications
2. Homepage
3. People
4. Saved Jobs
5. Applied Jobs

Homepage contains the required tabs/feeds defined in the canonical specification and existing widget tests. Settings is accessible separately. Existing routes also cover job details, evidence, applications, reports, email reviews, search runs, notifications, and collections.

Do not rename or reorder the five primary destinations without an explicit product decision and updated requirements/tests.

## 7. Locked architecture

### Backend

- Python 3.12–3.13.
- FastAPI modular monolith under `backend/app`.
- PostgreSQL 17 is authoritative; SQLite must never substitute for backend behavioral tests.
- Redis is the broker/runtime coordination dependency.
- Celery worker and Celery Beat handle durable/background work.
- A database-backed WorkItem/Outbox dispatcher and reconciliation path recover lost broker delivery and expired leases.
- SQLAlchemy and Alembic; three reviewed migrations and approximately 49 tables at the checkpoint.
- Caddy terminates production HTTPS/TLS.
- Docker Compose defines local and production topologies.

Main backend domains:

- `auth`: Google/OIDC, owner enrollment, sessions, devices, PKCE, token rotation.
- `config`: validated environment and independent integration states.
- `db`: models, sessions, migration readiness.
- `connectors`: ATS/direct/Workday/USAJOBS/optional JobSpy, parsing, safe HTTP.
- `eligibility`: evidence models, deterministic rules, text clauses, replay corpus.
- `relevance`: versioned role/skill matching.
- `jobs`: ingestion, evidence, canonical identity, orchestration and source runs.
- `reports`: salary selection, quota, company rotation and priority delivery.
- `applications`: save/apply/manual status/correction and permanent history.
- `email`: Gmail retrieval, parsing, identity/sender trust, reviews and effects.
- `people`: optional public-search adapter, evidence and committed budgets.
- `notifications`: persistent inbox and provider delivery contracts.
- `sync`: cursors, snapshot replacement, tombstones and offline operation reconciliation.
- `workers`: Celery tasks, schedules, leases and outbox processing.

### Native client

- Flutter 3.47.4 and Dart 3.13.3.
- Riverpod for state and go_router for routing.
- Shared Flutter source for Windows and Android.
- Drift/SQLite client cache using encryption-capable `sqlite3mc`.
- Runtime cipher verification; release startup must refuse ordinary unencrypted SQLite.
- Flutter secure storage/OS facilities hold session secrets and the cache encryption key.
- Cache namespaces separate account, API origin, and demo/live mode.
- Offline operations are idempotent, revision-aware, and bound to the originating account.
- Windows native runner supports protocol links, single-instance forwarding, notifications, opt-in system tray, and opt-in startup behavior.
- Android native integration includes FCM lifecycle hooks but activation is pending.

### Production topology

- One authorized Linux VPS is the baseline; the user's existing OVH VPS is the current candidate.
- No domain or subdomain has been purchased/configured yet.
- Only Caddy exposes ports 80/443.
- PostgreSQL and Redis remain internal and are never published to the internet.
- API, worker, scheduler, and dispatcher share the reviewed backend image.
- Separate database roles are used for migrations and runtime.
- A single VPS is not high availability.
- Off-server encrypted backups and a tested clean restore are required before relying on production.

## 8. Security invariants

Do not weaken these controls to make local debugging easier:

- Production requires HTTPS and forbids `DEMO_MODE`.
- Local demo binds API only to `127.0.0.1:8000`.
- PostgreSQL and Redis have no host-published ports in local Compose.
- Google/OAuth/provider secrets exist only on the backend, never in Dart defines or client binaries.
- App sessions store opaque token hashes; provider tokens use separate Fernet encryption.
- OAuth validates issuer, audience, expiry, state, nonce, PKCE, device ownership, and one-time redemption.
- Owner enrollment is restricted to the configured email/Google subject.
- API errors and startup UI must not expose raw exceptions, callback URLs, request bodies, credentials, or malformed secure-storage input.
- Generated API documentation/OpenAPI endpoints are disabled at runtime.
- Responses use request IDs, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and restrictive referrer policy.
- Application request bodies and authentication attempts are bounded/rate-limited.
- Source fetches reject private, loopback, link-local, metadata, mixed-DNS, downgrade, credential-bearing, oversized, and unsafe redirect targets.
- TLS remains verified against the original hostname while the vetted address is pinned.
- External HTML/email/JD text is evidence, never executable instructions.
- Email automatic effects require independent message identity, status meaning, sender authentication, and employer association. Ambiguity goes to review.
- Source/provider network calls occur outside long user database locks.
- Save/apply/status/correction commits include idempotency, event history and sync change records atomically.
- Backups must not put plaintext dumps or passwords in process arguments, repositories, logs, or unprotected files.
- Native sign-out clears sensitive device state/pending operations while preserving authorized server history.
- Release artifacts must be signed and checksum-verified through a trusted channel before production installation.

The completed security review is not a zero-vulnerability guarantee or penetration test. Keep dependency audits and residual risks visible.

## 9. What has already been implemented

The repository is not a scaffold. It includes:

- Modular FastAPI backend and versioned `/api/v1` surface.
- PostgreSQL schema, migrations and history downgrade guard.
- Owner/session/device authentication contracts.
- Evidence model and deterministic eligibility/relevance engine.
- A 60-case synthetic labeled corpus with regression/held-out grouping.
- ATS/direct/Workday/USAJOBS boundaries and retained real source examples.
- DNS-pinned SafeHTTP/SSRF protections.
- Job ingestion, immutable snapshots, canonical identity/dedupe, permanent tombstones, source run metrics, retries and bounded coverage.
- Employer entity/evidence administration boundaries.
- Daily report selection, salary bands, 50/2 caps, shared 32-day cycles and priority delivery.
- Save/unsave, Apply-open versus explicit Applied, manual applications, status events and corrections.
- Persistent notifications/inbox and exact routing contracts.
- Gmail read-only connection/sync/review/correction architecture.
- Optional People search/evidence/query-budget architecture.
- Cross-device sync, snapshots, tombstones, offline queue and conflict handling.
- Celery work, Beat schedules, WorkItem/outbox dispatcher and recovery logic.
- Flutter Windows/Android UI with exact navigation and feature screens.
- Encrypted local cache and secure-storage boundaries.
- Windows tray/startup/protocol/single-instance native code.
- Android FCM hooks and release-hardening configuration.
- Local and production Compose, Caddy configuration, backup/restore tools, CI, runbooks, `requirements.txt`, `Readme.txt`, lockfiles and continuation documents.

## 10. Published Git and CI state

The published remote branch and local checkpoint were independently matched at:

`35338e6f3fad8256a14d41fab3c5c9aac09749d2`

The remote repository's HEAD currently points to `feature/personal-staffer-core`. Do not force-push. Prefer a new local working branch such as `debug/windows-desktop`.

GitHub Actions run `34701723350` was triggered by the published checkpoint. Observed job results:

| Job | Result | Evidence |
|---|---|---|
| Backend | Success | Real PostgreSQL 17 and Redis services; frozen dependencies; Ruff; explicit Alembic migration; full pytest; fixture replay; HTTP demo smoke; logical dump and clean restore comparison; artifact upload. |
| Flutter on Ubuntu | Success | Locked dependency restore, analyzer, and Flutter tests. |
| Flutter on Windows | Success | Locked dependency restore, analyzer, 20 tests, Windows release compilation, and artifact upload. |
| Android debug CI | Failure | APK compile step failed and no artifact uploaded. Android investigation is deferred until desktop-first acceptance, but the failure must remain documented. |

The Windows CI artifact is named `personal-staffer-windows-unsigned` and was reported as 14,921,029 compressed bytes. It is an unsigned raw release directory, not a signed installer and not physical-device acceptance.

Earlier Android release compilation produced an unsigned artifact using a placeholder backend:

- Artifact: `Personal-Staffer-0.1.0-unsigned.apk`
- Size: 62,268,066 bytes
- SHA-256: `823f076beefd0f80b33e6bed35c070eefda4dbff30539c3306ee0b64fe5655dd`
- Three ABIs were present.
- It is not production-configured, signed, or device-accepted.

## 11. Executed test evidence before the latest CI

Two structured backend loops were recorded. Each ran 79 commands including lock validation, Ruff, formatting, compileall, complete pytest, policy replay, offline migration rendering, and 72 fresh-process module imports.

- Backend loop 1: 401 passed, 51 PostgreSQL tests explicitly skipped.
- Backend loop 2: 401 passed, 51 PostgreSQL tests explicitly skipped; script formatting/shebang issues were corrected and gates rerun.
- Final backend security regression: 404 passed, 51 PostgreSQL skips, 3 upstream deprecation warnings.
- Native loop 1: analyzer clean, 20 tests passed.
- Native loop 2: analyzer clean, 20 tests passed.
- Runtime dependency audit: 60 pinned runtime packages, zero known advisories returned at scan time. This does not prove zero vulnerabilities.
- Focused security review: 82 tests passed.
- Safe Uvicorn smoke without local PostgreSQL: live 200, version 200, private jobs 401, ready 503 as designed.

The 51 PostgreSQL tests were not counted as passes locally. The later GitHub Actions backend job is separate evidence that the real PostgreSQL/Redis workflow, migrations, complete suite, demo smoke, and clean restore comparison succeeded.

## 12. Current cloud-workspace changes that are not yet on GitHub

At the time this handoff was created, the cloud workspace remained on published commit `35338e6` but contained an uncommitted desktop-first draft. A fresh local clone will not contain these changes unless they are subsequently committed and pushed.

Modified draft files:

- `README.md`
- `Readme.txt`
- `deployment/compose.local.yml`
- `docs/BUILD_STATUS.md`
- `docs/CONTINUATION.md`
- `docs/TEST_RESULTS.md`
- `docs/WINDOWS_SETUP.md`

New draft files:

- `scripts/check_desktop_prerequisites.ps1`
- `scripts/start_desktop_demo.ps1`
- `scripts/stop_desktop_demo.ps1`

Intended behavior of the draft:

- Allow `deployment/compose.local.yml` to select an ignored `.env.demo` using `STAFFER_ENV_FILE`, while ordinary operation continues using `.env`.
- Provide a read-only Windows prerequisite report for Git, Docker, running Docker engine, exact Flutter 3.47.4, and Visual Studio C++ tools.
- Generate `.env.demo` from `.env.example` with `APP_ENV=local`, `DEMO_MODE=true`, and blank owner identity fields.
- Never modify or reuse `.env`.
- Build and start PostgreSQL/Redis, apply migrations explicitly, start API/worker/scheduler/dispatcher, seed synthetic demo records, wait for readiness, and launch Flutter Windows with matching demo defines.
- Provide a stop command that preserves the isolated PostgreSQL volume.
- Update documentation with the real GitHub push/CI state and desktop-first next action.

Cloud verification of this draft ran twice. Each pass completed:

- Git diff validation.
- README/Readme synchronization.
- `.env.demo` ignore check.
- Compose YAML/configuration assertions.
- Static demo isolation/safety assertions.
- Full locally runnable backend suite: **404 passed, 51 PostgreSQL skips, 3 warnings**.
- Live HTTP checks: live/version 200, ready 503 without local database services, private jobs 401, OpenAPI 404.

These were Linux/static support checks. PowerShell execution and Windows UI behavior are not verified. Claude Code should recreate or obtain these draft changes, review them rather than blindly trusting them, execute them on Windows, correct issues, then commit them on `debug/windows-desktop`.

## 13. Immediate desktop-first plan

### Phase A — Establish a safe Windows development environment

1. Confirm the repository is clean or preserve any user changes.
2. Fetch `origin` and verify commit `35338e6`.
3. Create `debug/windows-desktop`; do not force-push.
4. Confirm the actual Windows version.
5. Check Git, PowerShell, disk space, Docker Desktop/WSL2, Flutter 3.47.4/Dart 3.13.3, Visual Studio Desktop development with C++, Windows SDK, CMake, Ninja, and Inno Setup 6 for later packaging.
6. Run `flutter doctor -v`.
7. Ask before administrator-level installation or system configuration.

### Phase B — Start an isolated synthetic desktop demo

1. Use an ignored `.env.demo`; do not touch a real `.env`.
2. Require `APP_ENV=local` and `DEMO_MODE=true`.
3. Build the backend development image.
4. Start PostgreSQL and Redis.
5. Run `alembic upgrade head` explicitly once.
6. Start API, worker, scheduler, and dispatcher.
7. Run `python -m app.cli demo-seed`.
8. Verify:
   - `/api/v1/health/live` → 200.
   - `/api/v1/health/ready` → 200 after services are ready.
   - `/api/v1/version` → 200 and `demo_mode=true`.
   - Protected endpoints reject unauthenticated requests.
   - `/openapi.json` and `/docs` remain unavailable if current runtime policy requires that.
9. In `client/`, run:

```powershell
$env:CI = 'true'
flutter --suppress-analytics pub get --enforce-lockfile
flutter --suppress-analytics analyze
flutter --suppress-analytics test
flutter --suppress-analytics run -d windows --dart-define=API_BASE_URL=http://127.0.0.1:8000 --dart-define=DEMO_MODE=true
```

### Phase C — Physical Windows product debugging

Exercise and record every major node:

- Application startup and synthetic demo sign-in.
- Notifications, Homepage, People, Saved Jobs, and Applied Jobs navigation/order.
- Homepage tabs/feed states and Priority synthetic jobs.
- Job details, policy evidence, source/original links, save/unsave.
- Apply link opens without falsely marking Applied.
- Explicit Applied action and accidental-Applied correction/undo.
- Manual application entry, details, events, corrections, and permanent history.
- Notifications inbox, unread count, exact notification routing.
- Reports, source runs, email review placeholders, settings, profile and watchlist.
- Loading, empty, error, partial-coverage, offline, reconnect, pending and conflict states.
- Encrypted cache reopen, wrong-key behavior, secure key retrieval and sign-out cleanup.
- Window resize, small layout, large fonts, keyboard traversal and screen-reader labels.
- Protocol activation, single-instance forwarding, notification/toast activation.
- Tray off/on, close-to-tray, tray Open/Exit, startup off/on, reboot/sign-in behavior.
- No raw errors, secrets, tokens, callback data, or synthetic/real-state ambiguity in UI.

### Phase D — Two complete desktop verification loops

After the first complete working build, perform two independent loops. Each must include:

1. Frozen dependency/lock validation.
2. Backend Ruff and formatting.
3. Clean PostgreSQL database and Alembic upgrade.
4. Complete backend pytest with `TEST_DATABASE_URL` and no hidden skips.
5. Redis/worker/outbox behavior and demo HTTP smoke.
6. Flutter dependency restore, analyzer and full test suite.
7. Windows debug build and release build.
8. Windows encrypted-storage integration test.
9. Major UI/navigation smoke on the real laptop.
10. Secret scan, artifact inspection and `git diff --check`.

If a check fails, fix it, add regression coverage, and restart that verification loop. Retain prior evidence; do not overwrite history to make the record look green.

### Phase E — Windows installer acceptance

1. Use the existing `client/tool/build_windows.ps1` and Inno Setup configuration.
2. Package the complete release directory including app-local Visual C++ runtime DLLs.
3. Keep it visibly unsigned unless a legitimate protected signing identity exists.
4. Record SHA-256 for executable/package.
5. Test install, launch, protocol registration, upgrade over the installed version, close/restart, and uninstall.
6. Verify uninstall removes binaries/protocol/startup entries without pretending server history is deleted.
7. Do not commit EXE/build output.

### Phase F — Only after Windows acceptance

1. Diagnose and fix the GitHub Android CI failure.
2. Configure a legitimate backend HTTPS origin and protected Android signing identity.
3. Configure FCM if push notifications are being accepted.
4. Build, install and test on the Samsung Galaxy S25 Ultra.
5. Test cross-device/offline/reconnect/notification behavior between Windows and Samsung.

### Phase G — Live integrations and production activation

1. Inventory the authorized OVH VPS: CPU, RAM, disk, OS, ports, existing services and backup capacity.
2. Obtain/configure a domain or approved HTTPS endpoint. None exists yet.
3. Configure the sole allowed Google owner and OAuth callbacks securely.
4. Have the user complete Google sign-in/Gmail read-only consent in the system browser.
5. Activate at least one real official/ATS source and audited legal-employer/E-Verify evidence.
6. Run a real source-to-database pipeline and inspect accepted/withheld evidence.
7. Conduct a multi-day search/report pilot without weakening gates.
8. Select a People provider only after a result/terms/cost pilot; retain budgets.
9. Configure off-server encrypted backups and complete a real clean restore drill.
10. Deploy only after explicit authorization and preserve the current security topology.

## 14. Genuine blockers and unfinished gates

These are not excuses to remove scope or fabricate completion:

- Physical Windows launch, secure storage, tray/startup, toast/protocol, installation and accessibility acceptance.
- Google OAuth project/client values and actual owner consent.
- Gmail read-only authorization and lifecycle/reconnect checks.
- No domain/subdomain or deployed HTTPS backend yet.
- Authorized OVH inventory/deployment work has not occurred.
- No real matched legal-employer/E-Verify evidence is currently sufficient for production delivery.
- Production DNS-pinned source transport was unavailable in the cloud build environment.
- Real source-to-PostgreSQL delivery and multi-day coverage pilot remain.
- People provider/key and result/terms/cost pilot remain.
- USAJOBS key is optional and unconfigured.
- FCM and Samsung lifecycle remain.
- Protected signing identities for Windows/Android remain.
- Off-server restic destination and independently protected encryption key remain.
- A real encrypted backup/restore drill remains outside the CI logical restore comparison.
- JobSpy 1.1.82 is blocked because its required `markdownify 0.13.1` is affected by CVE-2025-46656 and its version constraint excludes patched 0.14.1. Keep `JOBSPY_ENABLED=false` until a compatible reviewed upstream release is qualified.

## 15. Honest interpretation of “working” and “complete”

Current code is a meaningful implementation checkpoint and has strong automated coverage. It is not an accepted production release.

The first usable increment is M3: a real Windows workflow running against PostgreSQL/Redis with synthetic demo data, then installed and physically accepted. That still does not complete Gmail, real-source evidence, Android, deployment, backups, signing, or the multi-day pilot.

Never claim:

- “50 jobs every day” — fewer may legitimately qualify.
- “All startups/ATS sites covered” — source access and schemas vary.
- “E-Verify confirmed” without current matched legal-entity proof.
- “Ten people found” — People results are optional and may be fewer.
- “Gmail knows every status” — portal-only changes may not produce email.
- “Zero vulnerabilities” — audits have coverage limits.
- “Device tested” based only on CI compilation.
- “Production ready” for an unsigned artifact or placeholder backend.

## 16. Git, artifacts and documentation rules

- Inspect before editing and preserve user changes.
- Work on `debug/windows-desktop` for local desktop debugging.
- Do not force-push, rewrite published history, or merge without explicit authorization.
- Never commit `.env`, `.env.demo`, `.env.production`, `.secrets`, tokens, credentials, keys, databases, dumps, Flutter `build/`, APKs, EXEs, installers, or provider payloads containing unnecessary personal data.
- Commit coherent changes only after relevant tests.
- Keep `README.md` and `Readme.txt` synchronized.
- Keep `requirements.txt`, `backend/requirements-dev.txt`, `pyproject.toml`, `uv.lock`, `pubspec.yaml`, and `pubspec.lock` consistent with actual dependency changes.
- Update `docs/BUILD_STATUS.md`, `docs/TEST_RESULTS.md`, `docs/KNOWN_LIMITATIONS.md`, and `docs/CONTINUATION.md` after each meaningful checkpoint.
- Record exact commands, pass/fail counts, skips, artifacts, checksums, platform and genuine blockers.
- Never erase old failed evidence or reinterpret a prepared workflow as executed.

## 17. First commands for local Claude Code

From PowerShell:

```powershell
git clone https://github.com/msaiabhinav/Personal-Staffer.git
cd Personal-Staffer
git fetch origin
git switch feature/personal-staffer-core
git pull --ff-only
git rev-parse HEAD
git status --short --branch
git switch -c debug/windows-desktop
```

The expected starting commit is:

```text
35338e6f3fad8256a14d41fab3c5c9aac09749d2
```

Then begin by reading the canonical documents and inspecting prerequisites. If this handoff file is supplied separately rather than present in the cloned repository, copy it into the repository only after confirming it does not overwrite another file.

## 18. Completion/reporting format for Claude Code

At each checkpoint report:

- Active branch and commit.
- Files changed and why.
- Exact commands executed.
- Tests passed, failed and skipped.
- App screens/nodes physically exercised.
- Security checks rerun.
- Artifact names, sizes, signatures and SHA-256 values.
- What is implemented versus automated-test verified versus live-source verified versus device verified versus not configured versus blocked.
- The next executable step.

Continue independent work until a genuine user action is required. The immediate next objective is not another architecture proposal: it is a safely running Windows desktop demo, followed by node-by-node product debugging and two complete verification loops.
