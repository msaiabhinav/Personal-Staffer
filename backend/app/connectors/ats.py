"""Public, employer-scoped ATS feed implementations. No account login or application submission."""

from __future__ import annotations

import html
import time
from urllib.parse import urlencode

from .base import BaseConnector, source_error, token
from .contracts import Candidate, DiscoverResult, OpeningVerification, utcnow
from .parsing import country, country_from_location, employment, exact_time, publication, salary
from .safe_http import SourceHTTPError


class AshbyConnector(BaseConnector):
    source_type = "ashby"

    def __init__(self, client=None, *, employer_name=None):
        super().__init__(client, employer_name=employer_name)
        self._boards = {}

    def _board(self, tenant, *, refresh=False):
        entry = self._boards.get(tenant)
        if not refresh and entry and time.monotonic() - entry[0] <= 60:
            return entry[1:]
        result, body = self._json(self.board_url(tenant))
        jobs = body.get("jobs")
        if not isinstance(jobs, list):
            raise TypeError("missing jobs")
        if len(jobs) > 5000:
            raise SourceHTTPError("BOARD_BUDGET_EXCEEDED", "Source board exceeds the 5000-posting run budget")
        observed = utcnow()
        if len(self._boards) >= 2 and tenant not in self._boards:
            self._boards.pop(next(iter(self._boards)))
        self._boards[tenant] = (time.monotonic(), result, jobs, observed)
        return result, jobs, observed

    @staticmethod
    def board_url(tenant):
        return f"https://api.ashbyhq.com/posting-api/job-board/{token(tenant)}?includeCompensation=true"

    def discover(self, query="", tenant="", cursor=None):
        try:
            _, jobs, observed = self._board(tenant, refresh=True)
            candidates = [
                Candidate(
                    source_type=self.source_type,
                    tenant=tenant,
                    external_id=str(j["id"]),
                    source_url=j["jobUrl"],
                    employer_name=self.employer_name or tenant,
                    title=j.get("title"),
                    payload=j,
                    discovered_at=observed,
                )
                for j in jobs
                if j.get("isListed") is True
                and (
                    not query
                    or query.casefold() in (j.get("title", "") + " " + j.get("descriptionPlain", "")).casefold()
                )
            ]
            self._success()
            return DiscoverResult(
                candidates=candidates,
                source_timestamp=observed,
                coverage={
                    "board_only": True,
                    "raw_count": len(jobs),
                    "complete_listing": True,
                    "publication_semantics": "LAST_PUBLICATION",
                },
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def verify_opening(self, job_source):
        # Ashby-hosted job pages render client-side, so the generic HTML check cannot see the
        # posting. The public posting API is authoritative: a listed job with an applyUrl is the
        # live, actionable opening; a job missing from a successfully fetched board is closed.
        target = job_source.application_url
        try:
            result, jobs, observed = self._board(job_source.tenant)
        except SourceHTTPError as exc:
            return OpeningVerification(
                status="UNKNOWN", application_url=target, evidence_text=exc.code, http_status=exc.status
            )
        except (ValueError, KeyError, TypeError):
            return OpeningVerification(status="UNKNOWN", application_url=target, evidence_text="Board unreadable")
        job = next((j for j in jobs if str(j.get("id")) == str(job_source.external_id)), None)
        if job is None or job.get("isListed") is not True:
            return OpeningVerification(
                status="CLOSED",
                application_url=target,
                final_url=result.final_url,
                checked_at=observed,
                evidence_text="Ashby posting API no longer lists this job id",
                http_status=result.status_code,
            )
        apply_url = job.get("applyUrl") or job.get("jobUrl")
        if not apply_url:
            return OpeningVerification(
                status="UNKNOWN",
                identity_match=True,
                application_url=target,
                final_url=result.final_url,
                checked_at=observed,
                evidence_text="Listed posting has no application URL",
                http_status=result.status_code,
            )
        return OpeningVerification(
            status="ACTIVE",
            identity_match=True,
            actionable=True,
            application_url=apply_url,
            final_url=result.final_url,
            checked_at=observed,
            evidence_text=f"Ashby posting API lists job {job_source.external_id} as isListed with an application URL",
            http_status=result.status_code,
        )

    def fetch(self, candidate):
        # Run-local snapshots reuse the full public board for at most 60 seconds.
        # Preserve the network observation time; reuse is never presented as a new fetch.
        try:
            result, jobs, observed = self._board(candidate.tenant)
            job = next(
                (j for j in jobs if str(j.get("id")) == candidate.external_id and j.get("isListed") is True), None
            )
            if job is None:
                raise SourceHTTPError("NOT_LISTED", "Specific opening is not listed on the source board", status=404)
            fetched = self._fetched(
                candidate,
                job,
                complete=bool(job.get("descriptionHtml") or job.get("descriptionPlain")),
                url=result.final_url,
            )
            fetched.fetched_at = observed
            return fetched
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def normalize(self, payload):
        p = payload.payload
        locs = [p.get("location")] + [loc.get("location") for loc in p.get("secondaryLocations", [])]
        addresses = [p.get("address", {}).get("postalAddress", {})] + [
            loc.get("address", {}).get("postalAddress", loc.get("address", {}))
            for loc in p.get("secondaryLocations", [])
        ]
        countries = sorted({c for address in addresses if (c := country(address.get("addressCountry")))})
        arrangement = str(p.get("workplaceType", "")).upper()
        arrangement = (
            arrangement
            if arrangement in {"REMOTE", "HYBRID", "ONSITE"}
            else "REMOTE"
            if p.get("isRemote") is True
            else "UNKNOWN"
        )
        pub = publication(p.get("publishedAt"), "publishedAt", "LAST_PUBLICATION")
        comp = p.get("compensation") or {}
        components = comp.get("summaryComponents", [])
        if not components:
            tiers = comp.get("compensationTiers", [])
            # More than one tier cannot be flattened into a fabricated universal range.
            components = tiers[0].get("components", []) if len(tiers) == 1 else []
        salaries = [c for c in components if c.get("compensationType") == "Salary"]
        s = salaries[0] if len(salaries) == 1 else {}
        job = self._base_job(
            payload,
            title=p.get("title"),
            description=p.get("descriptionHtml") or p.get("descriptionPlain"),
            application_url=p.get("applyUrl"),
            employer_url=p.get("jobUrl"),
            locations=[loc for loc in locs if isinstance(loc, str)],
            country_codes=countries,
            workplace_states=[a["addressRegion"] for a in addresses if a.get("addressRegion")],
            employment_type=employment(p.get("employmentType")),
            work_arrangement=arrangement,
            publication=pub,
            last_published_at=exact_time(p.get("publishedAt")),
            salary=salary(
                s.get("minValue"), s.get("maxValue"), s.get("currencyCode"), s.get("interval"), "compensation"
            ),
            warnings=["LAST_PUBLICATION_REQUIRES_REPOST_CHECK"],
        )
        return self._evidence(
            job,
            title=("title", p.get("title")),
            description=("descriptionHtml", p.get("descriptionHtml")),
            country_codes=("address/secondaryLocations.address", addresses),
            employment_type=("employmentType", p.get("employmentType")),
            publication=("publishedAt", p.get("publishedAt")),
            salary=("compensation", comp),
            application_url=("applyUrl", p.get("applyUrl")),
        )


class GreenhouseConnector(BaseConnector):
    source_type = "greenhouse"

    def discover(self, query="", tenant="", cursor=None):
        try:
            _, body = self._json(f"https://boards-api.greenhouse.io/v1/boards/{token(tenant)}/jobs?content=true")
            jobs = body["jobs"]
            candidates = [
                Candidate(
                    source_type=self.source_type,
                    tenant=tenant,
                    external_id=str(j["id"]),
                    source_url=j["absolute_url"],
                    title=j.get("title"),
                    employer_name=self.employer_name or tenant,
                    payload=j,
                )
                for j in jobs
                if j.get("internal_job_id") is not None
                and (not query or query.casefold() in (j.get("title", "") + " " + j.get("content", "")).casefold())
            ]
            self._success()
            return DiscoverResult(
                candidates=candidates,
                coverage={
                    "board_only": True,
                    "raw_count": len(jobs),
                    "complete_listing": True,
                    "detail_required_for_first_published": True,
                },
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def fetch(self, candidate):
        try:
            url = (
                f"https://boards-api.greenhouse.io/v1/boards/{token(candidate.tenant)}/jobs/"
                f"{token(candidate.external_id)}?questions=true&pay_transparency=true"
            )
            result, p = self._json(url)
            if str(p.get("id")) != candidate.external_id:
                raise SourceHTTPError("IDENTITY_MISMATCH", "Source detail identifies a different opening")
            return self._fetched(candidate, p, complete=bool(p.get("content")), url=result.final_url)
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def verify_opening(self, job_source):
        # Employer career pages that embed Greenhouse render the posting with JavaScript, so
        # the generic HTML check cannot see the title or an Apply control. The Job Board API is
        # the authoritative source instead: it returns a live posting by id together with its
        # application questions, and answers 404 once the opening closes.
        url = (
            f"https://boards-api.greenhouse.io/v1/boards/{token(job_source.tenant)}/jobs/"
            f"{token(job_source.external_id)}?questions=true"
        )
        target = job_source.application_url
        try:
            result, p = self._json(url)
        except SourceHTTPError as exc:
            status = exc.status
            if status in (404, 410):
                return OpeningVerification(
                    status="CLOSED",
                    application_url=target,
                    final_url=url,
                    evidence_text="Greenhouse Job Board API no longer lists this job id",
                    http_status=status,
                )
            return OpeningVerification(
                status="UNKNOWN", application_url=target, final_url=url, evidence_text=exc.code, http_status=status
            )
        except (ValueError, KeyError, TypeError):
            return OpeningVerification(
                status="UNKNOWN", application_url=target, evidence_text="Greenhouse detail payload unreadable"
            )
        identity = str(p.get("id")) == str(job_source.external_id)
        absolute = p.get("absolute_url")
        questions = p.get("questions")
        actionable = identity and bool(absolute) and isinstance(questions, list) and len(questions) > 0
        if identity and actionable:
            return OpeningVerification(
                status="ACTIVE",
                identity_match=True,
                actionable=True,
                application_url=absolute or target,
                final_url=result.final_url,
                evidence_text=(
                    f"Greenhouse Job Board API lists job {job_source.external_id} with "
                    f"{len(questions)} application question(s) and absolute_url"
                ),
                http_status=result.status_code,
            )
        return OpeningVerification(
            status="UNKNOWN",
            identity_match=identity,
            actionable=False,
            application_url=absolute or target,
            final_url=result.final_url,
            evidence_text="Greenhouse detail lacks an application form or absolute_url",
            http_status=result.status_code,
        )

    def normalize(self, payload):
        p = payload.payload
        metadata = p.get("metadata") or []
        types = [
            m.get("value")
            for m in metadata
            if str(m.get("name", "")).lower() in {"employment type", "employment_type", "job type"}
        ]
        emp_type = employment(types[0]) if len(types) == 1 else None
        location_name = (p.get("location") or {}).get("name", "")
        location_country = country_from_location(location_name)
        job = self._base_job(
            payload,
            title=p.get("title"),
            description=p.get("content"),
            employer=p.get("company_name"),
            application_url=p.get("absolute_url"),
            employer_url=p.get("absolute_url"),
            requisition_id=p.get("requisition_id"),
            locations=[location_name],
            country_codes=[location_country] if location_country else [],
            employment_type=emp_type,
            publication=publication(p.get("first_published"), "first_published"),
            original_published_at=exact_time(p.get("first_published")),
            source_updated_at=exact_time(p.get("updated_at")),
            warnings=[] if p.get("first_published") else ["PUBLICATION_MISSING_UPDATED_AT_NOT_PUBLICATION"],
        )
        # pay_input_ranges lacks a documented interval; retain as raw evidence without annualizing cents.
        return self._evidence(
            job,
            title=("title", p.get("title")),
            description=("content", p.get("content")),
            publication=("first_published", p.get("first_published")),
            updated_at=("updated_at", p.get("updated_at")),
            employment_type=("metadata", types),
            location=("location.name", location_name or None),
            country_codes=("location.name", location_name if location_country else None),
            salary=("pay_input_ranges", p.get("pay_input_ranges")),
            application_url=("absolute_url", p.get("absolute_url")),
        )


class LeverConnector(BaseConnector):
    source_type = "lever"

    def discover(self, query="", tenant="", cursor=None):
        try:
            offset = int(cursor or "0")
            if offset < 0 or offset > 10000:
                raise ValueError("invalid cursor")
            url = f"https://api.lever.co/v0/postings/{token(tenant)}?" + urlencode(
                {"mode": "json", "skip": offset, "limit": 100}
            )
            _, jobs = self._json(url)
            if not isinstance(jobs, list):
                raise TypeError("invalid jobs")
            candidates = [
                Candidate(
                    source_type=self.source_type,
                    tenant=tenant,
                    external_id=j["id"],
                    source_url=j["hostedUrl"],
                    title=j.get("text"),
                    employer_name=self.employer_name or tenant,
                    payload=j,
                )
                for j in jobs
                if not query or query.casefold() in (j.get("text", "") + j.get("descriptionPlain", "")).casefold()
            ]
            self._success()
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(offset + 100) if len(jobs) == 100 else None,
                coverage={"board_only": True, "raw_count": len(jobs), "complete_listing": len(jobs) < 100},
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def fetch(self, candidate):
        try:
            url = f"https://api.lever.co/v0/postings/{token(candidate.tenant)}/{token(candidate.external_id)}?mode=json"
            result, p = self._json(url)
            if p.get("id") != candidate.external_id:
                raise SourceHTTPError("IDENTITY_MISMATCH", "Source detail identifies another opening")
            return self._fetched(
                candidate, p, complete=bool(p.get("description") or p.get("descriptionPlain")), url=result.final_url
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def normalize(self, payload):
        p = payload.payload
        description = p.get("description") or p.get("descriptionPlain", "")
        opening = p.get("opening") or p.get("openingPlain")
        if opening:
            description = opening + "\n" + description
        for section in p.get("lists", []):
            description += "\n<h2>" + section.get("text", "") + "</h2>\n" + section.get("content", "")
        description += "\n" + (p.get("additional") or p.get("additionalPlain", ""))
        category, compensation = p.get("categories") or {}, p.get("salaryRange") or {}
        arrangement = str(p.get("workplaceType", "")).upper()
        code = country(p.get("country"))
        job = self._base_job(
            payload,
            title=p.get("text"),
            description=description,
            application_url=p.get("applyUrl"),
            employer_url=p.get("hostedUrl"),
            locations=[category["location"]] if category.get("location") else [],
            country_codes=[code] if code else [],
            employment_type=employment(category.get("commitment")),
            work_arrangement=arrangement if arrangement in {"ONSITE", "REMOTE", "HYBRID"} else "UNKNOWN",
            salary=salary(
                compensation.get("min"),
                compensation.get("max"),
                compensation.get("currency"),
                compensation.get("interval"),
                "salaryRange",
            ),
            warnings=["PUBLICATION_NOT_PROVIDED_BY_PUBLIC_CONTRACT"],
        )
        return self._evidence(
            job,
            title=("text", p.get("text")),
            description=("description+lists+additional", description),
            employment_type=("categories.commitment", category.get("commitment")),
            country_codes=("country", p.get("country")),
            location=("categories.location", category.get("location")),
            salary=("salaryRange", compensation),
            application_url=("applyUrl", p.get("applyUrl")),
        )


class SmartRecruitersConnector(BaseConnector):
    source_type = "smartrecruiters"

    def discover(self, query="", tenant="", cursor=None):
        try:
            offset = int(cursor or "0")
            if not 0 <= offset <= 10000:
                raise ValueError("invalid cursor")
            url = f"https://api.smartrecruiters.com/v1/companies/{token(tenant)}/postings?" + urlencode(
                {"offset": offset, "limit": 100, "q": query}
            )
            _, body = self._json(url)
            postings = body["content"]
            candidates = [
                Candidate(
                    source_type=self.source_type,
                    tenant=tenant,
                    external_id=j["id"],
                    source_url=j.get("ref")
                    or f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings/{j['id']}",
                    employer_name=self.employer_name or tenant,
                    title=j.get("name"),
                    payload=j,
                )
                for j in postings
            ]
            self._success()
            more = offset + len(postings) < body.get("totalFound", len(postings))
            return DiscoverResult(
                candidates=candidates,
                next_cursor=str(offset + len(postings)) if more and postings else None,
                coverage={"board_only": True, "raw_count": len(postings), "complete_listing": not more},
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            error = source_error(exc)
            self._failure(error)
            return DiscoverResult(errors=[error], coverage={"complete_listing": False})

    def fetch(self, candidate):
        try:
            url = f"https://api.smartrecruiters.com/v1/companies/{token(candidate.tenant)}/postings/{token(candidate.external_id)}"
            result, p = self._json(url)
            if str(p.get("id")) != candidate.external_id:
                raise SourceHTTPError("IDENTITY_MISMATCH", "Source detail identifies another opening")
            if p.get("active") is False:
                raise SourceHTTPError("NOT_ACTIVE", "Source explicitly identifies an inactive opening", status=404)
            sections = p.get("jobAd", {}).get("sections", {})
            return self._fetched(
                candidate, p, complete=bool(sections.get("jobDescription", {}).get("text")), url=result.final_url
            )
        except (SourceHTTPError, ValueError, KeyError, TypeError) as exc:
            return self._fetch_failed(candidate, exc)

    def verify_opening(self, job_source):
        # SmartRecruiters-hosted job pages render client-side; the public postings API is the
        # authoritative opening state: an active posting with an applyUrl is live, a 404 or
        # active=false is closed.
        target = job_source.application_url
        try:
            url = (
                f"https://api.smartrecruiters.com/v1/companies/{token(job_source.tenant)}/postings/"
                f"{token(job_source.external_id)}"
            )
            result, p = self._json(url)
        except SourceHTTPError as exc:
            if exc.status in (404, 410):
                return OpeningVerification(
                    status="CLOSED",
                    application_url=target,
                    evidence_text="SmartRecruiters postings API no longer lists this posting id",
                    http_status=exc.status,
                )
            return OpeningVerification(
                status="UNKNOWN", application_url=target, evidence_text=exc.code, http_status=exc.status
            )
        except (ValueError, KeyError, TypeError):
            return OpeningVerification(status="UNKNOWN", application_url=target, evidence_text="Detail unreadable")
        identity = str(p.get("id")) == str(job_source.external_id)
        if identity and p.get("active") is False:
            return OpeningVerification(
                status="CLOSED",
                identity_match=True,
                application_url=target,
                final_url=result.final_url,
                evidence_text="SmartRecruiters postings API marks the posting inactive",
                http_status=result.status_code,
            )
        apply_url = p.get("applyUrl") or target
        if identity and p.get("active") is not False and apply_url:
            return OpeningVerification(
                status="ACTIVE",
                identity_match=True,
                actionable=True,
                application_url=apply_url,
                final_url=result.final_url,
                evidence_text=f"SmartRecruiters postings API lists posting {job_source.external_id} as active with an apply URL",
                http_status=result.status_code,
            )
        return OpeningVerification(
            status="UNKNOWN",
            identity_match=identity,
            application_url=target,
            final_url=result.final_url,
            evidence_text="SmartRecruiters detail did not confirm identity and an apply URL",
            http_status=result.status_code,
        )

    def normalize(self, payload):
        p = payload.payload
        sections = p.get("jobAd", {}).get("sections", {})
        description = "\n".join(
            "<h2>" + html.escape(section.get("title", name)) + "</h2>" + section.get("text", "")
            for name, section in sections.items()
            if isinstance(section, dict)
        )
        loc = p.get("location") or {}
        code = country(loc.get("country"))
        pub = publication(p.get("releasedDate"), "releasedDate", "LAST_PUBLICATION")
        job = self._base_job(
            payload,
            title=p.get("name"),
            description=description,
            employer=p.get("company", {}).get("name"),
            application_url=p.get("applyUrl"),
            employer_url=p.get("postingUrl") or p.get("jobAd", {}).get("url"),
            requisition_id=p.get("refNumber"),
            source_active=p.get("active"),
            locations=[", ".join(str(loc[k]) for k in ["city", "region", "country"] if loc.get(k))],
            country_codes=[code] if code else [],
            workplace_states=[loc["region"]] if loc.get("region") else [],
            employment_type=employment(p.get("typeOfEmployment", {}).get("label")),
            publication=pub,
            last_published_at=exact_time(p.get("releasedDate")),
            warnings=["LAST_PUBLICATION_REQUIRES_REPOST_CHECK"],
        )
        return self._evidence(
            job,
            title=("name", p.get("name")),
            description=("jobAd.sections", sections),
            country_codes=("location.country", loc.get("country")),
            employment_type=("typeOfEmployment.label", p.get("typeOfEmployment", {}).get("label")),
            publication=("releasedDate", p.get("releasedDate")),
            application_url=("applyUrl", p.get("applyUrl")),
        )
