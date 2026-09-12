"""Direct public JSON-LD JobPosting reader and reviewed employer-directory leads.

JavaScript-only portals explicitly return incomplete coverage. Arbitrary HTML is
never called a complete job description merely because the request returned 200.
"""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from .base import BaseConnector, source_error, validate_job_url
from .contracts import Candidate, DiscoverResult, FetchResult
from .parsing import country, employment, exact_time, publication, salary
from .safe_http import SourceHTTPError, validate_url


def jobpostings(html: str) -> list[dict]:
    tree = HTMLParser(html)
    result = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            types = value.get("@type", [])
            if types == "JobPosting" or isinstance(types, list) and "JobPosting" in types:
                result.append(value)
            for key in ("@graph", "itemListElement", "item"):
                if key in value:
                    visit(value[key])

    for script in tree.css('script[type="application/ld+json"]'):
        try:
            visit(json.loads(script.text()))
        except (ValueError, TypeError):
            continue
    return result


def job_id(posting: dict, url: str) -> str:
    ident = posting.get("identifier")
    if isinstance(ident, dict):
        ident = ident.get("value")
    return str(ident) if ident else hashlib.sha256(url.encode()).hexdigest()


class DirectConnector(BaseConnector):
    source_type = "direct"

    def discover(self, query="", tenant="", cursor=None):
        try:
            validate_job_url(tenant)
            response = self.client.get(tenant)
            if response.status_code != 200:
                raise SourceHTTPError("SOURCE_HTTP_ERROR", "Career page request failed", status=response.status_code)
            postings = jobpostings(response.text)
            candidates = []
            for p in postings[:100]:
                url = urljoin(response.final_url, p.get("url") or response.final_url)
                validate_job_url(url)
                if query and query.casefold() not in (p.get("title", "") + p.get("description", "")).casefold():
                    continue
                candidates.append(
                    Candidate(
                        source_type=self.source_type,
                        tenant=tenant,
                        external_id=job_id(p, url),
                        source_url=url,
                        title=p.get("title"),
                        employer_name=self.employer_name,
                        payload=p,
                    )
                )
            self._success()
            if not postings:
                self._health.state = "DEGRADED"
            return DiscoverResult(
                candidates=candidates,
                coverage={
                    "structured_postings": len(postings),
                    "complete_listing": False,
                    "reason": "ONLY_EMBEDDED_JOBPOSTING_OBJECTS_SUPPORTED",
                    "javascript_executed": False,
                },
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def fetch(self, candidate):
        try:
            validate_job_url(candidate.source_url)
            result = self.client.get(candidate.source_url)
            if result.status_code != 200:
                raise SourceHTTPError(
                    "SOURCE_HTTP_ERROR", "Specific source page request failed", status=result.status_code
                )
            postings = jobpostings(result.text)
            matched = [
                p
                for p in postings
                if job_id(p, urljoin(result.final_url, p.get("url") or result.final_url)) == candidate.external_id
            ]
            if len(matched) != 1:
                raise SourceHTTPError("IDENTITY_UNRESOLVED", "Page did not contain one matching JobPosting")
            p = matched[0]
            return self._fetched(candidate, p, complete=bool(p.get("description")), url=result.final_url)
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def normalize(self, payload: FetchResult):
        p = payload.payload
        organization = p.get("hiringOrganization") or {}
        job_locations = p.get("jobLocation") or []
        if isinstance(job_locations, dict):
            job_locations = [job_locations]
        addresses = [loc.get("address", {}) for loc in job_locations if isinstance(loc, dict)]
        addresses = [a for a in addresses if isinstance(a, dict)]
        restrictions = p.get("applicantLocationRequirements") or []
        if isinstance(restrictions, dict):
            restrictions = [restrictions]
        codes = [country(a.get("addressCountry")) for a in addresses]
        for r in restrictions:
            if isinstance(r, dict) and r.get("@type") == "Country":
                codes.append(country(r.get("name")))
        base_salary = p.get("baseSalary") or {}
        if not isinstance(base_salary, dict):
            base_salary = {}
        value = base_salary.get("value", {})
        if not isinstance(value, dict):
            value = {"value": value}
        fixed = value.get("value")
        candidate_url = p.get("url") or payload.candidate.source_url
        job = self._base_job(
            payload,
            title=p.get("title"),
            description=p.get("description"),
            employer=organization.get("name") if isinstance(organization, dict) else None,
            application_url=urljoin(payload.candidate.source_url, candidate_url),
            employer_url=urljoin(payload.candidate.source_url, candidate_url),
            requisition_id=str(p["identifier"].get("value"))
            if isinstance(p.get("identifier"), dict) and p["identifier"].get("value") is not None
            else None,
            locations=[
                ", ".join(str(a[k]) for k in ("addressLocality", "addressRegion", "addressCountry") if a.get(k))
                for a in addresses
            ],
            country_codes=sorted({c for c in codes if c}),
            workplace_states=[a["addressRegion"] for a in addresses if a.get("addressRegion")],
            employment_type=employment(p.get("employmentType")),
            work_arrangement="REMOTE" if p.get("jobLocationType") == "TELECOMMUTE" else "UNKNOWN",
            original_published_at=exact_time(p.get("datePosted")),
            publication=publication(p.get("datePosted"), "datePosted"),
            valid_through=exact_time(p.get("validThrough")),
            salary=salary(
                value.get("minValue", fixed),
                value.get("maxValue", fixed),
                base_salary.get("currency"),
                value.get("unitText"),
                "baseSalary",
            ),
        )
        return self._evidence(
            job,
            title=("title", p.get("title")),
            description=("description", p.get("description")),
            country_codes=("jobLocation/applicantLocationRequirements", [addresses, restrictions]),
            employment_type=("employmentType", p.get("employmentType")),
            publication=("datePosted", p.get("datePosted")),
            salary=("baseSalary", base_salary),
            application_url=("url", candidate_url),
        )


class DirectoryDiscovery(BaseConnector):
    """Returns employer/link leads only, never normalized eligible jobs."""

    source_type = "directory"
    ALLOWED = frozenset(
        {
            "ycombinator.com",
            "www.ycombinator.com",
            "a16z.com",
            "www.a16z.com",
            "sequoiacap.com",
            "www.sequoiacap.com",
            "usv.com",
            "www.usv.com",
            "wellfound.com",
            "www.welcometothejungle.com",
        }
    )

    def discover_employer_links(self, url: str, *, limit: int = 100) -> dict:
        validate_url(url)
        if urlsplit(url).hostname not in self.ALLOWED:
            raise ValueError("Directory source must be in the reviewed source catalog")
        response = self.client.get(url)
        if response.status_code != 200:
            error = source_error(
                SourceHTTPError("DIRECTORY_UNAVAILABLE", "Public directory unavailable", status=response.status_code)
            )
            self._failure(error)
            return {"leads": [], "state": self.health().state, "error": error.model_dump(), "complete": False}
        tree = HTMLParser(response.text)
        leads, seen = [], set()
        for node in tree.css("a[href]"):
            target = urljoin(response.final_url, node.attributes.get("href", ""))
            try:
                validate_url(target)
            except SourceHTTPError:
                continue
            if target in seen or urlsplit(target).hostname in self.ALLOWED:
                continue
            if "linkedin.com" in (urlsplit(target).hostname or ""):
                continue
            seen.add(target)
            leads.append(
                {
                    "url": target,
                    "label": node.text(strip=True)[:200],
                    "source_url": response.final_url,
                    "verification_state": "LEAD_ONLY",
                    "employer_identity_verified": False,
                    "pool_membership_verified": False,
                }
            )
            if len(leads) >= min(max(limit, 1), 100):
                break
        self._success()
        return {
            "leads": leads,
            "state": "HEALTHY",
            "complete": False,
            "limitations": "Static external links only. Review employer identity, geography and careers URLs separately.",
        }
