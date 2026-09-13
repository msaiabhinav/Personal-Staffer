# Continue this checkpoint

## Windows desktop-debug state (12 September 2026)

Branch `debug/windows-desktop` from `35338e6`; latest checkpoint commit is recorded in BUILD_STATUS.md. The isolated demo backend runs on the target laptop (`scripts\start_desktop_demo.ps1 -BackendOnly`); the complete backend suite executed on real PostgreSQL/Redis with zero skips; Flutter 3.47.4 analyzer and 20 tests pass on Windows.

Next executable action, in order:

1. Done: two complete verification loops passed; branch pushed; CI green except the deferred Android job.
2. Owner: remaining physical checks - tray Open/Exit from the hidden-icons flyout, startup behaviour after sign-in, toast click (turn Windows Do Not Disturb off first), 150 % text size, a Pending save during an API outage and its reconnect. Record outcomes in TEST_RESULTS.md.
3. Watch for the intermittent blank window surface; `e45f10f` forces a frame on show/activate as a first mitigation. If it recurs, capture the `flutter run` log and consider the Skia backend.
4. Done: Google sign-in works in live-local mode; nine real sources registered and scanning; E-Verify informational (ADR 0003). Next: owner connects Gmail (Settings > Gmail connection); watch the first daily report at 11:00 America/New_York; review withheld counts per source in Settings > Source health and Search run history; consider more boards with analyst-family roles.
5. Then the HTTPS deployment phase (Phase G) so the installed release build can be used day-to-day.
5. Then Phase F: diagnose the Android CI compile failure (log requires repository access) before any Samsung work.

## First executable steps

1. On a normal Docker-capable host, copy .env.example to .env, build local Compose, start postgres/redis, apply migrations exactly once, then start API/worker/scheduler/dispatcher. Commands are in README.md and Readme.txt. Migrations are not automatic.
2. Use a disposable PostgreSQL database and TEST_DATABASE_URL to execute all currently skipped tests. The actual migrations are part of test fixtures. Run the explicit local demo HTTP smoke and clean restore comparison. Investigate failures; do not label the prepared CI as already executed.
3. Build and install Windows using the documented Flutter/Visual Studio/Inno Setup commands. Verify protocol/toast activation, tray/opt-in startup, encrypted key recovery and Saved/Applied persistence before accepting M3.
4. Configure one real direct/ATS source and import actual reviewed legal-employer/E-Verify evidence. Run-search, inspect withheld/evidence results, build one constrained report, then conduct the multi-day pilot. A retained real payload or a candidate pool flag is not employer proof.
5. Configure secure backend domain/Google OAuth and allowed owner, then ask the user to complete Google consent in the system browser. Gmail needs their consent later, never their password in chat. Continue manual tracking if consent/provider is unavailable.
6. Activate FCM and test Samsung plus Windows sync/offline/reconnect/notification lifecycle. Supply a legitimate public-search key only after the provider's result/terms pilot; retain request budgets and uncertainty labels.
7. Qualify specialized directory discovery. JobSpy 1.1.82 is pinned and interface-tested but its upstream markdownify constraint excludes the CVE-2025-46656 fix; wait for a compatible reviewed upstream release and rerun package/security qualification before enabling it. Keep LinkedIn job scraping disabled. Expand real labeled cases toward the specification's corpus/pilot targets.
8. Deploy only to an authorized host; configure off-server encrypted backups, run an actual restore drill, then qualify signed installer/APK updates. No paid service or hosting has been purchased.

## Code and commands

- backend/app has separate auth, API, evidence, connectors, jobs, reports, applications, email, People, notifications, sync and worker modules.
- client has real Flutter Windows/Android hosts, encrypted cache, platform bridges and feature screens.
- `python scripts/verify_backend.py --pass-number 1` and `--pass-number 2` reproduce backend loops; existing evidence should be preserved before rerunning.
- `scripts/export-requirements.sh` exports hashed production/dev requirements and synchronizes Readme.txt from README.md.
- Follow client/tool verification/build scripts and platform runbooks. Never treat a release compile as physical-device verification.
- Backups: scripts/backup.py requires restic with --stdin-from-command and explicit isolated restore target; scripts/check_restore.py streams logical state hashes with writers stopped.

## Do not regress

Unknown proof withholds recommendations. Keep 72 hours, exact-four-year semantics, 50/2 caps, common 32-day cycles, permanent no-repeat identities, quota-independent priority and pinned saved/applied evidence. Never promote first_seen/updated_at or synthetic fixture proof to production eligibility. Keep network calls outside user locks, durable work/outbox recovery, account-bound offline queues and correction conflicts. Source text and email content cannot become instructions. Shared ATS emails first need user review; no inferred sender authority. No automatic applications or message sending.

## Genuine dependencies

PostgreSQL/Redis and real Docker host; Windows build/installation environment and Samsung device; secure allowed Google identity/OAuth grant; actual E-Verify entity proof; endpoint/VPS and backup destination; FCM; optional People/USAJOBS keys; signing identity. Missing inputs do not excuse fabricating live results or removing scope. This checkpoint still needs release acceptance.
