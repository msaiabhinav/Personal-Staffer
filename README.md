# Personal Staffer

Private native Windows and Android job discovery and application tracking. Flutter clients share a FastAPI/PostgreSQL backend with durable Celery work. This is a substantial implementation checkpoint, **not an accepted production release**. Read `docs/BUILD_STATUS.md`, `docs/TEST_RESULTS.md` and `docs/KNOWN_LIMITATIONS.md` before activation.

No resume, automatic application, LinkedIn job scraping or message sending is included. Jobs need the specification's full evidence gates; missing legal-employer/E-Verify proof withholds recommendations. A low result count does not relax policy.

## Start the backend locally

From the repository root, with Docker Compose installed:

```powershell
Copy-Item .env.example .env
# Set DEMO_MODE=true in .env ONLY for a disposable local demonstration.
docker compose -f deployment/compose.local.yml build
docker compose -f deployment/compose.local.yml up -d postgres redis
docker compose -f deployment/compose.local.yml run --rm api alembic upgrade head
docker compose -f deployment/compose.local.yml up -d api worker scheduler dispatcher
```

Migrations are explicit. API, worker and scheduler do not race to migrate. Local API binds `127.0.0.1:5555` (host port `STAFFER_API_PORT`, container port 8000); PostgreSQL and Redis have no host-published ports. The local backend image includes test dependencies so the documented pytest command works.

```powershell
docker compose -f deployment/compose.local.yml run --rm api python -m app.cli replay-fixtures
docker compose -f deployment/compose.local.yml run --rm api python -m app.cli demo-seed
docker compose -f deployment/compose.local.yml run --rm -e TEST_DATABASE_URL=postgresql+psycopg://staffer:staffer-local@postgres:5432/staffer api pytest
```

### Windows desktop demo scripts

On the Windows laptop, PowerShell scripts wrap the same steps in an isolated Compose project (`personal-staffer-demo`) with an ignored `.env.demo` (APP_ENV=local, DEMO_MODE=true, no credentials). Your real `.env` is never read or modified.

```powershell
scripts\check_desktop_prerequisites.ps1        # read-only report; installs nothing
scripts\start_desktop_demo.ps1 -BackendOnly    # build, migrate once, seed, verify readiness
scripts\start_desktop_demo.ps1                 # ...then flutter run -d windows in DEMO_MODE
scripts\stop_desktop_demo.ps1                  # stops containers; demo volumes are kept (-DeleteData removes them)
```

The full backend suite runs against the demo PostgreSQL/Redis from the same project; `scripts/` and `.env.example` are mounted read-only into the local `api` service so root-script tests collect:

```powershell
docker compose -p personal-staffer-demo -f deployment/compose.local.yml run --rm --no-deps -e TEST_DATABASE_URL=postgresql+psycopg://staffer:staffer-local@postgres:5432/staffer_test api pytest
```

`demo-seed` refuses production and refuses any database containing a non-demo owner. It creates clearly synthetic priority jobs; choose **Priority** in the feed. These are fictional records, including fictional E-Verify evidence. Use a separate database for real operation. Keep DEMO_MODE=false for real use.

## Native client

From `client/`, install the documented Flutter 3.47.4 toolchain and platform prerequisites:

```powershell
flutter pub get --enforce-lockfile
flutter analyze
flutter test
flutter run -d windows --dart-define=API_BASE_URL=http://127.0.0.1:5555 --dart-define=DEMO_MODE=true
```

For real use, set an HTTPS API origin and omit DEMO_MODE. Google sign-in and Gmail consent are separate. Provider secrets belong only on the backend; never place them in Flutter defines. See `docs/WINDOWS_SETUP.md` and `docs/ANDROID_SETUP.md` for exact build, installation, notification and update checks.

## Python development without Docker

From `backend/`: `uv sync --frozen`, then `uv run pytest`. Set DATABASE_URL and TEST_DATABASE_URL to a real isolated PostgreSQL server to execute database tests. Tests skip these checks explicitly when the server is unavailable; SQLite is never substituted. `uv run alembic upgrade head --sql` renders migration SQL without pretending it has been applied.

The supplied Git remote is configured on branch `feature/personal-staffer-core`. Changes have not been published or deployed from this session. The saved checkpoint contains the source and transfer instructions.


## Verification and remaining activation

On the target Windows laptop (branch `debug/windows-desktop`) the complete backend suite executed on real PostgreSQL/Redis with 458 passed and 0 skipped, and Flutter 3.47.4 analysis plus 20 tests passed; the Windows application build still awaits the Visual Studio C++ toolchain. Two earlier Linux debugging passes are recorded in docs/TEST_RESULTS.md. Each backend pass ran 401 successful tests and explicitly skipped 51 PostgreSQL tests; each final native pass ran 20 successful tests. Run `python scripts/verify_backend.py --pass-number 1` from the root to reproduce the backend checks. The final security regression run passed 404 tests with the same 51 database skips. Use a real isolated TEST_DATABASE_URL to execute the database gates.

An unsigned Android release compilation artifact is provided as build evidence; it needs a configured HTTPS backend and your protected signing identity before private installation. Windows compilation and Windows/Samsung device acceptance are pending. Google consent, actual E-Verify employer evidence and provider/deployment configuration remain required. See docs/CONTINUATION.md for the exact next steps and limits.

Optional JobSpy activation is blocked by an upstream dependency vulnerability; its pinned qualification record and runtime refusal are documented in docs/JOBSPY_SETUP.md.
