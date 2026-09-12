from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from urllib.parse import urlsplit

from .contracts import (
    FetchResult,
    FieldEvidence,
    Health,
    NormalizedJob,
    OpeningVerification,
    SourceError,
    utcnow,
)
from .parsing import readable_html, sanitized_html
from .safe_http import SafeHTTPClient, SourceHTTPError, validate_url


def validate_job_url(url):
    validate_url(url)
    host = (urlsplit(url).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        raise SourceHTTPError("DISABLED_SOURCE", "LinkedIn job sourcing is disabled by product policy")


def source_error(exc) -> SourceError:
    if isinstance(exc, SourceHTTPError):
        return SourceError(
            code=exc.code,
            message=str(exc),
            http_status=exc.status,
            retryable=exc.retryable,
            retry_after=exc.retry_after,
        )
    return SourceError(code="MALFORMED_SOURCE", message="Source payload did not match the documented contract")


def token(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", value):
        raise SourceHTTPError("INVALID_TENANT", "Source board/tenant identifier is invalid")
    return value


class BaseConnector:
    source_type = "unknown"

    def __init__(self, client: SafeHTTPClient | None = None, *, employer_name: str | None = None):
        self.client = client or SafeHTTPClient()
        self.employer_name = employer_name
        self._health = Health(source_type=self.source_type, state="DEGRADED")

    def health(self) -> Health:
        return self._health.model_copy(deep=True)

    def _success(self):
        self._health = Health(source_type=self.source_type, state="HEALTHY", last_success_at=utcnow())

    def _failure(self, error):
        state = {403: "BLOCKED", 429: "RATE_LIMITED"}.get(error.http_status, "FAILED")
        self._health = Health(
            source_type=self.source_type,
            state=state,
            last_success_at=self._health.last_success_at,
            last_error=error,
            retry_after=error.retry_after,
        )

    def _json(self, url, *, headers=None, body=None):
        result = (
            self.client.get(url, headers=headers) if body is None else self.client.post_json(url, body, headers=headers)
        )
        if not 200 <= result.status_code < 300:
            retry_after = None
            if result.status_code == 429:
                retry_after = utcnow() + timedelta(
                    seconds=SafeHTTPClient._retry_delay(result.headers.get("retry-after"), 0)
                )
            raise SourceHTTPError(
                "SOURCE_HTTP_ERROR",
                "Source returned HTTP " + str(result.status_code),
                status=result.status_code,
                retryable=result.status_code == 429 or result.status_code >= 500,
                retry_after=retry_after,
            )
        return result, result.json()

    def _fetched(self, candidate, payload, *, complete, url=None, status=200):
        self._success()
        return FetchResult(
            candidate=candidate,
            outcome="SUCCESS",
            payload=payload,
            description_complete=complete,
            source_url=candidate.source_url,
            final_url=url or candidate.source_url,
            http_status=status,
            raw_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest(),
        )

    def _fetch_failed(self, candidate, exc):
        error = source_error(exc)
        if error.http_status in {404, 410}:
            self._success()  # One explicitly removed opening does not make its provider unhealthy.
        else:
            self._failure(error)
        return FetchResult(
            candidate=candidate,
            outcome="CLOSED" if error.http_status in {404, 410} else "FAILED",
            source_url=candidate.source_url,
            errors=[error],
            http_status=error.http_status,
        )

    def _base_job(self, fetched: FetchResult, *, title, description, employer=None, application_url=None, **kwargs):
        if fetched.outcome != "SUCCESS":
            raise ValueError("Failed source retrieval cannot become a normalized complete job")
        text = readable_html(description or "")
        c = fetched.candidate
        for url in [c.source_url, application_url, kwargs.get("employer_url")]:
            if url:
                validate_job_url(url)
        return NormalizedJob(
            source_type=self.source_type,
            tenant=c.tenant,
            external_id=c.external_id,
            employer_name=employer or c.employer_name or self.employer_name or c.tenant,
            title=title or c.title or "",
            description_text=text,
            description_html=sanitized_html(description or ""),
            description_complete=fetched.description_complete and bool(text),
            source_url=c.source_url,
            final_url=fetched.final_url,
            application_url=application_url,
            fetched_at=fetched.fetched_at,
            raw_sha256=fetched.raw_sha256,
            **kwargs,
        )

    @staticmethod
    def _evidence(job: NormalizedJob, **values):
        for field, (path, value) in values.items():
            if value is not None:
                job.field_evidence[field] = [
                    FieldEvidence(field_path=path, value=value, source_url=job.source_url, observed_at=job.fetched_at)
                ]
        return job

    def verify_opening(self, job_source: NormalizedJob) -> OpeningVerification:
        target = job_source.application_url
        if job_source.source_active is False or job_source.valid_through and job_source.valid_through < utcnow():
            return OpeningVerification(
                status="CLOSED",
                application_url=target,
                evidence_text="Structured source states inactive or application deadline has passed",
            )
        if not target:
            return OpeningVerification(
                status="UNKNOWN", evidence_text="Source did not supply an application destination"
            )
        try:
            validate_job_url(target)
            result = self.client.get(target)
        except SourceHTTPError as exc:
            return OpeningVerification(status="UNKNOWN", application_url=target, evidence_text=exc.code)
        if result.status_code in {404, 410}:
            return OpeningVerification(
                status="CLOSED",
                application_url=target,
                final_url=result.final_url,
                evidence_text="Application destination returned an explicit missing/gone status",
                http_status=result.status_code,
            )
        if result.status_code != 200:
            return OpeningVerification(
                status="UNKNOWN",
                application_url=target,
                final_url=result.final_url,
                evidence_text="Application destination is temporarily unverifiable",
                http_status=result.status_code,
            )
        visible = readable_html(result.text)
        if re.search(
            r"\b(this (job|position|opening) (is (now )?closed|has been filled|is no longer available)|"
            r"no longer accepting applications|job (not found|has expired))\b",
            visible,
            re.IGNORECASE,
        ):
            return OpeningVerification(
                status="CLOSED",
                application_url=target,
                final_url=result.final_url,
                evidence_text="Posting explicitly says it is closed or unavailable",
                http_status=200,
            )
        before, after = urlsplit(target), urlsplit(result.final_url)
        generic = after.path.rstrip("/").lower() in {"", "/jobs", "/careers", "/careers/search", "/search"}
        if before.path != after.path and job_source.external_id not in result.final_url:
            generic = True
        identity = not generic and bool(job_source.title) and job_source.title.casefold() in visible.casefold()
        actionable = identity and bool(
            re.search(r"\b(apply( now| for| to)?|application|submit application)\b", visible, re.IGNORECASE)
        )
        return OpeningVerification(
            status="ACTIVE" if identity and actionable else "UNKNOWN",
            identity_match=identity,
            actionable=actionable,
            generic_careers_redirect=generic,
            application_url=target,
            final_url=result.final_url,
            http_status=200,
            evidence_text="Specific opening identity and application action present"
            if actionable
            else "HTTP success alone does not establish an active application path",
        )
