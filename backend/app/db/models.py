"""PostgreSQL authoritative data model. Historical evidence uses restrictive FKs."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ID:
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)


class Created:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(ID, Created, Base):
    __tablename__ = "users"
    google_subject: Mapped[str] = mapped_column(String(255), unique=True)
    verified_email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    timezone: Mapped[str] = mapped_column(String(80), default="America/New_York")
    cycle_anchor: Mapped[date | None] = mapped_column(Date)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)


class Device(ID, Created, Base):
    __tablename__ = "devices"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    platform: Mapped[str] = mapped_column(String(30))
    app_version: Mapped[str] = mapped_column(String(50), default="")
    device_label: Mapped[str] = mapped_column(String(255), default="")
    push_token_encrypted: Mapped[str | None] = mapped_column(Text)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_cursor: Mapped[int] = mapped_column(BigInteger, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class AppSession(ID, Created, Base):
    __tablename__ = "app_sessions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"))
    refresh_token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    access_token_hash: Mapped[str | None] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginIntent(ID, Created, Base):
    __tablename__ = "login_intents"
    device_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    purpose: Mapped[str] = mapped_column(String(30), default="LOGIN")
    selected_label: Mapped[str | None] = mapped_column(String(255))
    state_hash: Mapped[str] = mapped_column(String(128), unique=True)
    challenge: Mapped[str] = mapped_column(String(255))
    nonce: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(30))
    device_label: Mapped[str] = mapped_column(String(255), default="")
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    code_verifier_encrypted: Mapped[str | None] = mapped_column(Text)


class SearchProfile(ID, Created, Base):
    __tablename__ = "search_profiles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    role_families: Mapped[list] = mapped_column(JSONB, default=list)
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    aliases: Mapped[dict] = mapped_column(JSONB, default=dict)
    geography: Mapped[list] = mapped_column(JSONB, default=lambda: ["USA"])
    work_arrangements: Mapped[list] = mapped_column(JSONB, default=lambda: ["REMOTE", "HYBRID", "ONSITE"])
    salary_preferences: Mapped[dict] = mapped_column(
        JSONB, default=lambda: {"preferred_usd": 80000, "undisclosed_allowed": True, "lower_allowed": True}
    )
    ruleset_version: Mapped[str] = mapped_column(String(80), default="1.0")


class SearchProfileVersion(ID, Created, Base):
    __tablename__ = "search_profile_versions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (UniqueConstraint("user_id", "version"),)


class EmployerGroup(ID, Created, Base):
    __tablename__ = "employer_groups"
    canonical_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    grouping_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    pool_tags: Mapped[list] = mapped_column(JSONB, default=list)


class EmployerBrand(ID, Base):
    __tablename__ = "employer_brands"
    group_id: Mapped[UUID] = mapped_column(ForeignKey("employer_groups.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    canonical_domain: Mapped[str | None] = mapped_column(String(255))


class EmployerEntity(ID, Base):
    __tablename__ = "employer_entities"
    group_id: Mapped[UUID] = mapped_column(ForeignKey("employer_groups.id"), index=True)
    brand_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_brands.id"))
    legal_name: Mapped[str] = mapped_column(String(255), index=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(255))
    address_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)


class EmployerAlias(ID, Base):
    __tablename__ = "employer_aliases"
    group_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_groups.id"))
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_entities.id"))
    normalized_alias: Mapped[str] = mapped_column(String(255), index=True)
    alias_type: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[dict] = mapped_column(JSONB)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewer: Mapped[str] = mapped_column(String(255))


class EVerifyEvidence(ID, Base):
    __tablename__ = "everify_evidence"
    entity_id: Mapped[UUID] = mapped_column(ForeignKey("employer_entities.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    legal_name_as_found: Mapped[str] = mapped_column(String(255))
    source_reference: Mapped[str] = mapped_column(Text)
    snapshot: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recheck_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    verification_method: Mapped[str] = mapped_column(String(80))
    reviewer: Mapped[str] = mapped_column(String(255))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("status IN ('CONFIRMED','UNKNOWN','CONFLICTING','NO_LONGER_CONFIRMED')", name="everify_status"),
        CheckConstraint(
            "status != 'CONFIRMED' OR (length(source_reference)>0 AND length(snapshot)>0 AND length(content_hash)=64 AND length(reviewer)>0)",
            name="everify_proof",
        ),
    )


class SourceRegistry(ID, Created, Base):
    __tablename__ = "source_registry"
    connector_type: Mapped[str] = mapped_column(String(80))
    tenant: Mapped[str] = mapped_column(String(255))
    employer_group_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_groups.id"))
    board_identifier: Mapped[str | None] = mapped_column(String(255))
    career_url: Mapped[str | None] = mapped_column(Text)
    geography: Mapped[list] = mapped_column(JSONB, default=list)
    pool_tags: Mapped[list] = mapped_column(JSONB, default=list)
    configuration_state: Mapped[str] = mapped_column(String(40), default="NOT_CONFIGURED")
    capabilities: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        UniqueConstraint("connector_type", "tenant"),
        CheckConstraint("connector_type != 'linkedin'", name="no_linkedin_source"),
    )


class WatchlistEntry(ID, Created, Base):
    __tablename__ = "watchlist_entries"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    employer_group_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_groups.id"))
    requested_name: Mapped[str | None] = mapped_column(String(255))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("user_id", "employer_group_id"),
        CheckConstraint(
            "employer_group_id IS NOT NULL OR (requested_name IS NOT NULL AND length(requested_name) > 0)",
            name="watchlist_resolvable_identity",
        ),
    )


class Job(ID, Base):
    __tablename__ = "jobs"
    employer_group_id: Mapped[UUID] = mapped_column(ForeignKey("employer_groups.id"), index=True)
    entity_id: Mapped[UUID | None] = mapped_column(ForeignKey("employer_entities.id"))
    title: Mapped[str] = mapped_column(Text)
    locations: Mapped[list] = mapped_column(JSONB, default=list)
    work_arrangement: Mapped[str | None] = mapped_column(String(30))
    requisition_id: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    published_earliest: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_latest: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publication_precision: Mapped[str] = mapped_column(String(40), default="UNKNOWN")
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    availability: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    current_snapshot_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("job_snapshots.id", use_alter=True, name="fk_job_current_snapshot")
    )
    canonical_redirect_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"))
    salary_min: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_max: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    salary_currency: Mapped[str | None] = mapped_column(String(5))
    salary_interval: Mapped[str | None] = mapped_column(String(30))
    priority_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    role_family: Mapped[str | None] = mapped_column(String(100))
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (
        CheckConstraint("availability IN ('ACTIVE','CLOSED','UNKNOWN')", name="job_availability"),
        CheckConstraint("canonical_redirect_id IS NULL OR canonical_redirect_id != id", name="no_self_redirect"),
    )


class JobSource(ID, Base):
    __tablename__ = "job_sources"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_registry_id: Mapped[UUID] = mapped_column(ForeignKey("source_registry.id"))
    external_id: Mapped[str | None] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(Text)
    employer_url: Mapped[str | None] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    final_observed_url: Mapped[str | None] = mapped_column(Text)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_verified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    availability: Mapped[str] = mapped_column(String(30), default="UNKNOWN")
    link_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("source_registry_id", "external_id"),)


class JobSnapshot(ID, Base):
    __tablename__ = "job_snapshots"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    source_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_sources.id"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    structured_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    description: Mapped[str] = mapped_column(Text)
    raw_evidence_reference: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    content_complete: Mapped[bool] = mapped_column(Boolean, default=False)


class JobFact(ID, Base):
    __tablename__ = "job_facts"
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"), index=True)
    field: Mapped[str] = mapped_column(String(80))
    value: Mapped[dict] = mapped_column(JSONB)
    fact_state: Mapped[str] = mapped_column(String(30))
    requiredness: Mapped[str | None] = mapped_column(String(40))
    polarity: Mapped[str | None] = mapped_column(String(30))
    evidence: Mapped[dict] = mapped_column(JSONB)
    extractor_version: Mapped[str] = mapped_column(String(80))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class JobEvaluation(ID, Base):
    __tablename__ = "job_evaluations"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"))
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    ruleset_version: Mapped[str] = mapped_column(String(80))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    decision: Mapped[str] = mapped_column(String(30))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        CheckConstraint("decision IN ('ELIGIBLE','INELIGIBLE','NEEDS_REVIEW')", name="evaluation_decision"),
    )


class RuleResult(ID, Base):
    __tablename__ = "rule_results"
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("job_evaluations.id"), index=True)
    rule_code: Mapped[str] = mapped_column(String(80))
    rule_version: Mapped[str] = mapped_column(String(80))
    decision: Mapped[str] = mapped_column(String(30))
    reason_code: Mapped[str] = mapped_column(String(100))
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    __table_args__ = (CheckConstraint("decision IN ('PASS','FAIL','UNKNOWN','REVIEW')", name="rule_decision"),)


class DuplicateLink(ID, Created, Base):
    __tablename__ = "duplicate_links"
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    canonical_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    link_type: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSONB)
    mechanism: Mapped[str] = mapped_column(String(255))
    reversed_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("duplicate_links.id"))
    __table_args__ = (CheckConstraint("candidate_id != canonical_id", name="no_self_duplicate"),)


class JobIdentityTombstone(ID, Created, Base):
    __tablename__ = "job_identity_tombstones"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    identity_type: Mapped[str] = mapped_column(String(40))
    identity_key: Mapped[str] = mapped_column(Text, unique=True)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)


class UserJobState(ID, Base):
    __tablename__ = "user_job_state"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_saved: Mapped[bool] = mapped_column(Boolean, default=False)
    saved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (
        UniqueConstraint("user_id", "job_id"),
        Index("ix_saved_user", "user_id", "is_saved"),
    )


class UserJobEvent(ID, Base):
    __tablename__ = "user_job_events"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    event_type: Mapped[str] = mapped_column(String(50))
    before: Mapped[dict] = mapped_column(JSONB, default=dict)
    after: Mapped[dict] = mapped_column(JSONB, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    operation_id: Mapped[str] = mapped_column(String(128))
    actor: Mapped[str] = mapped_column(String(40), default="USER")
    correction_of_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_job_events.id"))


class SavedJobVersion(ID, Base):
    __tablename__ = "saved_job_versions"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_job_events.id"))


class CompanyCycle(ID, Base):
    __tablename__ = "company_cycles"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    cycle_index: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    anchor_date: Mapped[date] = mapped_column(Date)
    __table_args__ = (
        UniqueConstraint("user_id", "cycle_index"),
        CheckConstraint("end_date > start_date", name="cycle_interval"),
    )


class Report(ID, Base):
    __tablename__ = "reports"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    report_date: Mapped[date] = mapped_column(Date)
    cycle_id: Mapped[UUID] = mapped_column(ForeignKey("company_cycles.id"))
    intended_release: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actual_release: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="BUILDING")
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("user_id", "report_date"),)


class ReportJob(ID, Base):
    __tablename__ = "report_jobs"
    report_id: Mapped[UUID] = mapped_column(ForeignKey("reports.id"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    snapshot_id: Mapped[UUID] = mapped_column(ForeignKey("job_snapshots.id"))
    selection_band: Mapped[str] = mapped_column(String(1))
    selection_order: Mapped[int] = mapped_column(Integer)
    evaluation_id: Mapped[UUID] = mapped_column(ForeignKey("job_evaluations.id"))
    __table_args__ = (
        UniqueConstraint("report_id", "job_id"),
        UniqueConstraint("report_id", "selection_order"),
        CheckConstraint("selection_order >= 0 AND selection_order < 50", name="report_slot_limit"),
    )


class CompanyCycleUsage(ID, Base):
    __tablename__ = "company_cycle_usage"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    cycle_id: Mapped[UUID] = mapped_column(ForeignKey("company_cycles.id"))
    employer_group_id: Mapped[UUID] = mapped_column(ForeignKey("employer_groups.id"))
    report_id: Mapped[UUID] = mapped_column(ForeignKey("reports.id"))
    report_date: Mapped[date] = mapped_column(Date)
    count: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        UniqueConstraint("user_id", "cycle_id", "employer_group_id"),
        CheckConstraint("count >= 1 AND count <= 2", name="company_daily_limit"),
    )


class InitialDelivery(ID, Base):
    __tablename__ = "initial_deliveries"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    channel: Mapped[str] = mapped_column(String(15))
    report_id: Mapped[UUID | None] = mapped_column(ForeignKey("reports.id"))
    snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_snapshots.id"))
    alert_reference: Mapped[str | None] = mapped_column(String(255))
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        UniqueConstraint("user_id", "job_id"),
        CheckConstraint("channel IN ('DAILY','PRIORITY')", name="delivery_channel"),
    )


class Application(ID, Base):
    __tablename__ = "applications"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id"))
    title: Mapped[str] = mapped_column(Text)
    company: Mapped[str] = mapped_column(Text)
    application_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    external_identity: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    applied_date_source: Mapped[str] = mapped_column(String(30), default="USER")
    current_status: Mapped[str] = mapped_column(String(30), default="APPLIED")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    selected_snapshot_id: Mapped[UUID | None] = mapped_column(ForeignKey("job_snapshots.id"))
    manual_description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    added_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        Index(
            "uq_active_application_job",
            "user_id",
            "job_id",
            unique=True,
            postgresql_where=text("voided_at IS NULL AND job_id IS NOT NULL"),
        ),
        Index(
            "uq_active_application_external",
            "user_id",
            "external_identity",
            unique=True,
            postgresql_where=text("voided_at IS NULL AND external_identity IS NOT NULL"),
        ),
        CheckConstraint(
            "current_status IN ('APPLIED','ASSESSMENT','INTERVIEWING','OFFER','REJECTED','WITHDRAWN','POSITION_CLOSED')",
            name="application_status",
        ),
    )


class ApplicationEvent(ID, Base):
    __tablename__ = "application_events"
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(30))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(30), default="USER")
    source_reference: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    operation_id: Mapped[str] = mapped_column(String(128))
    correction_of_event_id: Mapped[UUID | None] = mapped_column(ForeignKey("application_events.id"))
    __table_args__ = (UniqueConstraint("application_id", "operation_id"),)


class Person(ID, Base):
    __tablename__ = "people"
    linkedin_url: Mapped[str] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(String(255))
    headline: Mapped[str] = mapped_column(Text, default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    employment_evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JobPerson(ID, Base):
    __tablename__ = "job_people"
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"))
    person_id: Mapped[UUID] = mapped_column(ForeignKey("people.id"))
    relationship_group: Mapped[str] = mapped_column(String(80))
    evidence_classification: Mapped[str] = mapped_column(String(30))
    supporting_references: Mapped[list] = mapped_column(JSONB, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("job_id", "person_id"),)


class EnrichmentRun(ID, Base):
    __tablename__ = "enrichment_runs"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    job_id: Mapped[UUID] = mapped_column(ForeignKey("jobs.id"), index=True)
    state: Mapped[str] = mapped_column(String(40))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    discovered_count: Mapped[int] = mapped_column(Integer, default=0)
    approved_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_units: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0)
    last_error: Mapped[str | None] = mapped_column(Text)


class GmailConnection(ID, Created, Base):
    __tablename__ = "gmail_connections"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), unique=True)
    google_identity: Mapped[str] = mapped_column(String(320))
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    granted_scopes: Mapped[list] = mapped_column(JSONB, default=list)
    selected_label: Mapped[str | None] = mapped_column(String(255))
    sync_health: Mapped[str] = mapped_column(String(40), default="NOT_CONFIGURED")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GmailSyncState(ID, Base):
    __tablename__ = "gmail_sync_state"
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("gmail_connections.id"), unique=True)
    history_cursor: Mapped[str | None] = mapped_column(String(255))
    reconciliation_progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    watch_expiry: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailMessage(ID, Base):
    __tablename__ = "email_messages"
    connection_id: Mapped[UUID] = mapped_column(ForeignKey("gmail_connections.id"))
    gmail_message_id: Mapped[str] = mapped_column(String(255))
    thread_id: Mapped[str] = mapped_column(String(255), index=True)
    sender: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    classification: Mapped[str] = mapped_column(String(50))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (UniqueConstraint("connection_id", "gmail_message_id"),)


class EmailApplicationLink(ID, Base):
    __tablename__ = "email_application_links"
    email_id: Mapped[UUID] = mapped_column(ForeignKey("email_messages.id"))
    application_id: Mapped[UUID] = mapped_column(ForeignKey("applications.id"))
    match_state: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("application_events.id"))
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("email_id", "application_id"),)


class ReviewItem(ID, Created, Base):
    __tablename__ = "review_items"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    review_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="OPEN")
    admin_only: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[dict] = mapped_column(JSONB, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Notification(ID, Created, Base):
    __tablename__ = "notifications"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    notification_type: Mapped[str] = mapped_column(String(50))
    target_type: Mapped[str] = mapped_column(String(30))
    target_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    event_dedupe_key: Mapped[str] = mapped_column(String(255))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (
        UniqueConstraint("user_id", "event_dedupe_key"),
        Index("ix_unread_notifications", "user_id", "read_at"),
        CheckConstraint(
            "target_type IN ('jobs','applications','reviews','reports','search-runs')", name="notification_target"
        ),
    )


class NotificationDelivery(ID, Base):
    __tablename__ = "notification_deliveries"
    notification_id: Mapped[UUID] = mapped_column(ForeignKey("notifications.id"))
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"))
    channel: Mapped[str] = mapped_column(String(30))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(30), default="PENDING")
    last_attempt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_reference: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("notification_id", "device_id", "channel"),)


class SearchRun(ID, Base):
    __tablename__ = "search_runs"
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_version: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(30), default="RUNNING")
    counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)


class ConnectorRun(ID, Base):
    __tablename__ = "connector_runs"
    search_run_id: Mapped[UUID] = mapped_column(ForeignKey("search_runs.id"))
    source_registry_id: Mapped[UUID] = mapped_column(ForeignKey("source_registry.id"))
    query: Mapped[dict] = mapped_column(JSONB, default=dict)
    pool: Mapped[str | None] = mapped_column(String(80))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor: Mapped[str | None] = mapped_column(Text)
    counts: Mapped[dict] = mapped_column(JSONB, default=dict)
    errors: Mapped[list] = mapped_column(JSONB, default=list)
    health: Mapped[str] = mapped_column(String(40))
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)


class WorkItem(ID, Created, Base):
    __tablename__ = "work_items"
    task_key: Mapped[str] = mapped_column(String(255), unique=True)
    task_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    last_error: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(ID, Created, Base):
    __tablename__ = "outbox_events"
    event_key: Mapped[str] = mapped_column(String(255), unique=True)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    state: Mapped[str] = mapped_column(String(30), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_owner: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ProcessedOperation(ID, Created, Base):
    __tablename__ = "processed_operations"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    operation_id: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[dict] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("user_id", "operation_id"),)


class UserChange(Base):
    __tablename__ = "user_changes"
    cursor: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    revision: Mapped[int] = mapped_column(Integer)
    tombstone: Mapped[bool] = mapped_column(Boolean, default=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_user_change_cursor", "user_id", "cursor"),)


class SyncSnapshot(ID, Created, Base):
    """Short-lived immutable initial sync payload, paginated without open transactions."""

    __tablename__ = "sync_snapshots"
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    boundary_cursor: Mapped[int] = mapped_column(BigInteger)
    items: Mapped[list] = mapped_column(JSONB, default=list)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PeopleSearchCache(ID, Base):
    __tablename__ = "people_search_cache"
    query_hash: Mapped[str] = mapped_column(String(64), unique=True)
    query_text: Mapped[str] = mapped_column(Text)
    result_payload: Mapped[dict] = mapped_column(JSONB)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
