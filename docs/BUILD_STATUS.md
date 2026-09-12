# Personal Staffer build checkpoint

## Windows desktop-debug checkpoint — 12 September 2026

Branch `debug/windows-desktop` (from published `35338e6`), **pushed to origin on 12 September 2026**; GitHub Actions run [34713669791](https://github.com/msaiabhinav/Personal-Staffer/actions/runs/34713669791): backend, Flutter Ubuntu and Flutter Windows succeeded; the Android debug-APK compile step failed as before (deferred; its log needs repository admin rights to download anonymously). Executed on the target Asus Vivobook Pro 15 (Windows 11 Home 26200). Milestone M3 is **in progress**: the Windows workflow runs on the device against real PostgreSQL/Redis with synthetic data and the installer round-trips; physical acceptance of tray/startup/toast/accessibility and the second verification loop remain before M3 is declared accepted. Owner product decisions (Watchlist as a sixth destination, light/dark appearance, browser-style history, local API port 5555) are recorded in ADR 0002.

| State | Change at this checkpoint |
|---|---|
| Implemented | Isolated demo tooling: `scripts/check_desktop_prerequisites.ps1`, `scripts/start_desktop_demo.ps1`, `scripts/stop_desktop_demo.ps1`; `deployment/compose.local.yml` selects an ignored `.env.demo` through `STAFFER_ENV_FILE` and mounts `scripts/`/.env.example read-only into the local `api` service. Settings policy constants accept dotenv strings while still refusing any value other than 32/72. |
| Automated-test verified | On real PostgreSQL 17.11 and Redis 7.4.6 in Docker Desktop: **459 passed, 0 skipped** (3 upstream deprecation warnings). Every formerly skipped PostgreSQL test executed. CI-equivalent Ruff lint/format clean. Policy replay 60/60. Demo HTTP smoke on PostgreSQL passed. Flutter 3.47.4 analyzer clean and 20 tests passed on Windows. |
| Live-source verified | First real source-to-PostgreSQL run on the laptop via the production SafeHTTP client: Oscar Health Greenhouse board (288 postings) and Analog Devices Workday, all withheld pending E-Verify/opening evidence as policy requires. No reviewed legal-employer evidence yet, so no real job has been delivered. |
| Device verified | On the target laptop: Windows debug and release builds; the app launched and used in DEMO_MODE (all six destinations, job detail, save/unsave, watchlist, appearance, Back/Forward); AT-55 encrypted-storage integration test passed on the device; protocol-link forwarding to the running instance; release HTTPS guard; unsigned Inno Setup installer built, installed, upgraded over itself, uninstalled cleanly (`verification/windows-installer.json`). **Not yet physically accepted:** tray/close-to-tray/startup, toast click activation, keyboard/screen-reader review, offline-reconnect. |
| Not configured | Unchanged (Google owner/OAuth, FCM, People, USAJOBS, deployment endpoint, backups, signing). Inno Setup 6 not installed. |
| Blocked | Nothing blocks local desktop work now (Developer Mode, VS Build Tools + ATL and Inno Setup are installed). A working *installed* app needs an HTTPS backend origin because release builds refuse plain HTTP by design. Google sign-in is configured and verified on the laptop in live-local mode (12 September 2026); Gmail consent not yet exercised. |

Defects corrected here (regression tests added): dotenv `Literal` policy constants broke the documented startup; in-container pytest could not collect root-script tests; version-endpoint test assumed non-demo environment. See TEST_RESULTS.md.


Date: 2026-09-12. Branch: `feature/personal-staffer-core`. Origin: `https://github.com/msaiabhinav/Personal-Staffer.git` (publicly readable, empty when inspected). This is a substantial source-code build checkpoint; **the full product has not passed release acceptance**. Implementation checkpoint: `a852668e07ad85ddbd883e2a1c7e99334ef97473`. No remote push or production deployment has occurred.

## Evidence states

| State | What is established |
|---|---|
| Implemented | Modular FastAPI/PostgreSQL backend, 49-table schema and three migrations; evidence rules; ATS adapters; reports/priority/cycles; durable work/outbox; application snapshots/corrections; OAuth/Gmail/People domains; Flutter Windows/Android client; deployment/backup/install scripts. Specialized-directory coverage remains partial. Optional JobSpy package/interface qualification succeeded, but its pinned markdownify dependency has an upstream vulnerability and activation is blocked. |
| Automated-test verified | Two assembled backend debugging passes: each 401 passed, 51 PostgreSQL tests explicitly skipped. Both passed all 72 isolated module imports and synthetic corpus replay. Lint/format findings corrected; final gates pass. The final security-guard regression run passed 404 tests with 51 PostgreSQL skips. Both final native passes: analyzer clean and 20 tests passed, including startup secret redaction. |
| Live-source verified | Bounded public access experiment on 30 employers plus E-Verify; 11 complete ATS job payloads retained and normalized, with additional Lever/Workday/SmartRecruiters access observations. This proves observed source shape only. No live source-to-PostgreSQL delivery is verified. |
| Device verified | None. Windows install/toast/startup/key storage and Samsung install/FCM/sync checks need real platforms. Final Android release compilation succeeded for three ABIs. The APK is unsigned with a placeholder HTTPS backend; it is not install-ready and does not establish device acceptance. |
| Not configured | Allowed Google owner and OAuth client/grant; FCM; People provider key; optional USAJOBS; deployment endpoint/VPS; off-server restic destination; signing identity. |
| Blocked | Local PostgreSQL/Redis execution and Docker are unavailable in this environment. Production DNS-pinned source fetch cannot resolve public DNS here. E-Verify public endpoints returned access errors. JobSpy activation is BLOCKED_SECURITY pending a compatible patched dependency. Windows build requires a Windows host; Samsung requires the device. |

## Milestones and exit gates

| Milestone | Implementation checkpoint | Exit evidence still required |
|---|---|---|
| M0 foundations | Specification read fully, local branch and locks created, bounded 30-employer source matrix, early native workflow and platform toolchains investigated. Ashby/Greenhouse selected for retained field quality. | Authorized deployment inventory; actual provider/Windows integration checks. |
| M1 evidence core | Versioned evidence/rules, migrations, conservative unknown handling, replay CLI and 60 synthetic labeled bundles implemented and tested. | Larger real labeled corpus and PostgreSQL migration execution. |
| M2 real pipeline | Real payload replay, reviewed employer register, safe fetch, conservative identity ledger, short transactions, durable resume and run metrics implemented. | Live source-to-DB result with actual reviewed E-Verify legal-employer evidence. |
| M3 Windows workflow | Exact navigation, feed/details, evidence, save/apply/undo, manual applications, permanent history, inbox and native hooks implemented. | Windows compilation/installation and complete persistent API workflow on real PostgreSQL. This milestone is not declared accepted. |
| M4 daily/priority | ATS adapters, registry, report salary order/caps, shared cycles, priority pools, schedules and source health implemented. | Multi-day coverage pilot, database concurrency execution, specialized/JobSpy qualification. |
| M5 Gmail | Read-only consent flow, bounded page sync, trusted sender checks, matching/review/correction and reconnect states implemented. | Actual owner consent, provider smoke and database effects/lifecycle checks. |
| M6 People | Optional public search adapter, retained relationship evidence, alphabetical groups, committed request budget and UI implemented. | Key-enabled result/terms/cost pilot; provider selection remains conditional. |
| M7 Android/sync | Shared native screens, encrypted cache, account-bound pending operations, resnapshot/tombstones and FCM hooks implemented. | Signed/configured APK, Samsung install and cross-device/offline/notification acceptance. |
| M8 operations | Pinned dependencies/images/actions, security fixes, production roles/TLS topology, backup/restore tools, CI, requirements.txt/Readme.txt and continuation docs supplied. | Real containers/deployment, off-server encrypted restore, signatures and update/uninstall acceptance. |

## Debugging and security checkpoint

The first assembled native build attempt preceded the two structured verification passes. All backend subsystems are covered by the combined test suite and separate fresh-process imports. Pass 1 found an operations-script formatting inconsistency; pass 2 found inconsistent root/backend formatting and a missing executable-script shebang. These were corrected and the failing gates rerun successfully. Earlier integration fixes include an import cycle, network calls holding database locks, first-view revision races, offline projection invalidation, OAuth proxy authority handling, unsafe backup target/TLS handling and untrusted email status effects.

Runtime dependency audit: 60 pinned packages, zero known advisories returned at scan time. This is not a zero-vulnerability guarantee. A real Uvicorn HTTP smoke returned live=200, version=200, unauthenticated jobs=401 and ready=503 while PostgreSQL is unavailable.

See REQUIREMENTS.md for all PR-01–PR-25 and AT-01–AT-60 mappings, TEST_RESULTS.md for commands/logs, SECURITY_REVIEW.md for fixed findings, and CONTINUATION.md for exact next work. All externally blocked and unfinished release gates remain in scope.
