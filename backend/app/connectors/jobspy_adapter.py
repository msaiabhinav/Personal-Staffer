"""Explicitly enabled, allowlisted JobSpy discovery. Direct verification remains mandatory."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

from .base import BaseConnector, source_error
from .contracts import Candidate, DiscoverResult, Health, SourceError
from .jobspy_runner import clean
from .parsing import employment, publication, salary
from .safe_http import SourceHTTPError, validate_url

ALLOWED_SITES = frozenset({"indeed", "google", "glassdoor", "zip_recruiter"})


class JobSpyConnector(BaseConnector):
    source_type = "jobspy"

    def __init__(self, client=None, *, site="indeed", enabled=False, runner=None):
        self.source_type = "jobspy:" + site
        super().__init__(client)
        if site not in ALLOWED_SITES:
            raise ValueError("JobSpy site is disabled; LinkedIn is never an allowed source")
        self.site, self.enabled, self.runner = site, enabled, runner
        if not enabled or runner is None and importlib.util.find_spec("jobspy") is None:
            self._health = Health(
                source_type="jobspy:" + site,
                state="NOT_CONFIGURED",
                last_error=SourceError(
                    code="JOBSPY_NOT_CONFIGURED",
                    message="Install optional JobSpy dependency and explicitly enable this source",
                ),
            )

    def query_options(self, query, offset=0):
        # Indeed permits hours_old OR job_type+is_remote, never all three.
        # Employment, geography and work arrangement are checked downstream from evidence.
        options = {
            "site_name": [self.site],
            "search_term": query,
            "location": "United States",
            "country_indeed": "USA",
            "results_wanted": 50,
            "offset": offset,
            "description_format": "html",
            "enforce_annual_salary": False,
            "verbose": 0,
            "proxies": None,
        }
        if self.site == "google":
            options["google_search_term"] = f"{query} jobs in United States since 3 days ago"
        else:
            options["hours_old"] = 72
        return options

    def _run(self, options):
        if self.runner:
            return self.runner(options)
        # Search-only child has no application secrets and no proxy rotation configuration.
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "PYTHONPATH", "SSL_CERT_FILE"}}
        with tempfile.TemporaryFile(mode="w+b") as output:
            completed = subprocess.run(
                [sys.executable, "-m", "app.connectors.jobspy_runner"],
                input=json.dumps(options),
                text=True,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=60,
                env=env,
                check=False,
            )
            size = output.tell()
            if completed.returncode != 0 or size > 8 * 1024 * 1024:
                raise SourceHTTPError("JOBSPY_FAILED", "JobSpy process failed or exceeded its output limit")
            output.seek(0)
            return json.loads(output.read(8 * 1024 * 1024))

    def discover(self, query="", tenant="USA", cursor=None):
        if self.health().state == "NOT_CONFIGURED":
            return DiscoverResult(
                errors=[self.health().last_error], coverage={"state": "NOT_CONFIGURED", "complete_listing": False}
            )
        try:
            offset = int(cursor or "0")
            if not 0 <= offset <= 950:
                raise ValueError("invalid cursor")
            output = self._run(self.query_options(query, offset))
            rows = clean(output.get("rows", []))
            errors = output.get("errors", [])
            if errors:
                raise SourceHTTPError(
                    "JOBSPY_SOURCE_ERROR", "JobSpy reported source errors; partial results were withheld"
                )
            candidates = []
            for row in rows[:50]:
                if row.get("site") not in {self.site, None}:
                    continue
                url = row.get("job_url")
                if not url:
                    continue
                validate_url(url)
                candidates.append(
                    Candidate(
                        source_type=self.source_type,
                        tenant=tenant,
                        external_id=str(row.get("id") or url),
                        source_url=url,
                        title=row.get("title"),
                        employer_name=row.get("company"),
                        payload=row,
                    )
                )
            self._success()
            if not rows:
                # JobSpy upstream can swallow exceptions. Uncorroborated empty results cannot prove complete success.
                self._health.state = "DEGRADED"
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(offset + 50) if len(rows) >= 50 and offset < 950 else None,
                coverage={
                    "complete_listing": False,
                    "raw_count": len(rows),
                    "reason": "SCRAPER_EMPTY_UNVERIFIED" if not rows else "DIRECT_REVERIFICATION_REQUIRED",
                },
            )
        except (SourceHTTPError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def fetch(self, candidate):
        # A scraper result is discovery evidence, not a trusted complete JD. Root can enrich
        # through a reviewed direct/ATS source. Silence exclusions must not pass this record.
        result = self._fetched(candidate, candidate.payload, complete=False)
        result.fetched_at = candidate.discovered_at
        return result

    def normalize(self, payload):
        p = clean(payload.payload)
        job = self._base_job(
            payload,
            title=p.get("title"),
            description=p.get("description"),
            employer=p.get("company"),
            application_url=p.get("job_url_direct") or p.get("job_url"),
            employer_url=p.get("job_url_direct"),
            locations=[p["location"]] if p.get("location") else [],
            employment_type=employment(p.get("job_type")),
            work_arrangement="REMOTE" if p.get("is_remote") is True else "UNKNOWN",
            publication=publication(p.get("date_posted"), "date_posted"),
            salary=salary(
                p.get("min_amount"), p.get("max_amount"), p.get("currency"), p.get("interval"), "JobSpy source pay"
            ),
            warnings=[
                "SCRAPER_DESCRIPTION_NOT_INDEPENDENTLY_COMPLETE",
                "DATE_PRECISION_AND_COUNTRY_REQUIRE_VERIFICATION",
            ],
        )
        return self._evidence(
            job,
            title=("title", p.get("title")),
            description=("description", p.get("description")),
            publication=("date_posted", p.get("date_posted")),
            employment_type=("job_type", p.get("job_type")),
            application_url=("job_url_direct/job_url", job.application_url),
        )
