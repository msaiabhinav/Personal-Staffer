"""Selected public Workday CXS tenants, experimental and per-tenant verified.

CXS is a public website backend, not an asserted stable partner API. No account
credentials, browser execution or access-control bypass is used.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .base import BaseConnector, source_error, token
from .contracts import Candidate, DiscoverResult
from .parsing import country, country_from_location, employment
from .safe_http import SourceHTTPError


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

    def normalize(self, payload):
        p = payload.payload.get("jobPostingInfo", {})
        location_country = p.get("country", {})
        code = (
            country(location_country.get("descriptor"))
            if isinstance(location_country, dict)
            else country(location_country)
        ) or country_from_location(p.get("location"))
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
            warnings=["EXPERIMENTAL_TENANT_CONTRACT", "WORKDAY_START_DATE_SEMANTICS_REQUIRE_TENANT_VERIFICATION"],
        )
        # postedOn is rounded relative text, startDate semantics differ by tenant. Neither grants freshness.
        return self._evidence(
            job,
            title=("jobPostingInfo.title", p.get("title")),
            description=("jobPostingInfo.jobDescription", p.get("jobDescription")),
            country_codes=("jobPostingInfo.country", location_country),
            employment_type=("jobPostingInfo.timeType", p.get("timeType")),
            raw_publication=("jobPostingInfo.startDate/postedOn", [p.get("startDate"), p.get("postedOn")]),
            application_url=("jobPostingInfo.externalUrl", p.get("externalUrl")),
        )
