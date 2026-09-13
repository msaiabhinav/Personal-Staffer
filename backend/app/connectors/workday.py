"""Selected public Workday CXS tenants, experimental and per-tenant verified.

CXS is a public website backend, not an asserted stable partner API. No account
credentials, browser execution or access-control bypass is used.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from app.eligibility.models import PublicationEvidence

from .base import BaseConnector, source_error, token
from .contracts import Candidate, DiscoverResult, OpeningVerification
from .parsing import country, country_from_location, employment
from .safe_http import SourceHTTPError

_POSTED_ON = re.compile(r"posted\s+(today|yesterday|(\d{1,3})(\+)?\s+days?\s+ago)", re.IGNORECASE)
_REMOTE_TYPE = {
    "fully remote": "REMOTE",
    "remote": "REMOTE",
    "hybrid": "HYBRID",
    "fully onsite": "ONSITE",
    "onsite": "ONSITE",
}


def corroborated_publication(start_date, posted_on, fetched_at: datetime) -> PublicationEvidence:
    """startDate semantics differ per tenant, so alone it is not publication evidence.

    When the tenant's own relative label (postedOn: "Posted Yesterday", "Posted 3 Days Ago")
    agrees with startDate to the day, two independent fields corroborate the posting date and
    it is recorded with date precision. "30+ Days Ago" corroborates only that the posting is
    at least that old. Any disagreement leaves publication unknown.
    """
    field = "jobPostingInfo.startDate corroborated by jobPostingInfo.postedOn"
    unknown = PublicationEvidence(source_field=field, kind="ORIGINAL")
    match = _POSTED_ON.search(str(posted_on or ""))
    if not match or not isinstance(start_date, str):
        return unknown
    try:
        start = date.fromisoformat(start_date)
    except ValueError:
        return unknown
    observed = fetched_at.date()
    word = match[1].lower()
    if word == "today":
        days, open_ended = 0, False
    elif word == "yesterday":
        days, open_ended = 1, False
    else:
        days, open_ended = int(match[2]), bool(match[3])
    expected = observed - timedelta(days=days)
    if open_ended:
        agrees = start <= expected + timedelta(days=1)
    else:
        agrees = abs((start - expected).days) <= 1  # Tenant-local midnight vs UTC observation.
    if not agrees:
        return unknown
    base = datetime(start.year, start.month, start.day, tzinfo=fetched_at.tzinfo)
    return PublicationEvidence(
        earliest=base - timedelta(hours=14),
        latest=base + timedelta(days=1, hours=12) - timedelta(microseconds=1),
        precision="DATE",
        kind="ORIGINAL",
        source_field=field,
        source_timezone=None,
    )


def tenant_parts(url: str):
    p = urlsplit(url)
    match = re.fullmatch(r"([a-zA-Z0-9-]+)\.wd\d{1,2}\.myworkdayjobs\.com", p.hostname or "")
    if not match or p.scheme != "https" or p.username or p.password or p.query or p.fragment or p.port:
        raise SourceHTTPError("INVALID_TENANT", "Provide a reviewed public Workday tenant/site HTTPS URL")
    pieces = [piece for piece in p.path.split("/") if piece]
    if pieces and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", pieces[0]):
        pieces = pieces[1:]
    if len(pieces) != 1:
        raise SourceHTTPError("INVALID_TENANT", "Workday tenant URL must identify exactly one career site")
    site = token(pieces[0])
    return f"https://{p.hostname}", match[1], site


class WorkdayConnector(BaseConnector):
    source_type = "workday"

    def discover(self, query="", tenant="", cursor=None):
        try:
            origin, organization, site = tenant_parts(tenant)
            offset = int(cursor or "0")
            if not 0 <= offset <= 10000:
                raise ValueError("invalid cursor")
            _, p = self._json(
                f"{origin}/wday/cxs/{organization}/{site}/jobs",
                body={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": query},
            )
            jobs = p["jobPostings"]
            candidates = []
            for j in jobs:
                external_path = j.get("externalPath", "")
                if not external_path.startswith("/job/") or ".." in external_path:
                    continue
                candidates.append(
                    Candidate(
                        source_type=self.source_type,
                        tenant=tenant,
                        external_id=external_path.rsplit("/", 1)[-1],
                        source_url=f"{origin}/{site}{external_path}",
                        title=j.get("title"),
                        employer_name=self.employer_name or organization,
                        payload=j,
                    )
                )
            more = offset + len(jobs) < p.get("total", len(jobs))
            self._success()
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(offset + len(jobs)) if jobs and more else None,
                coverage={"experimental_cxs": True, "raw_count": len(jobs), "complete_listing": not more},
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False, "experimental_cxs": True})

    def fetch(self, candidate):
        try:
            origin, organization, site = tenant_parts(candidate.tenant)
            path = candidate.payload.get("externalPath", "")
            if not path.startswith("/job/") or ".." in path or "?" in path:
                raise SourceHTTPError("INVALID_JOB_PATH", "Workday source path is invalid")
            result, p = self._json(f"{origin}/wday/cxs/{organization}/{site}{path}")
            detail = p.get("jobPostingInfo", {})
            if not detail.get("title"):
                raise SourceHTTPError("IDENTITY_UNRESOLVED", "Workday detail lacks job identity")
            return self._fetched(candidate, p, complete=bool(detail.get("jobDescription")), url=result.final_url)
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def verify_opening(self, job_source):
        # Workday career pages render client-side, so the generic HTML check never sees the
        # posting. The same public CXS detail used for fetching is authoritative: a posting
        # that still answers with its identity and canApply/posted is the live opening; a
        # 404 means it was taken down.
        target = job_source.application_url
        try:
            origin, organization, site = tenant_parts(job_source.tenant)
            path = "/job/" + urlsplit(job_source.source_url).path.split("/job/", 1)[-1]
            if ".." in path or "?" in path or path == "/job/":
                raise SourceHTTPError("INVALID_JOB_PATH", "Workday source path is invalid")
            result, p = self._json(f"{origin}/wday/cxs/{organization}/{site}{path}")
        except SourceHTTPError as exc:
            if exc.status in (404, 410):
                return OpeningVerification(
                    status="CLOSED",
                    application_url=target,
                    evidence_text="Workday CXS detail no longer resolves this posting",
                    http_status=exc.status,
                )
            return OpeningVerification(
                status="UNKNOWN", application_url=target, evidence_text=exc.code, http_status=exc.status
            )
        except (ValueError, KeyError, TypeError):
            return OpeningVerification(status="UNKNOWN", application_url=target, evidence_text="Detail unreadable")
        detail = p.get("jobPostingInfo") or {}
        identity = bool(detail.get("title")) and (
            (job_source.requisition_id and str(detail.get("jobReqId")) == str(job_source.requisition_id))
            or detail.get("title") == job_source.title
        )
        listed = str(detail.get("posted", "true")).lower() != "false"
        actionable = str(detail.get("canApply", "true")).lower() != "false" and bool(
            detail.get("externalUrl") or target
        )
        if identity and listed and actionable:
            return OpeningVerification(
                status="ACTIVE",
                identity_match=True,
                actionable=True,
                application_url=detail.get("externalUrl") or target,
                final_url=result.final_url,
                evidence_text="Workday CXS detail resolves the posting with its requisition id and an application path",
                http_status=result.status_code,
            )
        if identity and not listed:
            return OpeningVerification(
                status="CLOSED",
                identity_match=True,
                application_url=target,
                final_url=result.final_url,
                evidence_text="Workday CXS detail marks the posting as no longer posted",
                http_status=result.status_code,
            )
        return OpeningVerification(
            status="UNKNOWN",
            identity_match=bool(identity),
            application_url=target,
            final_url=result.final_url,
            evidence_text="Workday CXS detail did not confirm identity and an application path",
            http_status=result.status_code,
        )

    def normalize(self, payload):
        p = payload.payload.get("jobPostingInfo", {})
        location_country = p.get("country", {})
        code = (
            country(location_country.get("descriptor"))
            if isinstance(location_country, dict)
            else country(location_country)
        ) or country_from_location(p.get("location"))
        publication = corroborated_publication(p.get("startDate"), p.get("postedOn"), payload.fetched_at)
        arrangement = _REMOTE_TYPE.get(str(p.get("remoteType") or "").strip().lower(), "UNKNOWN")
        warnings = ["EXPERIMENTAL_TENANT_CONTRACT"]
        if publication.precision != "DATE":
            warnings.append("WORKDAY_START_DATE_SEMANTICS_REQUIRE_TENANT_VERIFICATION")
        job = self._base_job(
            payload,
            title=p.get("title"),
            description=p.get("jobDescription"),
            application_url=p.get("externalUrl") or payload.candidate.source_url,
            employer_url=payload.candidate.source_url,
            requisition_id=p.get("jobReqId"),
            locations=[p["location"]] if p.get("location") else [],
            country_codes=[code] if code else [],
            employment_type=employment(p.get("timeType")),
            work_arrangement=arrangement,
            publication=publication,
            warnings=warnings,
        )
        # postedOn is rounded relative text and startDate semantics differ by tenant; only their
        # agreement (corroborated_publication) is recorded as a posting date.
        return self._evidence(
            job,
            title=("jobPostingInfo.title", p.get("title")),
            description=("jobPostingInfo.jobDescription", p.get("jobDescription")),
            country_codes=("jobPostingInfo.country", location_country),
            employment_type=("jobPostingInfo.timeType", p.get("timeType")),
            work_arrangement=("jobPostingInfo.remoteType", p.get("remoteType")),
            publication=(
                "jobPostingInfo.startDate/postedOn",
                [p.get("startDate"), p.get("postedOn")] if publication.precision == "DATE" else None,
            ),
            raw_publication=("jobPostingInfo.startDate/postedOn", [p.get("startDate"), p.get("postedOn")]),
            application_url=("jobPostingInfo.externalUrl", p.get("externalUrl")),
        )
