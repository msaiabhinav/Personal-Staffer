"""Versioned evidence contracts. Facts describe sources; rules describe policy."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class FactState(StrEnum):
    KNOWN = "KNOWN"
    NOT_STATED = "NOT_STATED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"


class RuleDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    REVIEW = "REVIEW"


class FinalDecision(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(Contract):
    snapshot_id: str
    source_url: str | None = None
    field_path: str | None = None
    text: str | None = None
    start: int | None = None
    end: int | None = None
    observed_at: AwareDatetime


class Fact(Contract):
    field: str
    state: FactState
    value: Any = None
    requiredness: Literal["REQUIRED", "PREFERRED", "NOT_REQUIRED", "UNKNOWN"] = "UNKNOWN"
    polarity: Literal["POSITIVE", "NEGATIVE", "UNKNOWN"] = "UNKNOWN"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    extractor_version: str = "deterministic-1.0"


class RuleResult(Contract):
    rule: str
    decision: RuleDecision
    reason_code: str
    message: str
    evidence: list[EvidenceRef] = Field(default_factory=list)
    rule_version: str = "1.0"
    flags: list[str] = Field(default_factory=list)


class PublicationEvidence(Contract):
    earliest: AwareDatetime | None = None
    latest: AwareDatetime | None = None
    precision: Literal["EXACT", "DATE", "ROUNDED", "UNKNOWN"] = "UNKNOWN"
    kind: Literal["ORIGINAL", "LAST_PUBLICATION", "UPDATED", "FIRST_SEEN", "UNKNOWN"] = "UNKNOWN"
    source_timezone: str | None = None
    source_field: str | None = None
    # Last-publication evidence is usable only after independent identity/repost checks.
    repost_checked: bool = False

    @model_validator(mode="after")
    def valid_interval(self):
        if (self.earliest is None) != (self.latest is None):
            raise ValueError("publication interval requires both endpoints")
        if self.earliest and self.latest and self.earliest > self.latest:
            raise ValueError("publication interval endpoints are reversed")
        if self.precision == "EXACT" and self.earliest != self.latest:
            raise ValueError("exact publication must have identical endpoints")
        return self


class EVerifyEvidence(Contract):
    status: Literal["CONFIRMED", "UNKNOWN", "CONFLICTING", "NO_LONGER_CONFIRMED"] = "UNKNOWN"
    legal_entity_id: str | None = None
    legal_name: str | None = None
    source_reference: str | None = None
    evidence_hash: str | None = None
    checked_at: AwareDatetime | None = None
    recheck_due_at: AwareDatetime | None = None
    method: str | None = None
    reviewer: str | None = None
    identity_match: bool = False
    synthetic: bool = False


class OpeningEvidence(Contract):
    status: Literal["ACTIVE", "CLOSED", "UNKNOWN"] = "UNKNOWN"
    application_url: str | None = None
    final_url: str | None = None
    identity_match: bool = False
    actionable: bool = False
    generic_careers_redirect: bool = False
    checked_at: AwareDatetime | None = None
    evidence_text: str | None = None
    http_status: int | None = None


class Salary(Contract):
    minimum: Decimal | None = Field(default=None, ge=0)
    maximum: Decimal | None = Field(default=None, ge=0)
    currency: str | None = None
    interval: str | None = None
    source: str | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("salary minimum exceeds maximum")
        return self


class JobEvidence(Contract):
    id: str
    title: str
    description: str
    description_complete: bool = False
    snapshot_id: str
    source_url: str
    fetched_at: AwareDatetime
    employer_group_id: str | None = None
    legal_entity_id: str | None = None
    country_codes: list[str] = Field(default_factory=list)
    country_conflicting: bool = False
    country_evidence: str | None = None
    employment_type: str | None = None
    employment_evidence: str | None = None
    work_arrangement: Literal["REMOTE", "HYBRID", "ONSITE", "UNKNOWN"] = "UNKNOWN"
    workplace_states: list[str] = Field(default_factory=list)
    explicit_remote_states: list[str] = Field(default_factory=list)
    staffing: bool = False
    permanent_placement: bool | None = None
    payroll_entity_verified: bool = False
    publication: PublicationEvidence = Field(default_factory=PublicationEvidence)
    first_seen_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    known_repost: bool = False
    everify: EVerifyEvidence = Field(default_factory=EVerifyEvidence)
    opening: OpeningEvidence = Field(default_factory=OpeningEvidence)
    salary: Salary = Field(default_factory=Salary)
    watchlisted: bool = False
    university: bool = False
    academic_medical_center: bool = False
    startup_pool: Literal["NYC", "BAY_AREA"] | None = None
    synthetic: bool = False


class Policy(Contract):
    version: str = "spec-1.0-policy-1.0"
    max_posting_age_hours: int = Field(default=72, ge=1, le=72)
    clock_tolerance_seconds: int = Field(default=300, ge=0, le=300)
    everify_recheck_days: int = Field(default=30, ge=1)
    opening_recheck_hours: int = Field(default=24, ge=1)
    preferred_salary_usd: Decimal = Decimal(80000)
    maximum_exact_experience: Decimal = Decimal(4)
    plus_exclusion_start: Decimal = Decimal(4)
    maximum_range_policy: bool = True
    experience_not_stated: Literal["REVIEW"] = "REVIEW"
    skill_vocabulary: list[str] | None = None


class RelevanceResult(Contract):
    relevant: bool | None
    families: list[str] = Field(default_factory=list)
    responsibility_evidence: list[str] = Field(default_factory=list)
    direct_skills: list[str] = Field(default_factory=list)
    related_skills: dict[str, list[str]] = Field(default_factory=dict)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    missing_requested_skills: list[str] = Field(default_factory=list)
    original_vocabulary: list[str] = Field(default_factory=list)
    summary: str = ""
    reason: str = ""
    version: str = "relevance-1.0"


class Evaluation(Contract):
    job_id: str
    snapshot_id: str
    decision: FinalDecision
    ruleset_version: str
    evaluated_at: AwareDatetime
    valid_until: AwareDatetime | None
    rules: list[RuleResult]
    facts: list[Fact]
    salary_band: Literal["A", "B", "C"]
    priority_reasons: list[str]
    relevance: RelevanceResult
    synthetic: bool = False

    @property
    def reason_codes(self) -> list[str]:
        return [rule.reason_code for rule in self.rules if rule.decision != RuleDecision.PASS]
