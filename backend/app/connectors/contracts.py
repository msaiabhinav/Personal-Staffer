"""Typed, evidence-preserving connector boundary, version 1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.eligibility.models import PublicationEvidence, Salary


def utcnow() -> datetime:
    return datetime.now(UTC)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceError(Model):
    code: str
    message: str
    retryable: bool = False
    http_status: int | None = None
    retry_after: AwareDatetime | None = None


class Health(Model):
    source_type: str
    state: Literal["NOT_CONFIGURED", "HEALTHY", "DEGRADED", "RATE_LIMITED", "BLOCKED", "FAILED"]
    last_success_at: AwareDatetime | None = None
    last_error: SourceError | None = None
    retry_after: AwareDatetime | None = None


class Candidate(Model):
    source_type: str
    tenant: str
    external_id: str
    source_url: str
    employer_name: str | None = None
    title: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    discovered_at: AwareDatetime = Field(default_factory=utcnow)


class DiscoverResult(Model):
    candidates: list[Candidate] = Field(default_factory=list)
    next_cursor: str | None = None
    coverage: dict[str, Any] = Field(default_factory=dict)
    errors: list[SourceError] = Field(default_factory=list)
    source_timestamp: AwareDatetime = Field(default_factory=utcnow)


class FetchResult(Model):
    candidate: Candidate
    outcome: Literal["SUCCESS", "CLOSED", "FAILED", "NOT_CONFIGURED"]
    payload: dict[str, Any] = Field(default_factory=dict)
    description_complete: bool = False
    source_active: bool | None = None
    source_url: str
    final_url: str | None = None
    http_status: int | None = None
    fetched_at: AwareDatetime = Field(default_factory=utcnow)
    errors: list[SourceError] = Field(default_factory=list)
    raw_sha256: str | None = None


class FieldEvidence(Model):
    field_path: str
    value: Any
    source_url: str
    observed_at: AwareDatetime


class NormalizedJob(Model):
    source_type: str
    tenant: str
    external_id: str
    employer_name: str
    title: str
    description_text: str
    # Only sanitized HTML generated from text, never raw executable source HTML.
    description_html: str = ""
    description_complete: bool = False
    source_active: bool | None = None
    valid_through: AwareDatetime | None = None
    source_url: str
    employer_url: str | None = None
    application_url: str | None = None
    final_url: str | None = None
    requisition_id: str | None = None
    locations: list[str] = Field(default_factory=list)
    country_codes: list[str] = Field(default_factory=list)
    workplace_states: list[str] = Field(default_factory=list)
    employment_type: str | None = None
    work_arrangement: Literal["REMOTE", "HYBRID", "ONSITE", "UNKNOWN"] = "UNKNOWN"
    original_published_at: AwareDatetime | None = None
    last_published_at: AwareDatetime | None = None
    source_updated_at: AwareDatetime | None = None
    publication: PublicationEvidence = Field(default_factory=PublicationEvidence)
    fetched_at: AwareDatetime
    salary: Salary = Field(default_factory=Salary)
    field_evidence: dict[str, list[FieldEvidence]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    raw_sha256: str | None = None
    synthetic: bool = False


class OpeningVerification(Model):
    status: Literal["ACTIVE", "CLOSED", "UNKNOWN"]
    identity_match: bool = False
    actionable: bool = False
    application_url: str | None = None
    final_url: str | None = None
    generic_careers_redirect: bool = False
    checked_at: AwareDatetime = Field(default_factory=utcnow)
    evidence_text: str
    http_status: int | None = None


class Connector(Protocol):
    def discover(self, query: str, tenant: str, cursor: str | None = None) -> DiscoverResult: ...
    def fetch(self, candidate: Candidate) -> FetchResult: ...
    def normalize(self, payload: FetchResult) -> NormalizedJob: ...
    def verify_opening(self, job_source: NormalizedJob) -> OpeningVerification: ...
    def health(self) -> Health: ...
