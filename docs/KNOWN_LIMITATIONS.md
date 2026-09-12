# Known limitations and incomplete release gates

The repository contains a working-code implementation checkpoint, not a production-complete application. Read TEST_RESULTS for exact executed checks.

- PostgreSQL and Redis cannot run in the current restricted Linux runtime; Docker is absent and only UID0 is mapped. No SQLite substitution is used. Database transaction, trigger, concurrency, full API workflow and restore cases must execute on the prepared Compose/CI environment. Passing static SQL rendering is not a migration execution.
- Windows compiler/installation/toast/tray/secure-key behavior and Samsung physical-device behavior remain unverified. Linux Flutter/cache tests cannot establish those results. Android build outcome is separately recorded; compilation alone is not installation testing.
- Allowed Google owner email and OAuth project are not supplied. Gmail needs your read-only consent through Google; no password is collected. FCM and People provider credentials are absent. Unconfigured boundaries stay visible.
- Official E-Verify access probes were blocked. No real legal entity is currently confirmed. An audited manually maintained register can support a pilot, but it does not establish nationwide automated coverage. Real jobs remain withheld unless all gates pass.
- Managed public source probes obtained11 complete ATS payload examples plus additional source access examples. The application's DNS-pinned fetcher cannot resolve public DNS from this runtime. These observations are separate; no verified source-to-PostgreSQL live pipeline is claimed.
- Workday support is experimental; public JavaScript-only portals and specialized sites need tenant-specific qualification. JobSpy 1.1.82 was pinned and imported in an isolated Python 3.12 environment; its required markdownify version has CVE-2025-46656 and cannot resolve the patched version within upstream constraints. Activation is blocked, and no live scraping was performed. Startup/VC sources currently provide link leads, not complete maintained specialized crawlers. USAJOBS needs explicit configuration.
- The60-case labeled policy benchmark is entirely synthetic. Real-source annotations toward250 bundles, measured recall/precision and a multi-day pilot remain required. Neither rejecting everything nor synthetic100% accuracy is a release success.
- No minimum50 daily results or10 People profiles is promised. Verified company pool geography and entity mapping need evidence; candidate tags do not grant either.
- Source rechecks are bounded; source URLs can disappear. Raw cleanup is not automatically activated, to protect pinned evidence and permanent no-repeat identities. Operational backup scheduling, restic target and retention need activation; no high-availability claim is made.
- Container definitions, signatures, install/update/uninstall behavior and restore drill have not been accepted on deployment hardware. No VPS, domain, signing certificate or paid subscription was purchased or deployed.
- Python compatibility deprecation warnings are retained in test output. Advisory scans cannot establish zero vulnerabilities.

No incomplete item is hidden behind fabricated records or a hardcoded live-success state. Local demo mode is explicitly synthetic and refuses nonlocal deployment and mixed real-user data.

## Windows desktop-debug checkpoint (12 September 2026)

- Visual Studio "Desktop development with C++" (MSVC, Windows 10/11 SDK, CMake, Ninja) is not installed on the target laptop; `flutter doctor` fails that category. Installation needs administrator elevation and has not been performed by the agent.
- Windows Developer Mode is off, so unprivileged symlink creation is blocked and `flutter pub get` reports "Building with plugins requires symlink support". Windows builds cannot proceed until it is enabled (Settings → System → For developers) or builds run elevated.
- Docker Desktop 4.85.0 on this laptop crashed at startup with undeletable stale AF_UNIX socket files (`%LOCALAPPDATA%\Docker\run\*`, `%LOCALAPPDATA%\docker-secrets-engine\engine.sock`; Windows error 1920). Workaround applied: the stale directories were renamed aside (`run.stale-20260912`, `run.stale2-20260912`, `docker-secrets-engine.stale-20260912`) and the unrelated "Docker AI" preference was disabled. Fresh sockets were recreated; the problem may recur on the next Docker restart and is outside this repository.
- `generated_plugin_registrant.*`/`generated_plugins.cmake` show EOL-only diffs after `flutter pub get` on a `core.autocrlf=true` checkout; no `.gitattributes` normalization exists yet.
- The OpenAPI document and Swagger UI are served at `/api/v1/openapi.json` and `/api/v1/docs` (tests depend on the former); only the root `/openapi.json` and `/docs` are absent. The handoff's "disabled at runtime" wording overstates this.
- Physical UI, tray, startup, protocol, toast and installer acceptance remain unverified on this host.
