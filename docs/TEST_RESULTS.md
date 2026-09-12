# Verification results — 12 September 2026

This record distinguishes executed behavior from prepared database, provider and device checks. No skipped test is counted as a pass. The user requested two debugging loops after the first assembled build attempt; both backend loops ran, with fixes and relevant gates rerun inside the second loop. Native final loops are being recorded separately.

## Backend debugging loops

From the repository root:

```bash
python scripts/verify_backend.py --pass-number 1
python scripts/verify_backend.py --pass-number 2
```

Each loop executes 79 commands: frozen dependency lock check, lint, formatting, compileall, the complete pytest suite, policy replay, offline migration rendering, and fresh-process imports of every one of the 72 application modules. Command-level JSON and logs are retained in `docs/verification/`.

| Check | Loop 1 | Loop 2 and correction |
|---|---|---|
| Complete pytest suite | 401 passed; 51 skipped; 3 dependency deprecation warnings | 401 passed; 51 skipped; same warnings |
| 72 isolated module imports | Passed | Passed |
| 60-case labeled policy replay | Passed; synthetic only | Passed; synthetic only |
| Lock, bytecode compile, offline migration render | Passed | Passed |
| Lint | Passed | Missing shebang found and fixed; recheck passed |
| Formatting | One new script needed formatting | Root/backend script formatting mismatch fixed with shared configuration; final 111 Python files conform |

The initial loop JSON records retain initial failed exit codes rather than erasing them. `backend-pass-2-corrections.json` records the corrections and successful lint/format/compile rechecks. No behavioral code was hidden behind a disabled check. Fresh-process imports were included because a real eligibility/relevance import cycle had been masked by earlier combined test ordering.

The 51 skipped tests require actual PostgreSQL. They cover migrations/history guards, persistence/ownership, report concurrency, source locks/resume, email effects, work/outbox crash recovery, notifications, sync snapshots and demo workflow. Their fixtures create unique schemas with actual Alembic migrations. Docker/psql are unavailable and this runtime maps only UID0; PostgreSQL root checks were not bypassed and SQLite was not substituted.

## Source, HTTP and security execution

- Actual public probes: 30 employer URLs, E-Verify endpoints and bounded additional source-specific access checks. 11 selected real ATS payloads normalized with provenance. These are not approved jobs or E-Verify confirmations. See SOURCE_CAPABILITIES.md and retained connector fixtures.
- Production SafeHTTP attempt: explicit DNS_UNAVAILABLE in this runtime. Fixed-public-URL managed transport probes are recorded separately; the production SSRF protections were preserved.
- Actual Uvicorn server smoke: `/health/live` 200, `/version` 200, private `/jobs` 401; `/health/ready` 503 because PostgreSQL is absent. Ready also has regression tests refusing missing or stale migration heads. Results: `verification/live-http-smoke.json`.
- Dependency audit executed from backend: `uv run pip-audit -r ../requirements.txt --no-deps --disable-pip --format json --output ../docs/dependency-audit.json --progress-spinner off`. All 60 runtime packages audited; zero known advisories reported. Advisory coverage has limits.
- API/OAuth security, sender/MIME adversarial cases, DNS/redirect/metadata/byte-limit checks, safe secret errors, throttling, backup parameter isolation and correction/idempotency contracts are included in the complete suite. Read SECURITY_REVIEW.md for findings and residual boundaries.
- Three upstream deprecation warnings concern Authlib/Starlette HTTPX compatibility and AnyIO's portal alias. They remain visible; no unqualified major transport swap was made merely to suppress warnings.

## Native build and tests

Flutter 3.47.4 / Dart 3.13.3 dependencies are locked. Preflight analyzer and 19 tests passed, covering navigation/tabs, refresh/retry identifiers, first-view/save revision, account races, frozen resnapshots/tombstones, and an actual encrypted SQLite reopen/wrong-key test on Linux. Android release compilation is underway. Final native loop logs and artifact outcome will be appended here. Windows/Samsung cache-key and lifecycle results remain unverified regardless of Linux tests or Android compilation.

## Prepared gates that have not executed

CI has real PostgreSQL/Redis services, explicit migrations, full suite, HTTP demo smoke with APP_ENV=local/DEMO_MODE=true, logical dump into a clean database and retained-state comparison. Windows runner compiles an unsigned release; Android runner compiles a development APK. Workflow YAML preparation is not a remote CI success. Container execution, actual encrypted restic restore, platform installer/update/uninstall, Google grant renewal, FCM lifecycle, live People result quality and multi-day report coverage remain release gates.
