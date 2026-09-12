"""Explicit isolated local fixtures, never production login or recommendations."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.errors import DomainError
from app.auth.service import issue_session
from app.config import get_settings
from app.db.models import (
    Device,
    EmployerEntity,
    EmployerGroup,
    EVerifyEvidence,
    Job,
    JobSnapshot,
    JobSource,
    SearchProfile,
    SearchProfileVersion,
    SourceRegistry,
    User,
    WatchlistEntry,
)
from app.db.session import get_session
from app.sync.service import lock_user, record_change

router = APIRouter(prefix="/api/v1")


def require_demo():
    settings = get_settings()
    if settings.app_env != "local" or not settings.demo_mode:
        raise DomainError("NOT_FOUND", "Endpoint not available.", 404)


def seed_demo(session):
    require_demo()
    session.execute(text("SELECT pg_advisory_xact_lock(783210420)"))
    if session.scalar(select(Job.id).where(Job.synthetic.is_(False)).limit(1)):
        raise DomainError("DEMO_ISOLATION_REQUIRED", "Use a separate demo database without real source jobs.", 409)
    owners = list(session.scalars(select(User)))
    if any(u.google_subject != "demo:personal-staffer" for u in owners):
        raise DomainError("DEMO_ISOLATION_REQUIRED", "Use a separate empty demo database.", 409)
    user = (
        owners[0]
        if owners
        else User(google_subject="demo:personal-staffer", verified_email="demo@example.invalid", display_name="DEMO")
    )
    if not owners:
        session.add(user)
        session.flush()
    lock_user(session, user.id)
    source = session.scalar(
        select(SourceRegistry).where(SourceRegistry.connector_type == "fixture", SourceRegistry.tenant == "local-demo")
    )
    if source:
        return {"user_id": str(user.id), "state": "EXISTING_DEMO", "demo_mode": True}
    now = datetime.now(UTC)
    group = EmployerGroup(
        canonical_name="DEMO · Example Analytics",
        normalized_name="demo example analytics",
        grouping_evidence={"synthetic": True},
    )
    session.add(group)
    session.flush()
    entity = EmployerEntity(group_id=group.id, legal_name="Synthetic Example Employer; Not a Real Company")
    session.add(entity)
    session.flush()
    session.add(
        EVerifyEvidence(
            entity_id=entity.id,
            status="CONFIRMED",
            legal_name_as_found=entity.legal_name,
            source_reference="synthetic://local-demo",
            snapshot="SYNTHETIC TEST ONLY",
            content_hash=hashlib.sha256(b"SYNTHETIC TEST ONLY").hexdigest(),
            checked_at=now,
            recheck_due_at=now + timedelta(days=30),
            verification_method="SYNTHETIC_TEST_ONLY",
            reviewer="DEMO",
            synthetic=True,
        )
    )
    source = SourceRegistry(
        connector_type="fixture",
        tenant="local-demo",
        employer_group_id=group.id,
        enabled=False,
        configuration_state="NOT_CONFIGURED",
    )
    session.add_all(
        [
            source,
            WatchlistEntry(user_id=user.id, employer_group_id=group.id),
            SearchProfile(
                user_id=user.id,
                skills=["SQL", "Python", "Power BI"],
                role_families=[
                    "Data analysis",
                    "Business analysis",
                    "Business intelligence",
                    "Operations and revenue",
                    "AI and machine learning",
                    "Analytics engineering",
                    "Deployment",
                    "Domain analysis",
                ],
            ),
        ]
    )
    session.flush()
    profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == user.id))
    session.add(
        SearchProfileVersion(
            user_id=user.id,
            version=profile.version,
            payload={
                "role_families": profile.role_families,
                "skills": profile.skills,
                "geography": profile.geography,
                "work_arrangements": profile.work_arrangements,
                "salary_preferences": profile.salary_preferences,
                "ruleset_version": profile.ruleset_version,
            },
        )
    )
    record_change(session, user.id, "profile", profile.id, profile.revision)
    # The specification's priority employer seeds appear on the demo Watchlist as
    # rotation groups only; no jobs, entities or E-Verify evidence are invented for them.
    from app.cli import seed_registry

    seed_registry(session)
    from app.eligibility.models import JobEvidence
    from app.jobs.pipeline import reevaluate_job

    for index, title in enumerate(["Revenue Analyst", "Business Intelligence Analyst"]):
        job_id, snapshot_id = uuid4(), uuid4()
        url = f"https://fixture.invalid/demo/{job_id}"
        description = "DEMO — fictional opening, no application is submitted.\nResponsibilities\nBuild SQL dashboards to analyze revenue and pricing data.\nRequired qualifications\n2 years analytics experience required.\nEmployment Type: Full-time."
        facts = JobEvidence.model_validate(
            {
                "id": str(job_id),
                "snapshot_id": str(snapshot_id),
                "title": title,
                "description": description,
                "description_complete": True,
                "source_url": url,
                "fetched_at": now,
                "employer_group_id": str(group.id),
                "legal_entity_id": str(entity.id),
                "country_codes": ["US"],
                "employment_type": "FULL_TIME",
                "work_arrangement": "REMOTE",
                "watchlisted": True,
                "publication": {
                    "earliest": now - timedelta(hours=12 + index),
                    "latest": now - timedelta(hours=12 + index),
                    "precision": "EXACT",
                    "kind": "ORIGINAL",
                    "source_field": "synthetic.published_at",
                },
                "opening": {
                    "status": "ACTIVE",
                    "application_url": url,
                    "identity_match": True,
                    "actionable": True,
                    "checked_at": now,
                    "evidence_text": "SYNTHETIC opening",
                },
                "synthetic": True,
            }
        )
        job = Job(
            id=job_id,
            employer_group_id=group.id,
            entity_id=entity.id,
            title=title,
            published_at=facts.publication.earliest,
            published_earliest=facts.publication.earliest,
            published_latest=facts.publication.latest,
            publication_precision="EXACT",
            availability="ACTIVE",
            synthetic=True,
            locations=["United States (DEMO)"],
            work_arrangement="REMOTE",
        )
        session.add(job)
        session.flush()
        js = JobSource(
            job_id=job.id,
            source_registry_id=source.id,
            external_id=str(index),
            source_url=url,
            application_url=url,
            availability="ACTIVE",
            last_verified=now,
            link_evidence={"identity_match": True, "synthetic": True},
        )
        session.add(js)
        session.flush()
        snapshot = JobSnapshot(
            id=snapshot_id,
            job_id=job.id,
            source_id=js.id,
            description=description,
            content_hash=hashlib.sha256(description.encode()).hexdigest(),
            content_complete=True,
            structured_fields={"job_evidence": facts.model_dump(mode="json")},
            fetched_at=now,
        )
        session.add(snapshot)
        session.flush()
        job.current_snapshot_id = snapshot.id
        reevaluate_job(session, job.id, user.id, now=now)
    from app.reports.service import deliver_priority

    delivered = deliver_priority(session, user.id, now=now)
    return {"user_id": str(user.id), "demo_mode": True, "priority_demo_jobs": len(delivered)}


class DemoInput(BaseModel):
    device_id: UUID
    platform: Literal["WINDOWS", "ANDROID", "windows", "android"]
    device_label: str = "Local demo device"


DEMO_SESSION_DEPENDENCY = Depends(get_session)


@router.post("/auth/demo")
def demo_login(payload: DemoInput, session: Session = DEMO_SESSION_DEPENDENCY):
    require_demo()
    result = seed_demo(session)
    user_id = UUID(result["user_id"])
    device = session.get(Device, payload.device_id)
    if device and device.user_id != user_id:
        raise DomainError("DEVICE_CONFLICT", "Use a fresh demo device identity.", 409)
    if not device:
        device = Device(
            id=payload.device_id,
            user_id=user_id,
            platform=payload.platform.upper(),
            device_label=payload.device_label[:255],
        )
        session.add(device)
        session.flush()
    device.revoked_at = None
    device.last_seen = datetime.now(UTC)
    record_change(session, user_id, "devices", device.id, device.revision)
    return {**issue_session(session, get_settings(), user_id, device.id), "demo_mode": True}
