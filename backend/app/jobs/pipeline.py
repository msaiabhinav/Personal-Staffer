"""Evidence-preserving ingestion; source identity never implies legal-employer approval."""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.contracts import NormalizedJob, OpeningVerification
from app.db.models import (
    Application,
    ConnectorRun,
    DuplicateLink,
    EmployerEntity,
    EmployerGroup,
    Job,
    JobEvaluation,
    JobFact,
    JobIdentityTombstone,
    JobSnapshot,
    JobSource,
    RuleResult,
    SearchProfile,
    SearchRun,
    SourceRegistry,
    User,
    WatchlistEntry,
)
from app.db.models import EVerifyEvidence as DBEVerify
from app.eligibility import evaluate_job
from app.eligibility.dedupe import JobIdentity, canonical_destination, compare_identity
from app.eligibility.models import (
    EVerifyEvidence,
    EvidenceRef,
    Fact,
    FinalDecision,
    JobEvidence,
    OpeningEvidence,
    Policy,
)
from app.eligibility.models import RuleResult as EvidenceRule


def _verified_startup_pool(group):
    if group is None:
        return None
    pools = (getattr(group, "grouping_evidence", None) or {}).get("pool_evidence", {})
    for pool in ("NYC", "BAY_AREA"):
        evidence = pools.get(pool, {})
        if pool + "_VERIFIED" not in (getattr(group, "pool_tags", None) or []):
            continue
        if not isinstance(evidence, dict) or not all(
            evidence.get(key)
            for key in ("source_reference", "quoted_text", "reviewer", "checked_at", "location", "startup_basis")
        ):
            continue
        if evidence.get("company_location_kind") not in {"HEADQUARTERS", "MAJOR_OPERATING_OFFICE"}:
            continue
        try:
            checked = datetime.fromisoformat(str(evidence["checked_at"]))
        except (TypeError, ValueError):
            continue
        if checked.tzinfo is not None and checked.utcoffset() is not None:
            return pool
    return None


def _entity_evidence(session, job, now):
    if not job.entity_id:
        return EVerifyEvidence()
    entity = session.get(EmployerEntity, job.entity_id)
    record = session.scalar(
        select(DBEVerify)
        .where(DBEVerify.entity_id == job.entity_id)
        .order_by(DBEVerify.checked_at.desc(), DBEVerify.id.desc())
        .limit(1)
    )
    if not record or not entity or entity.group_id != job.employer_group_id:
        return EVerifyEvidence()
    return EVerifyEvidence(
        status=record.status,
        legal_entity_id=str(record.entity_id),
        legal_name=record.legal_name_as_found,
        source_reference=record.source_reference,
        evidence_hash=record.content_hash,
        checked_at=record.checked_at,
        recheck_due_at=record.recheck_due_at,
        method=record.verification_method,
        reviewer=record.reviewer,
        synthetic=record.synthetic,
        identity_match=record.legal_name_as_found.casefold().strip() == entity.legal_name.casefold().strip(),
    )


def _complete_review(review: dict, *, content_hash: str) -> bool:
    """A review is per-opening content, never a source-wide approval Boolean."""
    if not isinstance(review, dict) or review.get("content_hash") != content_hash:
        return False
    if not all(review.get(key) for key in ("reviewer", "evidence_reference", "checked_at")):
        return False
    try:
        checked = datetime.fromisoformat(str(review["checked_at"]))
        return checked.tzinfo is not None and checked.utcoffset() is not None
    except (ValueError, TypeError):
        return False


def _identity_resolution_matches(review, *, content_hash, source_identity, requisition_id):
    return (
        _complete_review(review, content_hash=content_hash)
        and review.get("decision") == "DISTINCT"
        and review.get("source_identity") == source_identity
        and "requisition_id" in review
        and review["requisition_id"] == requisition_id
    )


def _finalize_evaluation(evaluation):
    decisions = {r.decision for r in evaluation.rules}
    # Attribute assignment skips validation, so assign the enum member itself; a bare
    # string here made every later model_dump() emit a Pydantic serializer warning.
    evaluation.decision = FinalDecision(
        "INELIGIBLE" if "FAIL" in decisions else "NEEDS_REVIEW" if decisions & {"UNKNOWN", "REVIEW"} else "ELIGIBLE"
    )
    if evaluation.decision != "ELIGIBLE":
        evaluation.priority_reasons = []
    return evaluation


def _profile_rules(evaluation, profile, now):
    if profile is None:
        return evaluation
    reference = EvidenceRef(
        snapshot_id=f"profile:{profile.id}:v{profile.version}",
        field_path="role_families/work_arrangements",
        observed_at=now,
    )
    # An explicitly saved empty selection means no chosen families/arrangements.
    family_ok = bool(set(profile.role_families).intersection(evaluation.relevance.families))
    evaluation.rules.append(
        EvidenceRule(
            rule="profile_role_families",
            decision="PASS" if family_ok else "FAIL",
            reason_code="PROFILE_FAMILY_MATCH" if family_ok else "PROFILE_FAMILY_NOT_SELECTED",
            message="Job matches a saved role family." if family_ok else "No saved role family matches this opening.",
            rule_version=f"profile-{profile.version}",
            evidence=[reference],
        )
    )
    return evaluation


def reevaluate_job(session: Session, job_id: UUID, user_id: UUID, *, now=None) -> JobEvaluation:
    now = now or datetime.now(UTC)
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise ValueError("Unknown job")
    snapshot = session.get(JobSnapshot, job.current_snapshot_id)
    profile = session.scalar(select(SearchProfile).where(SearchProfile.user_id == user_id))
    if snapshot is None:
        raise ValueError("A retained snapshot is required for evaluation")
    source_record = session.get(JobSource, snapshot.source_id) if snapshot.source_id else None
    serialized = snapshot.structured_fields.get("job_evidence")
    if serialized:
        facts = JobEvidence.model_validate(serialized)
    else:
        facts = JobEvidence(
            id=str(job.id),
            title=job.title,
            description=snapshot.description,
            description_complete=False,
            snapshot_id=str(snapshot.id),
            source_url=source_record.source_url if source_record else "https://invalid.example/unverified",
            fetched_at=snapshot.fetched_at,
        )
    # Snapshot IDs and completeness cannot be replaced by a stale/copied serialized envelope.
    updates = {
        "id": str(job.id),
        "snapshot_id": str(snapshot.id),
        "description": snapshot.description,
        "description_complete": snapshot.content_complete and facts.description_complete,
        "legal_entity_id": str(job.entity_id) if job.entity_id else None,
        "everify": _entity_evidence(session, job, now),
        "synthetic": job.synthetic or facts.synthetic,
    }
    current_opening = dict(source_record.link_evidence.get("opening", {})) if source_record else {}
    opening = OpeningEvidence.model_validate(current_opening) if current_opening else facts.opening
    if job.availability in ("CLOSED", "UNKNOWN"):
        opening = opening.model_copy(update={"status": job.availability})
    elif source_record and source_record.availability in ("CLOSED", "UNKNOWN"):
        opening = opening.model_copy(update={"status": source_record.availability})
    updates["opening"] = opening
    group = session.get(EmployerGroup, job.employer_group_id)
    updates.update(
        {
            "watchlisted": session.scalar(
                select(WatchlistEntry.id).where(
                    WatchlistEntry.user_id == user_id,
                    WatchlistEntry.employer_group_id == job.employer_group_id,
                    WatchlistEntry.enabled.is_(True),
                )
            )
            is not None,
            "university": "UNIVERSITY_VERIFIED" in (group.pool_tags if group else []),
            "academic_medical_center": "ACADEMIC_MEDICAL_CENTER_VERIFIED" in (group.pool_tags if group else []),
        }
    )
    updates["startup_pool"] = _verified_startup_pool(group)
    facts = facts.model_copy(update=updates)
    settings = get_settings()
    evaluation = evaluate_job(
        facts,
        now=now,
        policy=Policy(
            skill_vocabulary=profile.skills if profile else None,
            preferred_salary_usd=settings.preferred_salary_usd,
            everify_recheck_days=settings.everify_recheck_days,
        ),
        allow_synthetic=settings.app_env == "local" and settings.demo_mode,
    )
    pool_evidence = (group.grouping_evidence or {}).get("pool_evidence", {}) if group else {}
    evaluation.facts.append(
        Fact(
            field="startup_pool",
            state="KNOWN" if facts.startup_pool else "UNKNOWN",
            value={"pool": facts.startup_pool, "company_base_evidence": pool_evidence},
            evidence=[
                EvidenceRef(
                    snapshot_id=f"employer_group:{job.employer_group_id}",
                    field_path="grouping_evidence.pool_evidence",
                    observed_at=now,
                )
            ],
        )
    )
    evaluation = _profile_rules(evaluation, profile, now)
    if profile is not None:
        arrangement_ok = facts.work_arrangement in profile.work_arrangements
        evaluation.rules.append(
            EvidenceRule(
                rule="profile_work_arrangement",
                decision="PASS" if arrangement_ok else "FAIL",
                reason_code="PROFILE_ARRANGEMENT_MATCH" if arrangement_ok else "PROFILE_ARRANGEMENT_NOT_SELECTED",
                message="Work arrangement matches the saved profile."
                if arrangement_ok
                else "Work arrangement is not selected or remains unknown.",
                rule_version=f"profile-{profile.version}",
                evidence=[
                    EvidenceRef(
                        snapshot_id=f"profile:{profile.id}:v{profile.version}",
                        field_path="work_arrangements",
                        observed_at=now,
                    )
                ],
            )
        )
    checks = snapshot.structured_fields.get("identity_checks", {})
    unresolved = checks.get("review_candidates", [])
    review = source_record.link_evidence.get("identity_resolution", {}) if source_record else {}
    resolved = _identity_resolution_matches(
        review,
        content_hash=snapshot.content_hash,
        source_identity=checks.get("source_identity"),
        requisition_id=snapshot.structured_fields.get("normalized", {}).get("requisition_id"),
    )
    if unresolved and not resolved:
        evaluation.rules.append(
            EvidenceRule(
                rule="duplicate_identity",
                decision="REVIEW",
                reason_code="DUPLICATE_IDENTITY_UNRESOLVED",
                message="Possible cross-post/repost identity requires per-opening review.",
                evidence=[
                    EvidenceRef(
                        snapshot_id=str(snapshot.id),
                        field_path="identity_checks.review_candidates",
                        observed_at=snapshot.fetched_at,
                    )
                ],
            )
        )
    evaluation = _finalize_evaluation(evaluation)
    row = JobEvaluation(
        job_id=job.id,
        snapshot_id=snapshot.id,
        user_id=user_id,
        profile_version=profile.version if profile else 1,
        ruleset_version=evaluation.ruleset_version,
        evaluated_at=now,
        decision=evaluation.decision,
        valid_until=evaluation.valid_until,
        evidence=evaluation.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    for rule in evaluation.rules:
        session.add(
            RuleResult(
                evaluation_id=row.id,
                rule_code=rule.rule,
                rule_version=rule.rule_version,
                decision=rule.decision,
                reason_code=rule.reason_code,
                evidence=[e.model_dump(mode="json") for e in rule.evidence],
            )
        )
    if not session.scalar(select(JobFact.id).where(JobFact.snapshot_id == snapshot.id).limit(1)):
        for fact in evaluation.facts:
            session.add(
                JobFact(
                    snapshot_id=snapshot.id,
                    field=fact.field,
                    value={"value": fact.value},
                    fact_state=fact.state,
                    requiredness=fact.requiredness,
                    polarity=fact.polarity,
                    evidence={"references": [e.model_dump(mode="json") for e in fact.evidence]},
                    extractor_version=fact.extractor_version,
                    observed_at=now,
                )
            )
    job.priority_reasons = evaluation.priority_reasons
    job.role_family = evaluation.relevance.families[0] if evaluation.relevance.families else None
    session.flush()
    return row


def _canonical_job(session, job):
    visited = set()
    while job is not None and job.canonical_redirect_id:
        if job.id in visited:
            raise ValueError("Canonical job redirect cycle")
        visited.add(job.id)
        job = session.get(Job, job.canonical_redirect_id)
    return job


def _requisition_namespace(source):
    value = (source.capabilities or {}).get("requisition_namespace", {})
    if isinstance(value, dict) and all(
        value.get(k) for k in ("namespace", "reviewer", "evidence_reference", "checked_at")
    ):
        try:
            checked = datetime.fromisoformat(str(value["checked_at"]))
            if checked.tzinfo is not None and checked.utcoffset() is not None:
                return str(value["namespace"])
        except (ValueError, TypeError):
            pass
    return None


def normalized_identity(source, normalized, opening, *, canonical_id):
    namespace = _requisition_namespace(source)
    # The public opening check must establish the actual source opening, not only HTTP 200.
    destination_ok = bool(
        opening.identity_match
        and opening.actionable
        and normalized.employer_url
        and opening.status == "ACTIVE"
        and not opening.generic_careers_redirect
    )
    return JobIdentity(
        canonical_id=str(canonical_id),
        source=source.connector_type,
        tenant=source.tenant,
        external_id=normalized.external_id,
        employer_group_id=str(source.employer_group_id),
        requisition_id=normalized.requisition_id,
        requisition_verified=bool(namespace and normalized.requisition_id),
        employer_destination=normalized.employer_url,
        destination_identity_verified=destination_ok,
        title=normalized.title,
        location=" | ".join(sorted(normalized.locations)),
        description=normalized.description_text,
    )


def _source_identity(session, record, job):
    registry = session.get(SourceRegistry, record.source_registry_id)
    payload = (record.link_evidence or {}).get("identity")
    if payload:
        return JobIdentity.model_validate(payload).model_copy(update={"canonical_id": str(job.id)})
    return JobIdentity(
        canonical_id=str(job.id),
        source=registry.connector_type,
        tenant=registry.tenant,
        external_id=record.external_id,
        employer_group_id=str(job.employer_group_id),
        requisition_id=job.requisition_id,
        title=job.title,
        location=" | ".join(sorted(job.locations or [])),
        description=session.get(JobSnapshot, job.current_snapshot_id).description if job.current_snapshot_id else "",
    )


def _compare_namespaced(a, b, namespace_a, namespace_b):
    # Rotation groups are insufficient to scope requisition IDs across legal employers/boards.
    if namespace_a != namespace_b or not namespace_a:
        a = a.model_copy(update={"requisition_verified": False})
        b = b.model_copy(update={"requisition_verified": False})
    if a.requisition_id and b.requisition_id and a.requisition_id != b.requisition_id:
        from app.eligibility.dedupe import DuplicateDecision

        if (a.source, a.tenant, a.external_id) == (b.source, b.tenant, b.external_id):
            return DuplicateDecision(
                decision="REVIEW",
                reason="SOURCE_ID_REUSED_WITH_DIFFERENT_REQUISITION",
                evidence=[a.requisition_id, b.requisition_id],
            )
        return DuplicateDecision(
            decision="DISTINCT", reason="DIFFERENT_REQUISITIONS", evidence=[a.requisition_id, b.requisition_id]
        )
    return compare_identity(a, b)


def _tombstone(session, job, key, kind, evidence):
    existing = session.scalar(select(JobIdentityTombstone).where(JobIdentityTombstone.identity_key == key))
    if existing is None:
        session.add(JobIdentityTombstone(job_id=job.id, identity_type=kind, identity_key=key, evidence=evidence))
    elif _canonical_job(session, session.get(Job, existing.job_id)).id != job.id:
        raise ValueError("Conflicting permanent job identity needs review")


def _map_evidence(
    normalized, opening, job, group, snapshot_id, publication, *, staffing=False, permanent=None, payroll_verified=False
):
    def field(key):
        evidence = normalized.field_evidence.get(key, [])
        return str([f.model_dump(mode="json") for f in evidence]) if evidence else None

    def boolean(key):
        values = [f.value for f in normalized.field_evidence.get(key, [])]
        return values[0] if len(values) == 1 and isinstance(values[0], bool) else None

    # A remote job's office-address states are not its remote eligible states.
    remote_states = []
    for evidence in normalized.field_evidence.get("remote_eligible_states", []):
        values = evidence.value if isinstance(evidence.value, list) else [evidence.value]
        remote_states.extend(str(v).upper() for v in values if isinstance(v, str) and len(v) == 2)
    return JobEvidence(
        id=str(job.id),
        title=normalized.title,
        description=normalized.description_text,
        description_complete=normalized.description_complete,
        snapshot_id=str(snapshot_id),
        source_url=normalized.source_url,
        fetched_at=normalized.fetched_at,
        employer_group_id=str(group.id),
        country_codes=normalized.country_codes,
        country_conflicting=boolean("country_conflicting") is True or "COUNTRY_CONFLICTING" in normalized.warnings,
        country_evidence=field("country_codes"),
        employment_type=normalized.employment_type,
        employment_evidence=field("employment_type"),
        work_arrangement=normalized.work_arrangement,
        workplace_states=normalized.workplace_states,
        startup_pool=_verified_startup_pool(group),
        explicit_remote_states=remote_states if normalized.work_arrangement == "REMOTE" else [],
        staffing=staffing or boolean("staffing") is True,
        permanent_placement=permanent if permanent is not None else boolean("permanent_placement"),
        payroll_entity_verified=payroll_verified,
        publication=publication,
        salary=normalized.salary,
        first_seen_at=job.first_seen,
        opening=OpeningEvidence.model_validate(opening.model_dump()),
        synthetic=normalized.synthetic,
    )


def ingest_normalized(
    session: Session, source: SourceRegistry, normalized: NormalizedJob, opening: OpeningVerification, *, user_id: UUID
) -> tuple[Job, JobEvaluation]:
    settings = get_settings()
    if normalized.synthetic and not (settings.app_env == "local" and settings.demo_mode):
        raise ValueError("Synthetic imports require local DEMO_MODE")
    if (
        normalized.source_type != source.connector_type
        or normalized.tenant != source.tenant
        or not normalized.external_id
    ):
        raise ValueError("Normalized source/tenant/external identity must match its registered source")
    # Shared user lock also serializes external-application association against apply/report commands.
    if session.scalar(select(User).where(User.id == user_id).with_for_update()) is None:
        raise ValueError("Unknown user")
    source = session.scalar(select(SourceRegistry).where(SourceRegistry.id == source.id).with_for_update())
    if source.employer_group_id is None:
        raise ValueError("Source needs an explicitly registered employer group")
    group = session.scalar(select(EmployerGroup).where(EmployerGroup.id == source.employer_group_id).with_for_update())
    if group is None:
        raise ValueError("Registered employer group was not found")
    source_record = session.scalar(
        select(JobSource).where(
            JobSource.source_registry_id == source.id, JobSource.external_id == normalized.external_id
        )
    )
    job = _canonical_job(session, session.get(Job, source_record.job_id)) if source_record else None
    source_key = f"source:{source.connector_type}:{source.tenant}:{normalized.external_id}"
    for key in (source_key, f"source:{source.id}:{normalized.external_id}"):
        tombstone = session.scalar(select(JobIdentityTombstone).where(JobIdentityTombstone.identity_key == key))
        if tombstone:
            retained = _canonical_job(session, session.get(Job, tombstone.job_id))
            if retained.employer_group_id != group.id:
                raise ValueError("Permanent source identity belongs to a different employer group")
            if job and retained.id != job.id:
                raise ValueError("Source identity disagrees with permanent tombstone")
            job = retained
    incoming = normalized_identity(source, normalized, opening, canonical_id=job.id if job else uuid4())
    namespace = _requisition_namespace(source)
    permanent_keys = []
    if namespace and normalized.requisition_id:
        permanent_keys.append(f"req:{namespace}:{normalized.requisition_id}")
    if incoming.destination_identity_verified and incoming.employer_destination:
        permanent_keys.append(f"destination:{group.id}:{canonical_destination(incoming.employer_destination)}")
    for key in permanent_keys:
        retained_key = session.scalar(select(JobIdentityTombstone).where(JobIdentityTombstone.identity_key == key))
        if retained_key:
            retained = _canonical_job(session, session.get(Job, retained_key.job_id))
            if retained.employer_group_id != group.id:
                raise ValueError("Permanent requisition namespace conflicts with the employer group")
            if (
                key.startswith("destination:")
                and retained.requisition_id
                and normalized.requisition_id
                and retained.requisition_id != normalized.requisition_id
            ):
                continue  # URL reused for explicitly different requisitions is not a permanent unique identity.
            if job and retained.id != job.id:
                raise ValueError("Permanent cross-source identity is ambiguous")
            job = retained
    comparisons, review_candidates, matches = [], [], {}
    content_hash = hashlib.sha256(normalized.description_text.encode()).hexdigest()
    prior_link_evidence = (source_record.link_evidence or {}) if source_record else {}
    resolution = prior_link_evidence.get("identity_resolution", {})
    resolution_valid = _identity_resolution_matches(
        resolution, content_hash=content_hash, source_identity=source_key, requisition_id=normalized.requisition_id
    )
    if not resolution_valid:
        review_candidates.extend(prior_link_evidence.get("identity_review_candidates", []))
        if job and normalized.requisition_id and job.requisition_id and normalized.requisition_id != job.requisition_id:
            review_candidates.append({"job_id": str(job.id), "reason": "SOURCE_ID_REUSED_WITH_DIFFERENT_REQUISITION"})
    possible = session.scalars(
        select(Job).where(Job.employer_group_id == group.id, Job.canonical_redirect_id.is_(None)).order_by(Job.id)
    ).all()
    for candidate in possible:
        for record in session.scalars(select(JobSource).where(JobSource.job_id == candidate.id)):
            previous = _source_identity(session, record, candidate)
            # A changing requisition on an existing source ID still needs explicit review.
            incoming_compare = incoming.model_copy(update={"canonical_id": "incoming-evidence"})
            prior_namespace = (record.link_evidence or {}).get("requisition_namespace")
            comparison = _compare_namespaced(incoming_compare, previous, namespace, prior_namespace)
            check = {"job_id": str(candidate.id), "source_id": str(record.id), **comparison.model_dump()}
            comparisons.append(check)
            if comparison.decision == "SAME":
                matches[candidate.id] = candidate
            elif comparison.decision == "REVIEW" and not resolution_valid:
                review_candidates.append(check)
    if job is None and len(matches) == 1:
        job = next(iter(matches.values()))
    elif len(matches) > 1 or (job and any(m != job.id for m in matches)):
        review_candidates.extend(
            {"job_id": str(match), "reason": "MULTIPLE_CANONICAL_IDENTITY_MATCHES"} for match in matches
        )
    if job is None:
        job = Job(
            id=uuid4(),
            employer_group_id=group.id,
            title=normalized.title,
            requisition_id=normalized.requisition_id,
            synthetic=normalized.synthetic,
        )
        session.add(job)
        session.flush()
    incoming = incoming.model_copy(update={"canonical_id": str(job.id)})
    prior_snapshot = session.get(JobSnapshot, job.current_snapshot_id) if job.current_snapshot_id else None
    old_publication = None
    if prior_snapshot and prior_snapshot.structured_fields.get("job_evidence"):
        old_publication = JobEvidence.model_validate(prior_snapshot.structured_fields["job_evidence"]).publication
    if source_record is None:
        source_record = JobSource(
            job_id=job.id,
            source_registry_id=source.id,
            external_id=normalized.external_id,
            source_url=normalized.source_url,
        )
        session.add(source_record)
        session.flush()
    content_hash = hashlib.sha256(normalized.description_text.encode()).hexdigest()
    unique_reviews = {(review["job_id"], review.get("reason")): review for review in review_candidates}
    review_candidates = list(unique_reviews.values())
    source_record.link_evidence = {
        **(source_record.link_evidence or {}),
        "opening": opening.model_dump(mode="json"),
        "identity": incoming.model_dump(mode="json"),
        "requisition_namespace": namespace,
        "identity_review_candidates": review_candidates,
    }
    source_record.source_url = normalized.source_url
    source_record.employer_url = normalized.employer_url
    source_record.application_url = opening.application_url or normalized.application_url
    source_record.final_observed_url = opening.final_url or normalized.final_url
    source_record.last_seen, source_record.last_verified = normalized.fetched_at, opening.checked_at
    source_record.availability = opening.status
    job.title, job.locations, job.work_arrangement = normalized.title, normalized.locations, normalized.work_arrangement
    job.availability = opening.status
    publication = normalized.publication.model_copy()
    if (
        old_publication
        and old_publication.kind in ("ORIGINAL", "LAST_PUBLICATION")
        and old_publication.earliest
        and (not publication.earliest or old_publication.earliest < publication.earliest)
    ):
        publication = old_publication.model_copy()
    # This is a real local identity/repost check, recorded per opening and snapshot. It only
    # covers known retained identities, not unseen reposts elsewhere on the internet.
    local_repost_check = bool(normalized.external_id and not review_candidates)
    if publication.kind == "LAST_PUBLICATION":
        publication = publication.model_copy(update={"repost_checked": local_repost_check})
    if publication.kind in ("ORIGINAL", "LAST_PUBLICATION"):
        job.published_earliest, job.published_latest = publication.earliest, publication.latest
        job.publication_precision = publication.precision
        job.published_at = (
            publication.earliest if publication.kind == "ORIGINAL" and publication.precision == "EXACT" else None
        )
    job.last_published_at, job.source_updated_at = normalized.last_published_at, normalized.source_updated_at
    job.salary_min, job.salary_max = normalized.salary.minimum, normalized.salary.maximum
    job.salary_currency, job.salary_interval = normalized.salary.currency, normalized.salary.interval
    snapshot_id = uuid4()
    staffing_review = source_record.link_evidence.get("staffing_review", {})
    staffing_verified = _complete_review(staffing_review, content_hash=content_hash)
    evidence = _map_evidence(
        normalized,
        opening,
        job,
        group,
        snapshot_id,
        publication,
        staffing=bool((source.capabilities or {}).get("staffing")),
        permanent=staffing_review.get("permanent_placement") if staffing_verified else None,
        payroll_verified=bool(
            staffing_verified and job.entity_id and staffing_review.get("payroll_entity_id") == str(job.entity_id)
        ),
    )
    snapshot = JobSnapshot(
        id=snapshot_id,
        job_id=job.id,
        source_id=source_record.id,
        fetched_at=normalized.fetched_at,
        structured_fields={
            "normalized": normalized.model_dump(mode="json"),
            "employer_pool_evidence": (group.grouping_evidence or {}).get("pool_evidence", {}),
            "job_evidence": evidence.model_dump(mode="json"),
            "identity_checks": {
                "mechanism": "retained-identities-1.0",
                "checked_at": normalized.fetched_at.isoformat(),
                "source_identity": source_key,
                "known_candidates": len(possible),
                "comparisons": comparisons,
                "review_candidates": review_candidates,
                "repost_checked": local_repost_check,
                "coverage": "Local retained source identities, employer requisitions, destinations and similarity only",
            },
        },
        description=normalized.description_text,
        raw_evidence_reference=normalized.raw_sha256,
        content_hash=content_hash,
        content_complete=normalized.description_complete,
    )
    session.add(snapshot)
    session.flush()
    job.current_snapshot_id = snapshot.id
    for candidate in review_candidates:
        target = UUID(candidate["job_id"])
        if target != job.id and not session.scalar(
            select(DuplicateLink.id).where(
                DuplicateLink.candidate_id == job.id,
                DuplicateLink.canonical_id == target,
                DuplicateLink.link_type == "CANDIDATE",
                DuplicateLink.reversed_by_id.is_(None),
            )
        ):
            session.add(
                DuplicateLink(
                    candidate_id=job.id,
                    canonical_id=target,
                    link_type="CANDIDATE",
                    evidence=candidate,
                    mechanism="retained-identities-1.0",
                )
            )
    _tombstone(session, job, source_key, "SOURCE", {"source_url": normalized.source_url})
    if namespace and normalized.requisition_id and not review_candidates:
        _tombstone(
            session,
            job,
            f"req:{namespace}:{normalized.requisition_id}",
            "REQUISITION",
            {"namespace": namespace, "source_id": str(source.id)},
        )
    if incoming.destination_identity_verified and incoming.employer_destination and not review_candidates:
        key = f"destination:{group.id}:{canonical_destination(incoming.employer_destination)}"
        retained_key = session.scalar(select(JobIdentityTombstone).where(JobIdentityTombstone.identity_key == key))
        if retained_key is None or _canonical_job(session, session.get(Job, retained_key.job_id)).id == job.id:
            _tombstone(
                session, job, key, "DESTINATION", {"url": incoming.employer_destination, "source_id": str(source.id)}
            )
    # Exact actionable destination may associate one external application; ambiguity is retained.
    application_url = opening.application_url or normalized.application_url
    if application_url and opening.identity_match and opening.actionable and not review_candidates:
        applications = session.scalars(
            select(Application)
            .where(
                Application.user_id == user_id,
                Application.voided_at.is_(None),
                Application.application_url == application_url,
            )
            .with_for_update()
        ).all()
        if len(applications) == 1 and applications[0].job_id is None:
            applications[0].job_id = job.id
            applications[0].selected_snapshot_id = applications[0].selected_snapshot_id or snapshot.id
    return job, reevaluate_job(session, job.id, user_id, now=normalized.fetched_at)


def run_source(session: Session, source_id: UUID, user_id: UUID, *, query="", connector=None) -> SearchRun:
    from app.connectors import get_connector

    source = session.get(SourceRegistry, source_id)
    if not source:
        raise ValueError("Unknown source")
    run = SearchRun(user_id=user_id, coverage={"source_id": str(source.id)})
    session.add(run)
    session.flush()
    cr = ConnectorRun(
        search_run_id=run.id, source_registry_id=source.id, query={"query": query}, health="NOT_CONFIGURED"
    )
    session.add(cr)
    counts = Counter()
    errors = []
    if not source.enabled:
        errors.append({"code": "NOT_CONFIGURED", "message": "Source is disabled"})
    else:
        try:
            connector = connector or get_connector(source.connector_type)
            cursor = None
            for page in range(20):
                discovery = connector.discover(query, source.tenant, cursor)
                counts["discovered"] += len(discovery.candidates)
                errors.extend(e.model_dump(mode="json") for e in discovery.errors)
                for candidate in discovery.candidates:
                    if counts["fetched"] >= 500:
                        errors.append({"code": "RUN_BUDGET_EXHAUSTED", "message": "Search continues in a later run"})
                        break
                    fetched = connector.fetch(candidate)
                    counts["fetched"] += 1
                    if fetched.outcome != "SUCCESS":
                        errors.extend(e.model_dump(mode="json") for e in fetched.errors)
                        counts["fetch_failed"] += 1
                        continue
                    counts["fetch_success"] += 1
                    normalized = connector.normalize(fetched)
                    counts["complete_description"] += int(normalized.description_complete)
                    opening = connector.verify_opening(normalized)
                    _, evaluation = ingest_normalized(session, source, normalized, opening, user_id=user_id)
                    counts[evaluation.decision] += 1
                cursor = discovery.next_cursor
                cr.cursor = cursor
                if not cursor or counts["fetched"] >= 500:
                    break
            cr.health = connector.health().state
            if not errors:
                source.last_success = datetime.now(UTC)
        except Exception as exc:
            # Database failures propagate to roll back; remote/parser failures remain explicit coverage errors.
            from sqlalchemy.exc import SQLAlchemyError

            if isinstance(exc, SQLAlchemyError):
                raise
            errors.append({"code": "SOURCE_ERROR", "message": type(exc).__name__})
            cr.health = "FAILED"
    if errors and cr.health == "HEALTHY":
        cr.health = "DEGRADED"
    source.configuration_state = cr.health
    source.last_error = errors[-1]["code"] if errors else None
    cr.counts, cr.errors = dict(counts), errors
    cr.finished_at = datetime.now(UTC)
    run.counts, run.errors = dict(counts), errors
    run.state, run.finished_at = ("PARTIAL" if errors else "SUCCEEDED"), cr.finished_at
    session.flush()
    return run
