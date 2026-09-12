# Optional JobSpy dependency qualification — BLOCKED_SECURITY

**Do not activate JobSpy with the current dependency set.** The optional package imports and its interface matches the adapter, but its upstream dependency constraint excludes a published security fix. Live execution is blocked in code, even when `JOBSPY_ENABLED=true`.

`python-jobspy==1.1.82` requires `markdownify>=0.13.1,<0.14.0`. The resolved markdownify 0.13.1 is affected by **CVE-2025-46656 / GHSA-7mpr-5m44-h73r**, which allows excessive memory consumption from malformed heading tags. The fixed version is 0.14.1, outside JobSpy's permitted range. No dependency override or advisory suppression was used. The audit emitted two identical records for the same advisory: **one unique vulnerability in one package**, among 72 audited packages. See [the advisory](https://github.com/advisories/GHSA-7mpr-5m44-h73r).

## Reproducible optional dependency record

The nondefault `jobspy` dependency group pins `python-jobspy==1.1.82`; `backend/uv.lock` contains its resolved versions/hashes, and `requirements-jobspy.txt` preserves a full hash-pinned backend-plus-optional export for investigation. These files are qualification evidence, **not a recommendation to install the vulnerable runtime**. The default backend environment, ordinary requirements and Docker images do not include JobSpy. Nine optional packages were added to the lock; existing package versions and the default dependency export remained unchanged.

The group requires **Python 3.12** (`>=3.12,<3.13`) because upstream pins NumPy 1.26.3. The default backend still supports Python 3.12–3.13. UV enforces the optional group's interpreter constraint. A pip export cannot enforce the whole group constraint and may omit optional packages using Python markers; it is not a supported way to activate this group on Python 3.13.

For maintainers reviewing a future compatible upstream release, regenerate the optional export from `backend/`:

```bash
uv export --frozen --no-dev --group jobspy --no-emit-project --format requirements-txt --output-file ../requirements-jobspy.txt
pip-audit -r ../requirements-jobspy.txt --no-deps --disable-pip
```

Do not remove the execution guard until a reviewed release permits patched dependencies, passes package/source qualification, and has updated lock/audit evidence. Installing a different unreviewed version yields `JOBSPY_VERSION_UNQUALIFIED`; it does not bypass the guard.

## Actual checks

A separate scratch Python 3.12.14/Linux environment installed the optional set before the dependency audit identified the vulnerability. The real package imported, every query option matched an explicit `scrape_jobs` parameter, all four site configurations bound successfully, and `uv pip check` found compatible installed packages. **No scrape or source request was executed.** The default backend environment was not altered.

`docs/verification/jobspy-package-qualification.json` records versions, options, unchanged baseline versions and limitations. `docs/verification/jobspy-pip-audit.json` preserves the unmodified audit result. `docs/verification/check_jobspy_interface.py` reproduces the import/signature check in an already installed, isolated qualification environment, never calls `scrape_jobs`, and blocks Python socket connects. This Python guard is not an OS-level sandbox for native libraries.

The runtime connector returns `Health.state=BLOCKED` and error `BLOCKED_SECURITY` for the pinned real package, with no subprocess or source request. A missing package remains `NOT_CONFIGURED`. Injected fixture runners are test boundaries and remain usable for deterministic synthetic tests. Regression tests cover known-vulnerable and unqualified versions, absent dependency, and absence of subprocess/network execution.

## Source constraints after a future reviewed fix

Only registered `jobspy:indeed`, `jobspy:google`, `jobspy:glassdoor` and `jobspy:zip_recruiter` sources are allowed. LinkedIn jobs and proxy rotation are prohibited. Each source stays independent; every result still needs independent complete-JD, timestamp, geography, employer/E-Verify and active-opening evidence. An empty scraper result is incomplete/degraded coverage.

The package includes native `tls-client` transport. Its source access, redirects, rate limiting and resource usage remain unverified. The safe HTTP connector's DNS-pinning guarantees do not automatically apply to this third-party transport. No production activation instructions are provided while the security blocker remains.

References: [official PyPI package](https://pypi.org/project/python-jobspy/), [maintained source repository](https://github.com/speedyapply/JobSpy).
