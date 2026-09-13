"""Employer career sites the owner asked to be scanned (13 September 2026).

Three hosted career-site products expose a public listing without login, browser
execution or bot-detection bypass:

* Eightfold (``apply.careers.microsoft.com``): JSON search plus a JSON job detail.
* Talemetry (``careers.hcahealthcare.com``): JSON search; the job page carries a JSON-LD
  ``JobPosting`` which the direct connector already normalises.
* Radancy (``jobs.intuit.com``): a results endpoint whose ``results`` field is HTML; the
  job page carries a JSON-LD ``JobPosting``.

Each tenant is the site's own public URL as the owner supplied it.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from selectolax.parser import HTMLParser

from .base import BaseConnector, source_error, token, validate_job_url
from .contracts import Candidate, DiscoverResult, OpeningVerification
from .direct import DirectConnector, jobpostings
from .parsing import country_from_location, publication
from .safe_http import SourceHTTPError

_ARRANGEMENT = {"onsite": "ONSITE", "remote": "REMOTE", "hybrid": "HYBRID"}


def _epoch(value) -> datetime | None:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return None
    if stamp <= 0:
        return None
    return datetime.fromtimestamp(stamp, tz=UTC)


def _site(tenant: str) -> tuple[str, dict[str, str]]:
    """Origin and single-valued query parameters of a tenant URL."""
    validate_job_url(tenant)
    parts = urlsplit(tenant)
    params = {key: values[0] for key, values in parse_qs(parts.query).items() if values}
    return f"{parts.scheme}://{parts.hostname}", params


# --------------------------------------------------------------------------- Eightfold


class EightfoldConnector(BaseConnector):
    """Eightfold career sites. Tenant: ``https://<apply host>/?domain=<employer domain>``
    (optionally ``&location=United States``)."""

    source_type = "eightfold"
    PAGE = 50

    def _parts(self, tenant):
        origin, params = _site(tenant)
        domain = params.get("domain")
        if not domain or not re.fullmatch(r"[a-z0-9.-]{3,100}", domain):
            raise SourceHTTPError("INVALID_TENANT", "Eightfold tenant URL must carry ?domain=<employer domain>")
        return origin, domain, params.get("location")

    def discover(self, query="", tenant="", cursor=None):
        try:
            origin, domain, location = self._parts(tenant)
            offset = int(cursor or "0")
            if not 0 <= offset <= 10000:
                raise ValueError("invalid cursor")
            params = {"domain": domain, "query": query, "start": offset, "num": self.PAGE}
            if location:
                params["location"] = location
            _, body = self._json(f"{origin}/api/pcsx/search?" + urlencode(params))
            data = body.get("data") or {}
            positions = data.get("positions")
            if not isinstance(positions, list):
                raise TypeError("missing positions")
            candidates = []
            for p in positions:
                identifier = str(p.get("id") or "")
                if not re.fullmatch(r"[0-9]{6,24}", identifier):
                    continue
                candidates.append(
                    Candidate(
                        source_type=self.source_type,
                        tenant=tenant,
                        external_id=identifier,
                        source_url=f"{origin}/careers/job/{identifier}",
                        employer_name=self.employer_name,
                        title=p.get("name"),
                        payload=p,
                    )
                )
            self._success()
            total = int(data.get("count") or len(positions))
            more = bool(positions) and offset + len(positions) < total
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(offset + len(positions)) if more else None,
                coverage={"raw_count": len(positions), "total_hits": total, "complete_listing": not more},
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def _detail(self, tenant, identifier):
        origin, domain, _ = self._parts(tenant)
        return self._json(f"{origin}/api/apply/v2/jobs/{token(identifier)}?domain={domain}")

    def fetch(self, candidate):
        try:
            result, p = self._detail(candidate.tenant, candidate.external_id)
            if str(p.get("id")) != candidate.external_id:
                raise SourceHTTPError("IDENTITY_MISMATCH", "Source detail identifies another opening")
            return self._fetched(candidate, p, complete=bool(p.get("job_description")), url=result.final_url)
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def normalize(self, payload):
        p = payload.payload
        locations = p.get("locations") if isinstance(p.get("locations"), list) else [p.get("location")]
        locations = [str(loc) for loc in locations if loc]
        codes = sorted({code for code in (country_from_location(loc) for loc in locations) if code})
        created = _epoch(p.get("t_create"))
        pub = publication(created.isoformat() if created else None, "t_create")
        arrangement = _ARRANGEMENT.get(str(p.get("work_location_option") or "").lower(), "UNKNOWN")
        apply_url = p.get("canonicalPositionUrl") or payload.candidate.source_url
        job = self._base_job(
            payload,
            title=p.get("name") or p.get("posting_name"),
            description=p.get("job_description"),
            application_url=apply_url,
            employer_url=apply_url,
            requisition_id=str(p.get("ats_job_id") or p.get("display_job_id") or "") or None,
            locations=locations,
            country_codes=codes,
            work_arrangement=arrangement,
            publication=pub,
            source_updated_at=_epoch(p.get("t_update")),
        )
        return self._evidence(
            job,
            title=("name", p.get("name")),
            description=("job_description", p.get("job_description")),
            country_codes=("locations", locations or None),
            work_arrangement=("work_location_option", p.get("work_location_option")),
            publication=("t_create", p.get("t_create")),
            application_url=("canonicalPositionUrl", p.get("canonicalPositionUrl")),
        )

    def verify_opening(self, job_source):
        target = job_source.application_url
        try:
            result, p = self._detail(job_source.tenant, job_source.external_id)
        except SourceHTTPError as exc:
            if exc.status in (404, 410):
                return OpeningVerification(
                    status="CLOSED",
                    application_url=target,
                    evidence_text="Eightfold job detail no longer resolves this posting",
                    http_status=exc.status,
                )
            return OpeningVerification(
                status="UNKNOWN", application_url=target, evidence_text=exc.code, http_status=exc.status
            )
        except (ValueError, KeyError, TypeError):
            return OpeningVerification(status="UNKNOWN", application_url=target, evidence_text="Detail unreadable")
        identity = str(p.get("id")) == str(job_source.external_id) and bool(p.get("name"))
        if identity and not p.get("isPrivate", False):
            return OpeningVerification(
                status="ACTIVE",
                identity_match=True,
                actionable=True,
                application_url=p.get("canonicalPositionUrl") or target,
                final_url=result.final_url,
                evidence_text="Eightfold job detail resolves the posting with an application page",
                http_status=result.status_code,
            )
        return OpeningVerification(
            status="UNKNOWN",
            identity_match=identity,
            application_url=target,
            final_url=result.final_url,
            evidence_text="Eightfold detail did not confirm a public, matching posting",
            http_status=result.status_code,
        )


# --------------------------------------------------------- listing + JSON-LD job pages


class _ListingJsonLdConnector(DirectConnector):
    """A site listing supplies candidates; each job page's JSON-LD JobPosting is the record."""

    def _listing(self, query, tenant, cursor):  # -> (candidates, next_cursor, coverage)
        raise NotImplementedError

    def discover(self, query="", tenant="", cursor=None):
        try:
            candidates, next_cursor, coverage = self._listing(query, tenant, cursor)
            self._success()
            return DiscoverResult(candidates=candidates, next_cursor=next_cursor, coverage=coverage)
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
            if len(postings) != 1:
                raise SourceHTTPError("IDENTITY_UNRESOLVED", "Page did not contain exactly one JobPosting")
            p = dict(postings[0])
            # Identity is the job page the listing pointed at (its id is in the URL); the
            # JSON-LD identifier, when present, is the site's own requisition number.
            if candidate.external_id not in result.final_url and candidate.external_id not in candidate.source_url:
                raise SourceHTTPError("IDENTITY_MISMATCH", "Job page identifies another opening")
            p["url"] = p.get("url") or candidate.source_url
            if isinstance(p.get("datePosted"), str):
                p["datePosted"] = _pad_date(p["datePosted"])
            return self._fetched(candidate, p, complete=bool(p.get("description")), url=result.final_url)
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)


def _pad_date(value: str) -> str:
    """Radancy writes ``2026-7-21``; zero-pad so the date-only publication rule applies."""
    match = re.fullmatch(r"\s*(\d{4})-(\d{1,2})-(\d{1,2})\s*", value)
    if match:
        return f"{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}"
    return value


class TalemetryConnector(_ListingJsonLdConnector):
    """Talemetry career sites. Tenant: the site origin, e.g. ``https://careers.hcahealthcare.com``."""

    source_type = "talemetry"

    def _listing(self, query, tenant, cursor):
        origin, _ = _site(tenant)
        page = int(cursor or "1")
        if not 1 <= page <= 400:
            raise ValueError("invalid cursor")
        _, body = self._json(
            f"{origin}/jobs/search?" + urlencode({"q": query, "page": page}), headers={"Accept": "application/json"}
        )
        entries = body.get("entries")
        if not isinstance(entries, list):
            raise TypeError("missing entries")
        candidates = []
        for entry in entries:
            identifier = str(entry.get("id") or "")
            if not re.fullmatch(r"[0-9]{3,20}", identifier):
                continue
            location = entry.get("location") or {}
            candidates.append(
                Candidate(
                    source_type=self.source_type,
                    tenant=tenant,
                    external_id=identifier,
                    source_url=f"{origin}/jobs/{identifier}",
                    employer_name=self.employer_name,
                    title=entry.get("title"),
                    payload={
                        **entry,
                        "location_text": ", ".join(
                            str(location.get(k)) for k in ("locality", "region_abbr") if location.get(k)
                        ),
                    },
                )
            )
        total = int(body.get("total_entries") or len(entries))
        per_page = int(body.get("per_page") or max(len(entries), 1))
        more = bool(entries) and page * per_page < total
        return (
            candidates,
            (str(page + 1) if more else None),
            {
                "raw_count": len(entries),
                "total_hits": total,
                "complete_listing": not more,
            },
        )


class RadancyConnector(_ListingJsonLdConnector):
    """Radancy career sites. Tenant: the search URL the owner supplied, e.g.
    ``https://jobs.intuit.com/search-jobs?k=&l=United+States&orgIds=27595``."""

    source_type = "radancy"
    PER_PAGE = 15

    def _listing(self, query, tenant, cursor):
        origin, params = _site(tenant)
        page = int(cursor or "1")
        if not 1 <= page <= 400:
            raise ValueError("invalid cursor")
        search = {
            "ActiveFacetID": 0,
            "CurrentPage": page,
            "RecordsPerPage": self.PER_PAGE,
            "Distance": 50,
            "RadiusUnitType": 0,
            "Keywords": query,
            "Location": params.get("l", ""),
            "ShowRadius": "False",
            "IsPagination": "False",
            "FacetType": 0,
            "OrgIds": params.get("orgIds", ""),
            "SearchResultsModuleName": "Search Results",
            "SearchFiltersModuleName": "Search Filters",
            "SortCriteria": 0,
            "SortDirection": 0,
            "SearchType": 5,
        }
        _, body = self._json(f"{origin}/search-jobs/results?" + urlencode(search))
        fragment = body.get("results")
        if not isinstance(fragment, str):
            raise TypeError("missing results")
        tree = HTMLParser(fragment)
        candidates = []
        for anchor in tree.css("a[href^='/job/']"):
            href = anchor.attributes.get("href") or ""
            identifier = href.rstrip("/").rsplit("/", 1)[-1]
            if not re.fullmatch(r"[0-9]{4,24}", identifier):
                continue
            title_node = anchor.css_first("h2")
            location_node = anchor.css_first(".job-location")
            candidates.append(
                Candidate(
                    source_type=self.source_type,
                    tenant=tenant,
                    external_id=identifier,
                    source_url=urljoin(origin, href),
                    employer_name=self.employer_name,
                    title=html.unescape(title_node.text(strip=True)) if title_node else None,
                    payload={"href": href, "location_text": location_node.text(strip=True) if location_node else None},
                )
            )
        total_node = tree.css_first("[data-total-results]")
        total = (
            int(total_node.attributes.get("data-total-results") or len(candidates)) if total_node else len(candidates)
        )
        more = bool(candidates) and page * self.PER_PAGE < total
        return (
            candidates,
            (str(page + 1) if more else None),
            {
                "raw_count": len(candidates),
                "total_hits": total,
                "complete_listing": not more,
            },
        )
