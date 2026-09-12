# Dependency provenance and compatibility

Python runtime3.12.14; uv0.12.11. Exact resolution is committed in backend/uv.lock. Root requirements.txt is exported with hashes; backend/requirements-dev.txt includes test tooling. Regenerate both with scripts/export-requirements.sh after a lock change.

| Package | Installed and tested version |
|---|---|
| fastapi | 0.141.1 |
| pydantic | 2.13.5 |
| sqlalchemy | 2.0.52 |
| alembic | 1.20.0 |
| psycopg | 3.3.5 |
| celery | 5.6.3 |
| redis | 6.4.0 |
| httpx | 0.28.1 |
| selectolax | 0.4.11 |
| authlib | 1.8.0 |
| cryptography | 50.0.1 |
| google-auth | 2.58.0 |
| uvicorn | 0.52.4 |
| pytest | 9.1.1 |

Official implementation references checked at build time: [SQLAlchemy2.0](https://docs.sqlalchemy.org/en/20/), [Celery task behavior](https://docs.celeryq.dev/en/stable/userguide/tasks.html), [FastAPI](https://fastapi.tiangolo.com/), [uv locks](https://docs.astral.sh/uv/). Client exact versions and source references are in pubspec.yaml/pubspec.lock and device setup documents. Source-specific documents retain official API references and live probe outcomes.

Container image tags and exact digests were resolved from the official Docker Hub library tag API and recorded in deployment/image-lock.json. Docker image execution was unavailable here; digest resolution does not mean an image ran. GitHub Action tags/commit hashes were resolved from their owning repositories and pinned in ci.yml. CI has not run remotely in this session.

The installed Python dependency audit initially found no known advisories; final pass results are in dependency-audit.json. This is finite advisory coverage, not a guarantee of no vulnerabilities. FastAPI/Starlette/Authlib use a supported HTTPX compatibility path with deprecation warnings; functional boundary tests pass, but future migration to HTTPX2 needs compatibility verification, not a blind manifest substitution.
