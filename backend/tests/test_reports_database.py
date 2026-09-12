"""Report/ingestion invariants on PostgreSQL + actual migrations, never SQLite.

Tests explicitly skip when TEST_DATABASE_URL is unavailable. All evidence is synthetic.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
import test_database_core
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from test_eligibility_corpus import NOW
from test_pipeline_mapping import normalized, opening

from app.config import Settings
from app.db.models import (
    CompanyCycleUsage,
    DuplicateLink,
    EmployerEntity,
    EmployerGroup,
    EVerifyEvidence,
    InitialDelivery,
    Job,
    JobEvaluation,
    JobSnapshot,
    JobSource,
    Notification,
    OutboxEvent,
    Report,
    ReportJob,
    SearchProfile,
    SourceRegistry,
    User,
    WatchlistEntry,
    WorkItem,
)
from app.jobs import pipeline
from app.reports import service

pg_engine = test_database_core.pg_engine  # Reuse actual Alembic + isolated PostgreSQL fixture.
pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def local_synthetic_mode(monkeypatch):
    settings = Settings(app_env="local", demo_mode=True)
    monkeypatch.setattr(pipeline, "get_settings", lambda: settings)
    monkeypatch.setattr(service, "get_settings", lambda: settings)


def seed_owner(session):
    owner = User(google_subject="synthetic:" + uuid4().hex, verified_email="synthetic@fixture.invalid")
    session.add(owner)
    session.flush()
    profile = SearchProfile(
        user_id=owner.id,
        role_families=["Operations and revenue"],
        skills=["SQL"],
        work_arrangements=["REMOTE", "ONSITE", "HYBRID"],
    )
    session.add(profile)
    session.flush()
    return owner


def seed_source(session, number=0, *, group=None, tenant=None):
    group = group or EmployerGroup(
        canonical_name=f"Synthetic Employer {number}", normalized_name=f"synthetic employer {number}"
    )
    session.add(group)
    session.flush()
    entity = EmployerEntity(group_id=group.id, legal_name=f"Synthetic Legal Employer {number}")
    session.add(entity)
    session.flush()
    session.add(
        EVerifyEvidence(
            entity_id=entity.id,
            status="CONFIRMED",
            legal_name_as_found=entity.legal_name,
            source_reference="synthetic://official-record",
            snapshot="Synthetic evidence ONLY",
            content_hash="a" * 64,
            checked_at=NOW - timedelta(days=1),
            recheck_due_at=NOW + timedelta(days=29),
            verification_method="SYNTHETIC",
            reviewer="synthetic-reviewer",
            synthetic=True,
        )
    )
    source = SourceRegistry(
        connector_type="fixture",
        tenant=tenant or f"synthetic-{number}-{uuid4().hex}",
        employer_group_id=group.id,
        configuration_state="HEALTHY",
        enabled=True,
    )
    session.add(source)
    session.flush()
    return source, entity


def ingest(
    session, owner, source, entity, req, *, when=NOW, salary_min=90000, salary_max=100000, last_publication=False
):
    item = normalized(
        tenant=source.tenant,
        external_id=req,
        requisition_id=req,
        employer_url=f"https://fixture.invalid/{source.tenant}/{req}",
        application_url=f"https://fixture.invalid/{source.tenant}/{req}/apply",
        fetched_at=when,
        salary={"minimum": salary_min, "maximum": salary_max, "currency": "USD", "interval": "YEAR"},
        publication={
            "earliest": when - timedelta(hours=24),
            "latest": when - timedelta(hours=24),
            "precision": "EXACT",
            "kind": "LAST_PUBLICATION" if last_publication else "ORIGINAL",
        },
    )
    check = opening(application_url=item.application_url, final_url=item.employer_url, checked_at=when)
    job, initial = pipeline.ingest_normalized(session, source, item, check, user_id=owner.id)
    assert job.entity_id is None or job.entity_id == entity.id
    if job.entity_id is None:
        assert initial.decision == "NEEDS_REVIEW"  # Brand register never approves actual legal employer.
        job.entity_id = entity.id  # Explicit fixture equivalent of reviewed administrator mapping.
    final = pipeline.reevaluate_job(session, job.id, owner.id, now=when)
    return job, final, item, check


def test_report_concurrency_caps_membership_and_idempotent_outbox(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        for company in range(26):
            source, entity = seed_source(session, company)
            for position in range(3):
                _, evaluation, _, _ = ingest(session, owner, source, entity, f"REQ-{company}-{position}")
                assert evaluation.decision == "ELIGIBLE"
        user_id = owner.id

    def build(_):
        with Session(pg_engine) as session, session.begin():
            report = service.build_report(session, user_id, now=NOW)
            return report.id

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(build, [1, 2]))
    assert results[0] == results[1]
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Report)) == 1
        assert session.scalar(select(func.count()).select_from(ReportJob)) == 50
        assert session.scalar(select(func.count()).select_from(InitialDelivery)) == 50
        assert max(session.scalars(select(CompanyCycleUsage.count))) <= 2
        assert session.scalar(select(func.count()).select_from(Notification)) == 1
        assert session.scalar(select(func.count()).select_from(WorkItem)) == 50
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 51
        assert session.get(Report, results[0]).status == "FINALIZED"


def test_priority_overlap_bypasses_quota_and_regular_company_cycle(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        group = session.get(EmployerGroup, source.employer_group_id)
        group.pool_tags = ["UNIVERSITY_VERIFIED"]
        session.add(WatchlistEntry(user_id=owner.id, employer_group_id=group.id))
        session.flush()
        job, _, _, _ = ingest(session, owner, source, entity, "PRIORITY")
        first = service.deliver_priority(session, owner.id, now=NOW)
        assert first == [job.id]
        assert job.priority_reasons == ["WATCHLIST", "UNIVERSITY"]
        assert service.deliver_priority(session, owner.id, now=NOW) == []
        report = service.build_report(session, owner.id, now=NOW)
        assert report.summary["count"] == 0
        assert session.scalar(select(func.count()).select_from(CompanyCycleUsage)) == 0
        assert session.scalar(select(func.count()).select_from(InitialDelivery)) == 1


def test_new_profile_and_current_closure_block_old_eligible_decision(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        first, _, _, _ = ingest(session, owner, source, entity, "PROFILE")
        second, _, _, _ = ingest(session, owner, source, entity, "CLOSED")
        first_id, second_id, user_id = first.id, second.id, owner.id
    with Session(pg_engine) as session, session.begin():
        profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == user_id))
        profile.role_families = ["Analytics engineering"]
        profile.version = 2
        session.get(Job, second_id).availability = "CLOSED"
        report = service.build_report(session, user_id, now=NOW)
        assert report.summary["count"] == 0
        newest = session.scalars(
            select(JobEvaluation).where(JobEvaluation.user_id == user_id, JobEvaluation.profile_version == 2)
        ).all()
        assert {e.job_id for e in newest} == {first_id, second_id}
        assert all(e.decision == "INELIGIBLE" for e in newest)


def test_group_requisitions_remain_distinct_and_source_retry_reuses_snapshot_identity(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        one, _, item, check = ingest(session, owner, source, entity, "REQ1")
        two, _, _, _ = ingest(session, owner, source, entity, "REQ2")
        repeated, _ = pipeline.ingest_normalized(session, source, item, check, user_id=owner.id)
        assert one.id != two.id and repeated.id == one.id
        assert session.scalar(select(func.count()).select_from(Job)) == 2
        assert session.scalar(select(func.count()).select_from(JobSource)) == 2


def test_known_cross_source_destination_stays_suppressed_even_after_new_cycle(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        job, _, item, check = ingest(session, owner, source, entity, "REQ1")
        report = service.build_report(session, owner.id, now=NOW)
        assert report.summary["count"] == 1
        # A second source carries the exact proven employer destination and same opening ID.
        other = SourceRegistry(
            connector_type="fixture",
            tenant="second-source",
            employer_group_id=source.employer_group_id,
            configuration_state="HEALTHY",
            enabled=True,
        )
        session.add(other)
        session.flush()
        new_time = NOW + timedelta(days=32)
        cross = item.model_copy(
            update={
                "tenant": other.tenant,
                "external_id": "different-source-id",
                "fetched_at": new_time,
                "publication": item.publication.model_copy(
                    update={"earliest": new_time - timedelta(hours=1), "latest": new_time - timedelta(hours=1)}
                ),
            }
        )
        repeated, _ = pipeline.ingest_normalized(
            session, other, cross, check.model_copy(update={"checked_at": new_time}), user_id=owner.id
        )
        assert repeated.id == job.id
        assert repeated.published_earliest == NOW - timedelta(hours=24)
        future = service.build_report(session, owner.id, now=new_time)
        assert future.summary["count"] == 0
        assert session.scalar(select(func.count()).select_from(InitialDelivery)) == 1
        assert session.scalar(select(func.count()).select_from(JobSource)) == 2


def test_last_publication_uses_actual_local_checks_and_quarantines_similarity(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        source.capabilities = {"repost_identity_reviewed": True}
        _one, _, item, check = ingest(session, owner, source, entity, "REQ1", last_publication=True)
        # A new identity with the same content/location and no reliable requisition is unresolved.
        ambiguous = item.model_copy(
            update={
                "external_id": "new-id",
                "requisition_id": None,
                "employer_url": "https://fixture.invalid/ambiguous",
                "application_url": "https://fixture.invalid/ambiguous/apply",
            }
        )
        other, evaluation = pipeline.ingest_normalized(
            session,
            source,
            ambiguous,
            check.model_copy(
                update={"application_url": ambiguous.application_url, "final_url": ambiguous.employer_url}
            ),
            user_id=owner.id,
        )
        other.entity_id = entity.id
        evaluation = pipeline.reevaluate_job(session, other.id, owner.id, now=NOW)
        snapshot = session.get(JobSnapshot, other.current_snapshot_id)
        assert snapshot.structured_fields["identity_checks"]["review_candidates"]
        assert not snapshot.structured_fields["job_evidence"]["publication"]["repost_checked"]
        assert evaluation.decision == "NEEDS_REVIEW"
        assert session.scalar(select(func.count()).select_from(DuplicateLink)) >= 1


def test_salary_selection_prefers_high_then_newest_display(pg_engine, monkeypatch):
    settings = Settings(app_env="local", demo_mode=True, daily_job_limit=2)
    monkeypatch.setattr(service, "get_settings", lambda: settings)
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        high, _, _, _ = ingest(session, owner, source, entity, "HIGH", when=NOW - timedelta(hours=2))
        mid, _, _, _ = ingest(
            session, owner, source, entity, "MID", when=NOW - timedelta(hours=1), salary_min=70000, salary_max=90000
        )
        low, _, _, _ = ingest(session, owner, source, entity, "LOW", salary_min=50000, salary_max=70000)
        report = service.build_report(session, owner.id, now=NOW)
        members = session.scalars(
            select(ReportJob).where(ReportJob.report_id == report.id).order_by(ReportJob.selection_order)
        ).all()
        assert [m.job_id for m in members] == [mid.id, high.id]
        assert low.id not in [m.job_id for m in members]
        assert report.summary["limit"] == 2 and report.summary["supply"] == "FULL"


def test_finalized_report_membership_and_partial_failure_are_real(pg_engine):
    with Session(pg_engine) as session, session.begin():
        owner = seed_owner(session)
        source, entity = seed_source(session)
        job, _, _, _ = ingest(session, owner, source, entity, "REQ1")
        source.configuration_state = "BLOCKED"
        report = service.build_report(session, owner.id, now=NOW)
        assert report.summary["count"] == 1 and report.summary["partial_coverage"]
        member = session.scalar(select(ReportJob).where(ReportJob.report_id == report.id))
        identifiers = (report.id, job.id, member.snapshot_id, member.evaluation_id)
    with Session(pg_engine) as session, session.begin(), pytest.raises(DBAPIError), session.begin_nested():
        session.add(
            ReportJob(
                report_id=identifiers[0],
                job_id=identifiers[1],
                snapshot_id=identifiers[2],
                evaluation_id=identifiers[3],
                selection_order=2,
                selection_band="A",
            )
        )
        session.flush()
