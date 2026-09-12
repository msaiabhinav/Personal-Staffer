"""Audited operator tools. Reviewed evidence never bypasses normal eligibility."""

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import DomainError
from app.api.schemas import AdminSearchInput, EmployerEntityInput, EmployerEvidenceInput, WatchlistResolveInput
from app.applications.service import change, execute_operation, require_revision
from app.auth.dependencies import current_user
from app.config import get_settings
from app.db.models import (
    EmployerEntity,
    EmployerGroup,
    EVerifyEvidence,
    Job,
    ReviewItem,
    SourceRegistry,
    User,
    WatchlistEntry,
)
from app.db.session import get_session

router = APIRouter(prefix="/admin", tags=["administration"])
USER_DEPENDENCY = Depends(current_user)
SESSION_DEPENDENCY = Depends(get_session)


def require_admin(user):
    if not user.is_admin:
        raise DomainError("FORBIDDEN", "Administrator access is required.", 403)


def validate_employer_evidence(payload, entity, clock, *, allow_synthetic=False):
    if payload.synthetic and not allow_synthetic:
        raise DomainError(
            "SYNTHETIC_EVIDENCE_FORBIDDEN", "Synthetic employer evidence requires explicit local demo mode.", 422
        )
    if payload.checked_at > clock + timedelta(minutes=5):
        raise DomainError("INVALID_CHECK_DATE", "Evidence cannot be checked in the future.", 422)
    if payload.status == "CONFIRMED":
        parsed = urlsplit(payload.source_reference)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or parsed.username or parsed.password:
            raise DomainError(
                "OFFICIAL_SOURCE_REQUIRED", "Use the HTTPS official source URL without embedded credentials.", 422
            )
        if not any(
            host == domain or host.endswith("." + domain) for domain in ("e-verify.gov", "everify.gov", "uscis.gov")
        ):
            raise DomainError(
                "OFFICIAL_SOURCE_REQUIRED", "Confirmation requires an official E-Verify or USCIS source reference.", 422
            )
        if payload.legal_name_as_found.casefold().strip() != entity.legal_name.casefold().strip():
            raise DomainError(
                "ENTITY_MISMATCH", "Evidence must match the selected legal employing entity exactly.", 422
            )
        if payload.legal_name_as_found.casefold() not in payload.snapshot.casefold():
            raise DomainError(
                "EVIDENCE_NAME_MISSING", "Retain the official source excerpt containing the legal entity name.", 422
            )


@router.post("/employer-evidence")
def import_employer_evidence(
    payload: EmployerEvidenceInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    require_admin(user)

    def action():
        entity = session.get(EmployerEntity, payload.entity_id)
        if not entity:
            raise DomainError("NOT_FOUND", "Legal employing entity not found.", 404)
        settings = get_settings()
        clock = datetime.now(UTC)
        validate_employer_evidence(
            payload, entity, clock, allow_synthetic=settings.app_env == "local" and settings.demo_mode
        )
        evidence = EVerifyEvidence(
            entity_id=entity.id,
            status=payload.status,
            legal_name_as_found=payload.legal_name_as_found,
            source_reference=payload.source_reference,
            snapshot=payload.snapshot,
            content_hash=sha256(payload.snapshot.encode()).hexdigest(),
            checked_at=payload.checked_at,
            recheck_due_at=payload.checked_at + timedelta(days=settings.everify_recheck_days),
            verification_method=payload.verification_method,
            reviewer=user.verified_email,
            synthetic=payload.synthetic,
        )
        session.add(evidence)
        session.flush()
        review = ReviewItem(
            user_id=user.id,
            review_type="EMPLOYER_EVIDENCE_IMPORT",
            target_id=evidence.id,
            reason="Authenticated review of official legal-entity participation evidence",
            state="RESOLVED",
            admin_only=True,
            evidence={
                "entity_id": str(entity.id),
                "content_hash": evidence.content_hash,
                "source_reference": payload.source_reference,
            },
            resolved_at=clock,
            resolution={"reviewer": user.verified_email, "status": payload.status},
        )
        session.add(review)
        session.flush()
        change(session, user.id, "reviews", review.id, review.revision)
        # Re-evaluation is explicitly queued through the regular worker boundary by caller afterward.
        return {
            "id": str(evidence.id),
            "entity_id": str(entity.id),
            "status": evidence.status,
            "checked_at": evidence.checked_at,
            "recheck_due_at": evidence.recheck_due_at,
            "review_id": str(review.id),
            "new_delivery_requires_reevaluation": True,
        }

    return execute_operation(
        session, user.id, key, "admin.employer-evidence", payload.entity_id, payload.model_dump(mode="json"), action
    )


@router.post("/jobs/{job_id}/reevaluate")
def reevaluate(
    job_id: UUID,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    require_admin(user)

    def action():
        if not session.get(Job, job_id):
            raise DomainError("NOT_FOUND", "Job not found.", 404)
        # This only reruns deterministic rules over retained evidence, and never fetches in the API request.
        from app.jobs.pipeline import reevaluate_job

        evaluation = reevaluate_job(session, job_id, user.id)
        return {
            "job_id": str(job_id),
            "evaluation_id": str(evaluation.id),
            "decision": evaluation.decision,
            "evaluated_at": evaluation.evaluated_at,
            "evidence": evaluation.evidence,
        }

    return execute_operation(session, user.id, key, "admin.reevaluate", job_id, {}, action)


@router.post("/search-runs", status_code=202)
def start_search(
    payload: AdminSearchInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    require_admin(user)

    def action():
        source = session.get(SourceRegistry, payload.source_registry_id)
        if not source:
            raise DomainError("NOT_FOUND", "Registered source not found.", 404)
        from app.workers.service import enqueue

        work = enqueue(
            session,
            "SOURCE_SEARCH",
            {"source_id": str(source.id), "user_id": str(user.id), "query": payload.query},
            f"admin-search:{user.id}:{key}",
        )
        return {"work_id": str(work.id), "state": work.state, "source_state": source.configuration_state}

    return execute_operation(
        session, user.id, key, "admin.search", payload.source_registry_id, payload.model_dump(mode="json"), action
    )


@router.get("/reviews")
def admin_reviews(
    user: User = USER_DEPENDENCY, session: Session = SESSION_DEPENDENCY, limit: int = Query(25, ge=1, le=100)
):
    require_admin(user)
    rows = list(
        session.scalars(
            select(ReviewItem)
            .where(ReviewItem.user_id == user.id, ReviewItem.admin_only.is_(True))
            .order_by(ReviewItem.created_at.desc(), ReviewItem.id)
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "id": row.id,
                "type": row.review_type,
                "reason": row.reason,
                "state": row.state,
                "evidence": row.evidence,
                "created_at": row.created_at,
                "resolved_at": row.resolved_at,
            }
            for row in rows
        ]
    }


@router.post("/employer-entities")
def create_employer_entity(
    payload: EmployerEntityInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    require_admin(user)

    def action():
        group = session.get(EmployerGroup, payload.employer_group_id)
        if not group:
            raise DomainError("NOT_FOUND", "Employer group not found.", 404)
        if payload.legal_name.casefold() not in payload.quoted_text.casefold():
            raise DomainError(
                "EVIDENCE_NAME_MISSING", "Retain the source excerpt identifying this legal employer.", 422
            )
        entity = EmployerEntity(
            group_id=group.id,
            legal_name=payload.legal_name,
            jurisdiction=payload.jurisdiction,
            address_evidence={
                "source_reference": payload.source_reference,
                "quoted_text": payload.quoted_text,
                "reviewer": user.verified_email,
                "checked_at": datetime.now(UTC).isoformat(),
            },
        )
        session.add(entity)
        session.flush()
        return {
            "id": str(entity.id),
            "group_id": str(group.id),
            "legal_name": entity.legal_name,
            "everify_state": "UNKNOWN",
        }

    return execute_operation(
        session, user.id, key, "admin.entity", payload.employer_group_id, payload.model_dump(mode="json"), action
    )


@router.post("/watchlist/{entry_id}/resolve")
def resolve_watchlist(
    entry_id: UUID,
    payload: WatchlistResolveInput,
    user: User = USER_DEPENDENCY,
    session: Session = SESSION_DEPENDENCY,
    key: str = Header(alias="Idempotency-Key"),
):
    require_admin(user)

    def action():
        entry = session.scalar(
            select(WatchlistEntry).where(WatchlistEntry.id == entry_id, WatchlistEntry.user_id == user.id)
        )
        group = session.get(EmployerGroup, payload.employer_group_id)
        if not entry or not group:
            raise DomainError("NOT_FOUND", "Watchlist request or employer group not found.", 404)
        require_revision(entry.revision, payload.expected_revision)
        already = session.scalar(
            select(WatchlistEntry).where(
                WatchlistEntry.user_id == user.id,
                WatchlistEntry.employer_group_id == group.id,
                WatchlistEntry.id != entry.id,
            )
        )
        if already:
            raise DomainError(
                "WATCHLIST_ALREADY_REGISTERED",
                "This employer already has a watchlist entry. Remove the duplicate pending request.",
            )
        entry.employer_group_id = group.id
        entry.revision += 1
        review = ReviewItem(
            user_id=user.id,
            review_type="WATCHLIST_EMPLOYER_RESOLUTION",
            target_id=entry.id,
            reason="Reviewed mapping of requested name to registered employer group",
            evidence={
                "requested_name": entry.requested_name,
                "source_reference": payload.source_reference,
                "quoted_text": payload.quoted_text,
            },
            state="RESOLVED",
            admin_only=True,
            resolved_at=datetime.now(UTC),
            resolution={"employer_group_id": str(group.id), "reviewer": user.verified_email},
        )
        session.add(review)
        change(session, user.id, "watchlist", entry.id, entry.revision)
        return {
            "id": str(entry.id),
            "company": group.canonical_name,
            "resolution_state": "REGISTERED",
            "revision": entry.revision,
        }

    return execute_operation(
        session, user.id, key, "admin.watchlist.resolve", entry_id, payload.model_dump(mode="json"), action
    )
