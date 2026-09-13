"""amazon.jobs public search feed. No account login or application submission.

The public ``/en/search.json`` endpoint returns complete postings (description and both
qualification sections) per search hit, so a run discovers and fetches from the same
observation. The tenant is the ISO-3166 alpha-3 country filter the owner registered
(``USA``); one registered source covers every Amazon legal entity hiring there.
"""

from __future__ import annotations

import html
import json
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from app.eligibility.models import PublicationEvidence

from .base import BaseConnector, source_error, token
from .contracts import Candidate, DiscoverResult, OpeningVerification, utcnow
from .parsing import country, employment
from .safe_http import SourceHTTPError

ORIGIN = "https://www.amazon.jobs"
PAGE_SIZE = 100
MAX_OFFSET = 10000
_ID = re.compile(r"[0-9]{4,12}")
_ARRANGEMENT = {"ONSITE": "ONSITE", "REMOTE": "REMOTE", "HYBRID": "HYBRID", "VIRTUAL": "REMOTE"}
_MONTHS = {
    name: index
    for index, name in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ],
        start=1,
    )
}


def posted_date(value) -> PublicationEvidence:
    """``posted_date`` is a bare date ("September 10, 2026") with no zone: full-day uncertainty."""
    if isinstance(value, str):
        match = re.fullmatch(r"\s*([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})\s*", value)
        if match and match[1].lower() in _MONTHS:
            try:
                base = datetime(int(match[3]), _MONTHS[match[1].lower()], int(match[2]), tzinfo=UTC)
            except ValueError:
                return PublicationEvidence(source_field="posted_date", kind="ORIGINAL")
            return PublicationEvidence(
                earliest=base - timedelta(hours=14),
                latest=base + timedelta(days=1, hours=12) - timedelta(microseconds=1),
                precision="DATE",
                kind="ORIGINAL",
                source_field="posted_date",
                source_timezone=None,
            )
    return PublicationEvidence(source_field="posted_date", kind="ORIGINAL")


def search_url(query: str, tenant: str, offset: int, *, limit: int = PAGE_SIZE) -> str:
    params = [
        ("base_query", query),
        ("result_limit", str(limit)),
        ("offset", str(offset)),
        ("sort", "recent"),
    ]
    if tenant:
        params.append(("normalized_country_code[]", token(tenant)))
    return f"{ORIGIN}/en/search.json?" + urlencode(params)


class AmazonJobsConnector(BaseConnector):
    source_type = "amazon_jobs"

    def __init__(self, client=None, *, employer_name=None):
        super().__init__(client, employer_name=employer_name)
        self._seen: dict[str, tuple[float, dict, str]] = {}

    def _remember(self, jobs, final_url):
        stamp = time.monotonic()
        for job in jobs:
            identifier = str(job.get("id_icims") or "")
            if identifier:
                self._seen[identifier] = (stamp, job, final_url)
        if len(self._seen) > 2000:
            for key in sorted(self._seen, key=lambda k: self._seen[k][0])[: len(self._seen) - 2000]:
                self._seen.pop(key, None)

    def _search(self, query, tenant, offset):
        result, body = self._json(search_url(query, tenant, offset))
        jobs = body.get("jobs")
        if not isinstance(jobs, list):
            raise TypeError("missing jobs")
        return result, body, jobs

    def discover(self, query="", tenant="", cursor=None):
        try:
            offset = int(cursor or "0")
            if not 0 <= offset <= MAX_OFFSET:
                raise ValueError("invalid cursor")
            result, body, jobs = self._search(query, tenant, offset)
            self._remember(jobs, result.final_url)
            candidates = []
            for j in jobs:
                identifier = str(j.get("id_icims") or "")
                path = str(j.get("job_path") or "")
                if not _ID.fullmatch(identifier) or not path.startswith("/en/jobs/") or ".." in path:
                    continue
                candidates.append(
                    Candidate(
                        source_type=self.source_type,
                        tenant=tenant,
                        external_id=identifier,
                        source_url=ORIGIN + path,
                        employer_name=self.employer_name or j.get("company_name") or "Amazon",
                        title=j.get("title"),
                        payload=j,
                    )
                )
            self._success()
            total = int(body.get("hits") or len(jobs))
            more = bool(jobs) and offset + len(jobs) < total and offset + len(jobs) <= MAX_OFFSET
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(offset + len(jobs)) if more else None,
                coverage={
                    "board_only": False,
                    "raw_count": len(jobs),
                    "total_hits": total,
                    "complete_listing": not more,
                    "publication_semantics": "ORIGINAL_DATE",
                },
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def _lookup(self, identifier, tenant):
        # The search endpoint answers an exact job id query with that single posting; a job
        # that no longer appears has left the public listing.
        result, _, jobs = self._search(identifier, "", 0)
        job = next((j for j in jobs if str(j.get("id_icims")) == identifier), None)
        return result, job

    def fetch(self, candidate):
        try:
            identifier = token(candidate.external_id)
            entry = self._seen.get(identifier)
            if entry and time.monotonic() - entry[0] <= 60:
                _, job, final_url = entry
            else:
                result, job = self._lookup(identifier, candidate.tenant)
                final_url = result.final_url
                if job is None:
                    raise SourceHTTPError("NOT_LISTED", "Specific opening is not listed on amazon.jobs", status=404)
            if str(job.get("id_icims")) != candidate.external_id:
                raise SourceHTTPError("IDENTITY_MISMATCH", "Source detail identifies another opening")
            return self._fetched(candidate, job, complete=bool(job.get("description")), url=final_url)
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    @staticmethod
    def _locations(p):
        raw = p.get("locations")
        rows = []
        if isinstance(raw, list):
            for item in raw:
                try:
                    rows.append(json.loads(item) if isinstance(item, str) else item)
                except (TypeError, ValueError):
                    continue
        rows = [row for row in rows if isinstance(row, dict)]
        labels = [str(row.get("normalizedLocation") or row.get("location") or "") for row in rows]
        labels = [label for label in labels if label]
        if not labels and p.get("normalized_location"):
            labels = [str(p["normalized_location"])]
        countries = {country(row.get("countryIso2a") or row.get("normalizedCountryCode")) for row in rows}
        if not countries:
            countries = {country(p.get("country_code"))}
        states = {str(row.get("region") or row.get("normalizedStateName") or "") for row in rows}
        if not states and p.get("state"):
            states = {str(p["state"])}
        types = {str(row.get("type") or "").upper() for row in rows}
        arrangement = "UNKNOWN"
        if types and all(t in _ARRANGEMENT for t in types) and len({_ARRANGEMENT[t] for t in types}) == 1:
            arrangement = _ARRANGEMENT[next(iter(types))]
        return labels, sorted(c for c in countries if c), sorted(s for s in states if s), arrangement

    def normalize(self, payload):
        p = payload.payload
        sections = [
            ("Description", p.get("description")),
            ("Basic qualifications", p.get("basic_qualifications")),
            ("Preferred qualifications", p.get("preferred_qualifications")),
        ]
        description = "\n".join("<h2>" + html.escape(title) + "</h2>" + str(text) for title, text in sections if text)
        labels, countries, states, arrangement = self._locations(p)
        pub = posted_date(p.get("posted_date"))
        job = self._base_job(
            payload,
            title=p.get("title"),
            description=description,
            employer=p.get("company_name") or self.employer_name,
            application_url=p.get("url_next_step") or payload.candidate.source_url,
            employer_url=payload.candidate.source_url,
            requisition_id=str(p.get("id_icims")) if p.get("id_icims") else None,
            locations=labels,
            country_codes=countries,
            workplace_states=states,
            work_arrangement=arrangement,
            employment_type=employment(p.get("job_schedule_type")),
            publication=pub,
        )
        return self._evidence(
            job,
            title=("title", p.get("title")),
            description=("description", p.get("description")),
            country_codes=("locations[].countryIso2a", countries or None),
            work_arrangement=("locations[].type", arrangement if arrangement != "UNKNOWN" else None),
            employment_type=("job_schedule_type", p.get("job_schedule_type")),
            publication=("posted_date", p.get("posted_date")),
            application_url=("url_next_step", p.get("url_next_step")),
        )

    def verify_opening(self, job_source):
        # The apply destination requires an Amazon account sign-in, so an HTML check would
        # only ever see a login page. The public search listing is authoritative instead.
        target = job_source.application_url
        try:
            result, job = self._lookup(token(job_source.external_id), job_source.tenant)
        except SourceHTTPError as exc:
            return OpeningVerification(
                status="UNKNOWN", application_url=target, evidence_text=exc.code, http_status=exc.status
            )
        except (ValueError, KeyError, TypeError):
            return OpeningVerification(status="UNKNOWN", application_url=target, evidence_text="Listing unreadable")
        if job is None:
            return OpeningVerification(
                status="CLOSED",
                application_url=target,
                final_url=result.final_url,
                evidence_text="amazon.jobs public listing no longer returns this job id",
                http_status=result.status_code,
            )
        apply_url = job.get("url_next_step") or target
        return OpeningVerification(
            status="ACTIVE" if apply_url else "UNKNOWN",
            identity_match=True,
            actionable=bool(apply_url),
            application_url=apply_url,
            final_url=result.final_url,
            checked_at=utcnow(),
            evidence_text=f"amazon.jobs public listing returns job {job_source.external_id} with an application destination"
            if apply_url
            else "Listed posting has no application destination",
            http_status=result.status_code,
        )
