# Verification results — 12 September 2026

This record distinguishes executed behavior from prepared database, provider and device checks. No skipped test is counted as a pass. The user requested two debugging loops after the first assembled build attempt; both backend loops ran, with fixes and relevant gates rerun inside the second loop. Both final native loops also ran successfully and their exact logs are retained.

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

Flutter 3.47.4 / Dart 3.13.3 dependencies are locked. Both final native passes had a clean analyzer and 20 passing tests, covering navigation/tabs, refresh/retry identifiers, first-view/save revision, account races, frozen resnapshots/tombstones, and an actual encrypted SQLite reopen/wrong-key test on Linux. Final Android release compilation succeeded. Exact native loop logs are `verification/native-pass-1.log` and `verification/native-pass-2.log`. The final artifact outcome is recorded below. Windows/Samsung cache-key and lifecycle results remain unverified regardless of Linux tests or Android compilation.

## Prepared gates that have not executed

CI has real PostgreSQL/Redis services, explicit migrations, full suite, HTTP demo smoke with APP_ENV=local/DEMO_MODE=true, logical dump into a clean database and retained-state comparison. Windows runner compiles an unsigned release; Android runner compiles a development APK. Workflow YAML preparation is not a remote CI success. Container execution, actual encrypted restic restore, platform installer/update/uninstall, Google grant renewal, FCM lifecycle, live People result quality and multi-day report coverage remain release gates.


## Final Android artifact

`Personal-Staffer-0.1.0-unsigned.apk`: 62,268,066 bytes; SHA-256 `823f076beefd0f80b33e6bed35c070eefda4dbff30539c3306ee0b64fe5655dd`. Final build exited 0 in 80.7 seconds after the first uncached toolchain build. Actual native application and sqlite3mc libraries exist for arm64-v8a, armeabi-v7a and x86_64.

The artifact uses `https://backend-not-configured.invalid`, FCM disabled and demo mode disabled. It has no signing certificate: apksigner exited 1 with the expected unsigned rejection. It cannot be installed as a private release until configured and signed. Actual APK manifest inspection confirmed cleartext disabled, backup disabled and no debuggable=true flag. Recognized private-key/token patterns produced no matches in scanned ZIP entries; this is a limited pattern scan. Metadata: `verification/android-artifact.json`.

Nonfatal upstream build warnings (Firebase/Kotlin API transition, SDK XML and optional Cupertino icon font lookup) remain documented in ANDROID_SETUP. Windows compilation and actual Samsung/Windows lifecycle tests have not executed.


## Optional JobSpy qualification and security blocker

A separate Python 3.12 environment installed actual python-jobspy 1.1.82; all four allowed-source query argument sets bind to its real scrape_jobs signature. No scraping ran and no default runtime package version changed. The optional group supports Python 3.12 only because upstream pins NumPy 1.26.3.

The optional requirements audit found one unique advisory in markdownify 0.13.1 (two duplicate entries in the audit response): [CVE-2025-46656 / GHSA-7mpr-5m44-h73r](https://github.com/advisories/GHSA-7mpr-5m44-h73r). The patched version is 0.14.1; JobSpy requires a version below 0.14.0. No dependency constraint or advisory was suppressed. Optional activation remains BLOCKED_SECURITY and the production/default dependency set remains unchanged. Qualification/audit evidence is retained in `verification/jobspy-package-qualification.json` and `verification/jobspy-pip-audit.json`. Runtime refusal has dedicated regression coverage in the final backend test run.


Final regression after the optional JobSpy security guard: **404 passed, 51 PostgreSQL tests skipped, three upstream deprecation warnings**, 4.32 seconds. Three additional tests prove known-vulnerable/unqualified/missing-package behavior without invoking the source runner. Frozen-lock, full lint and formatting checks passed; existing default dependency versions and exported requirements stayed unchanged. Evidence: `verification/backend-final-tests.log` and `verification/backend-final-tests.xml`.


## Windows desktop-debug checkpoint — 12 September 2026 (branch `debug/windows-desktop`)

First execution on the target Asus Vivobook Pro 15 (Windows 11 Home 26200, 24 GB RAM). Docker Desktop 4.85.0 / engine 29.6.2 (WSL 2), Compose v5.3.1, Git 2.53.0, Flutter 3.47.4 / Dart 3.13.3 installed at `C:\Users\crick\dev\flutter` (official archive, SHA-256 `31173300481bd06e377fd55ee84214689648b1817563efd7b450b7b78bdf351a` verified against the release manifest).

| Check | Command (repo root unless noted) | Result |
|---|---|---|
| Prerequisite report | `scripts\check_desktop_prerequisites.ps1` | Exit 1 as designed: Visual Studio C++ tooling, Windows SDK, CMake and Ninja absent; Inno Setup absent (WARN). |
| Isolated demo backend | `scripts\start_desktop_demo.ps1 -BackendOnly` | Image built; PostgreSQL 17.11 and Redis 7.4.6 healthy; `alembic upgrade head` explicit; API/worker/scheduler/dispatcher started; `demo-seed` created 2 synthetic priority jobs; live 200, ready 200, version 200 with `demo_mode=true`, `/jobs` and `/notifications` 401, root `/openapi.json` and `/docs` 404. |
| Complete backend suite on real services | `docker compose -p personal-staffer-demo -f deployment/compose.local.yml run --rm --no-deps -e TEST_DATABASE_URL=postgresql+psycopg://staffer:staffer-local@postgres:5432/staffer_test api pytest -ra` | **458 passed, 0 skipped, 25 upstream deprecation warnings**, 26.3 s. Every previously skipped PostgreSQL test executed. Log: `verification/windows-backend-loop-1.log`. |
| Lint / format (CI-equivalent, host ruff 0.16.7 from `backend/`) | `ruff check app tests ../scripts`; `ruff format --check app tests ../scripts` | All checks passed; 111 files formatted. |
| Policy replay | `run --rm api python -m app.cli replay-fixtures` | 48/48 regression, 12/12 held-out, 0 hard-rule false accepts. `verification/windows-replay-fixtures.json`. |
| Demo HTTP smoke on PostgreSQL | `run --rm -e DATABASE_URL=...staffer_test -e APP_ENV=local -e DEMO_MODE=true api python /scripts/smoke_demo.py` | Passed after an explicit `alembic upgrade head` on `staffer_test`. |
| Flutter (client/) | `flutter pub get --enforce-lockfile`; `flutter analyze`; `flutter test` | Lock resolved; analyzer clean; **20 passed** on the Windows host. `pub get` exits 1 only because Windows plugin symlinks need Developer Mode (see limitations). |
| `git diff --check` | | Clean. |

Defects found and corrected on this host (each with a regression test):

1. `Settings.cycle_days`/`max_posting_age_hours` were `Literal[32]`/`Literal[72]`; dotenv supplies strings, so the README's `Copy-Item .env.example .env` path failed at the first `alembic upgrade head`. CI never loaded an env file, which is why it passed. Fixed with bounded ints (any value other than 32/72 still refused); `test_documented_env_example_loads` and `test_policy_constants_accept_env_strings_and_refuse_other_values`.
2. The documented in-container `pytest` command could not collect `test_security_review.py` (and `test_demo_database.py`) because the image's build context excludes `scripts/`. Local Compose now mounts `scripts/` and `.env.example` read-only into `api`.
3. `test_public_health_and_version_report_real_state` assumed the test process was not a demo container; it now pins `DEMO_MODE` for both branches.

Environmental observations, not code defects: Docker Desktop on Windows copies files as mode 0755, so `ruff` inside the image reports EXE002 for every module and a spurious first-party `alembic` import ordering; the CI-equivalent host run is the lint authority. The `demo-seed` path emitted a Pydantic serializer warning (`decision` expected enum, got `str`): `_finalize_evaluation` assigned a bare string to `Evaluation.decision`, bypassing validation. Fixed with the enum member plus `test_finalized_decision_is_enum_and_serializes_without_warnings`; the rerun is **459 passed, 0 skipped, 3 upstream deprecation warnings** (down from 25).

Not executed on this host yet: `flutter build windows` (debug/release), the Windows app itself, encrypted-storage integration test, installer packaging. These wait on the Visual Studio C++ toolchain and Developer Mode (administrator actions).


## Windows desktop checkpoint 2 — first Windows build, Phase C automated nodes, installer (12 September 2026)

Toolchain completed on the laptop: Windows Developer Mode enabled by the owner; Visual Studio 2022 Build Tools 17.14.40 with the C++ workload plus the **VC.ATL** component (required by `flutter_secure_storage_windows` and `flutter_local_notifications_windows`; the first build failed with `C1083 atlbase.h` until it was added); Inno Setup 6 installed per-user. `scripts\check_desktop_prerequisites.ps1` now checks ATL and reports all required items PASS.

| Check | Command (client/ unless noted) | Result |
|---|---|---|
| Windows debug build | `flutter build windows --debug --dart-define=API_BASE_URL=http://127.0.0.1:5555 --dart-define=DEMO_MODE=true` | Built; app launched and signed into the synthetic demo; every primary destination, job detail, save/unsave, watchlist add/remove, theme toggle and Back/Forward exercised on the laptop. |
| Encrypted storage on device (AT-55) | `flutter test integration_test/device_storage_test.dart -d windows --dart-define=API_BASE_URL=http://127.0.0.1:5555` | **All tests passed**: secure-store key round-trip and encrypted SQLite (sqlite3mc) reopen on Windows. Fails by design if an app instance is running (single-instance forwarding absorbs the launch). |
| Windows release build | `flutter build windows --release ...` | Built, 90 s. `personal_staffer.exe` 871,936 bytes; SHA-256 recorded in `verification/windows-installer.json`. Unsigned. |
| Release HTTPS guard | launch Release exe compiled with `http://127.0.0.1:5555` | Shows "Personal Staffer could not start" with the safe message and no raw exception, as designed for release builds. |
| Protocol activation + single instance | run `personal_staffer.exe personalstaffer://jobs/<id>` while an instance runs | Second process exited 0; the running instance logged `navigate raw=personalstaffer://jobs/... route=/jobs/...` (trace captured under `flutter run`, removed afterwards). Launching the integration test with an instance open reproduces the same forwarding. |
| Installer packaging (Phase E) | `tool\build_windows.ps1 -ApiBaseUrl http://127.0.0.1:5555 -Iscc "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"` | Lock, analyzer, 23 tests, release build, app-local `msvcp140/vcruntime140/vcruntime140_1` copy, ISCC compile: `PersonalStaffer-0.1.0-unsigned-setup.exe` 12,486,610 bytes, SHA-256 `5936cf5bb3af9ca46eb835e9d1111e54cd5393eb93b0a575c292e80322da5fe7`, Authenticode status NotSigned. |
| Install / upgrade / uninstall | `/VERYSILENT /NORESTART /SUPPRESSMSGBOXES` | Install exit 0 into `%LOCALAPPDATA%\Programs\Personal Staffer`; `personalstaffer://` registered under HKCU with the installed exe; Start-menu shortcut and per-user uninstall entry present. OS activation `Start-Process personalstaffer://jobs/<id>` launched the installed exe. Upgrade over the existing install exit 0 ("Installation process succeeded", no restart). Uninstall exit 0; install directory, protocol key, `HKCU\Software\PersonalStaffer`, Run entry, Start-menu group and uninstall entry all removed; `%APPDATA%\com.personalstaffer` (encrypted cache/secure store) retained as user data. |
| Verification loop 1 | `scripts\verify_desktop_loop.ps1 -PassNumber 1 -SkipIntegration` | 20 steps: lock, ruff check/format, clean `staffer_loop` database + Alembic, **459 passed, 0 skipped** on PostgreSQL/Redis, replay, demo smoke, live HTTP checks, analyzer, 23 Flutter tests, release build, artifact hashes, secret scan, `git diff --check` all PASS. `windows-debug-build` FAILED with `LNK1168` because the owner's running debug instance locked the executable (environmental); `device-integration` was skipped for the same reason and is **not counted as a pass**. Evidence: `verification/windows-desktop-loop-1.json/.log`. The script now refuses to start while an instance is running. Loop 2 must run with the app closed. |

Defects corrected in this checkpoint (regression-tested unless noted): `GET /jobs?posted_within_hours=72` returned 422 (int Literal query parameter; HTTP test added); `tool\build_windows.ps1` aborted on the redist `v143` alias folder without an `x64` subtree (script fix, exercised by the successful packaging run); initial window now clamped to the monitor work area (runner change, no automated test).

Phase C nodes still requiring the owner's physical action: tray enable/disable and close-to-tray, tray Open/Exit, Windows startup switch and sign-in behaviour, toast click activation, keyboard traversal and screen-reader labels, large-font/small-window review, offline/reconnect by disabling the network. A checklist is in WINDOWS_SETUP.md.

### Complete verification loops (app closed) — 12 September 2026

`scriptserify_desktop_loop.ps1 -PassNumber 1` (evidence `windows-desktop-loop-1-20260912T181816Z.json/.log`) and `-PassNumber 2` (`windows-desktop-loop-2.json/.log`), both at commit `4f53a66`: **20 steps PASS, 0 failed, 0 skipped** in each loop — frozen Flutter lock, Ruff check/format, clean `staffer_loop` database + `alembic upgrade head`, complete backend suite on PostgreSQL 17/Redis 7 (**459 passed, 0 skipped**), policy replay, demo HTTP smoke, live API checks on 127.0.0.1:5555, Flutter analyzer, **23 Flutter tests**, Windows debug and release builds, **on-device encrypted-storage integration test**, release artifact hashes, secret scan, `git diff --check`. The earlier loop-1 record with the environmental debug-build failure is retained unchanged.

### Owner hands-on Phase C results on the laptop (12 September 2026)

| Node | Result | Evidence / follow-up |
|---|---|---|
| Tray enable + close-to-tray | Works: closing the window keeps the process alive; `HKCU\Software\PersonalStaffer\TrayEnabled=1`. The owner initially saw no icon because **Windows 11 places new notification-area icons under the "^ hidden icons" flyout**; UI Automation enumeration of that flyout lists "Personal Staffer — background notifications". | Settings description now says where the icon lives; enabling tray mode shows a one-time balloon from the icon (`flutter_window.cpp`). Owner confirmed the Open/Exit menu from the hidden-icons flyout (12 September 2026). |
| Startup switch | Toggling on writes `HKCU\...\Run\PersonalStaffer = "<exe>" --background` and `StartupEnabled=1`; the owner left it on. | The entry currently points at the debug build in `clientuild`; turn it off before uninstalling dev builds, or enable it from the installed release instead. Sign-in behaviour not yet observed. |
| Keyboard traversal | Owner: Tab works. | Alt+Left/Right verified by widget test; screen-reader names not yet reviewed. |
| Offline / reconnect | Turning Wi-Fi off did **not** show Offline because the demo backend is local (127.0.0.1) and stays reachable — correct behaviour, wrong test. Stopping the API container produced "Offline · cached records" (amber footer), the "Offline · 0 pending changes" strip and a readable cached feed within one 30-second sync cycle (`docs/verification` screenshots not retained; observed live). API restarted afterwards. | Reconnect confirmation and a Pending save during outage still to be observed by the owner. |
| Large text 150 % | Not yet reported. | |
| Toasts | Not testable yet: the owner's Windows session has **Do Not Disturb on**. | Turn DND off before the toast check. |
| Blank window surface | Twice the Flutter view rendered blank (white, then black after a resize) when the window was brought forward from another process after sitting hidden for a long time (once after a forwarded protocol link, once after `ShowWindow` from a script). Not reproduced by minimize/restore under `flutter run`; no engine error logged. Impeller OpenGL backend is in use on this hybrid Intel/NVIDIA laptop. | Open defect; keep an instance running under `flutter run` to capture the engine log when it recurs, then evaluate forcing a redraw on `WM_ACTIVATE`/`WM_SHOWWINDOW` or the Skia backend. |

### First real Google sign-in (live-local mode) — 12 September 2026

The owner created a free Google Cloud project, enabled the Gmail API, configured an External/Testing consent screen with the owner as test user, and created a **Web application** OAuth client with redirect URIs `http://127.0.0.1:5555/api/v1/auth/google/callback` and `/api/v1/gmail/callback`; the values were entered only into the ignored `.env.local`. `scripts\start_desktop_demo.ps1 -Mode live -BackendOnly` generated `TOKEN_ENCRYPTION_KEY` locally, started the separate `personal-staffer-local` stack (fresh database, `demo_mode=false`), and `POST /auth/login/start` returned a Google authorization URL. The Windows app was built without `DEMO_MODE`; the owner completed consent in the browser and the app signed in by redeeming the flow.

Server-side check (no secrets): `users=1` (`msaiabhinav2000@gmail.com`, 21-character Google subject stored), `devices=1`, active `app_sessions=1`, no API errors. Gmail read-only connection (separate consent from Settings) not yet exercised.
