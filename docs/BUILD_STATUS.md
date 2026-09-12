# Personal Staffer build checkpoint

Date: 2026-09-12. Branch: `feature/personal-staffer-core`. Origin: `https://github.com/msaiabhinav/Personal-Staffer.git` (publicly readable, empty when inspected). This is a substantial source-code build checkpoint; **the full product has not passed release acceptance**. No remote push or production deployment has occurred.

## Evidence states

| State | What is established |
|---|---|
| Implemented | Modular FastAPI/PostgreSQL backend, 49-table schema and three migrations; evidence rules; ATS adapters; reports/priority/cycles; durable work/outbox; application snapshots/corrections; OAuth/Gmail/People domains; Flutter Windows/Android client; deployment/backup/install scripts. Specialized-directory coverage and JobSpy activation remain partial. |
| Automated-test verified | Two assembled backend debugging passes: each 401 passed, 51 PostgreSQL tests explicitly skipped. Both passed all 72 isolated module imports and synthetic corpus replay. Lint/format findings corrected; final gates pass. Native preflight: 19 tests and analyzer pass; two final native passes are being recorded. |
| Live-source verified | Bounded public access experiment on 30 employers plus E-Verify; 11 complete ATS job payloads retained and normalized, with additional Lever/Workday/SmartRecruiters access observations. This proves observed source shape only. No live source-to-PostgreSQL delivery is verified. |
| Device verified | None. Windows install/toast/startup/key storage and Samsung install/FCM/sync checks need real platforms. Android release compilation is underway; compilation does not establish device acceptance. |
| Not configured | Allowed Google owner and OAuth client/grant; FCM; People provider key; optional USAJOBS; deployment endpoint/VPS; off-server restic destination; signing identity. |
| Blocked | Local PostgreSQL/Redis execution and Docker are unavailable in this environment. Production DNS-pinned source fetch cannot resolve public DNS here. E-Verify public endpoints returned access errors. Windows build requires a Windows host; Samsung requires the device. |

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
| M7 Android/sync | Shared native screens, encrypted cache, account-bound pending operations, resnapshot/tombstones and FCM hooks implemented. | Final build outcome, Samsung install and cross-device/offline/notification acceptance. |
| M8 operations | Pinned dependencies/images/actions, security fixes, production roles/TLS topology, backup/restore tools, CI, requirements.txt/Readme.txt and continuation docs supplied. | Real containers/deployment, off-server encrypted restore, signatures and update/uninstall acceptance. |

## Debugging and security checkpoint

The first assembled native build attempt preceded the two structured verification passes. All backend subsystems are covered by the combined test suite and separate fresh-process imports. Pass 1 found an operations-script formatting inconsistency; pass 2 found inconsistent root/backend formatting and a missing executable-script shebang. These were corrected and the failing gates rerun successfully. Earlier integration fixes include an import cycle, network calls holding database locks, first-view revision races, offline projection invalidation, OAuth proxy authority handling, unsafe backup target/TLS handling and untrusted email status effects.

Runtime dependency audit: 60 pinned packages, zero known advisories returned at scan time. This is not a zero-vulnerability guarantee. A real Uvicorn HTTP smoke returned live=200, version=200, unauthenticated jobs=401 and ready=503 while PostgreSQL is unavailable.

See REQUIREMENTS.md for all PR-01–PR-25 and AT-01–AT-60 mappings, TEST_RESULTS.md for commands/logs, SECURITY_REVIEW.md for fixed findings, and CONTINUATION.md for exact next work. All externally blocked and unfinished release gates remain in scope.
