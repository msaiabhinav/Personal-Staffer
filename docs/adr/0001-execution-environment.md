# ADR 0001 — Execution environment and verification boundaries

Status: accepted for this build session.

The supplied repository was initially inaccessible, so implementation began in a local Git project as the specification instructs. The user subsequently opened access; origin now points to the supplied, empty repository. No upstream files were replaced.

The execution environment is Linux with Python 3.12.14. Docker is absent. System PostgreSQL installation fails because privilege switching is unsupported; a downloaded portable PostgreSQL package also cannot create a non-root service user. The namespace maps only UID 0. PostgreSQL integration tests must therefore run with TEST_DATABASE_URL on the documented Compose or CI environment. We do not substitute SQLite, modify PostgreSQL root checks, or claim database concurrency tests passed here.

Windows and Samsung native checks require their platforms. Flutter tooling can support static/unit/widget checks here; actual installer, secure-storage, toast and device lifecycle behavior must be verified separately. No requirement is removed by this decision.
