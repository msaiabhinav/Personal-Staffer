from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, text

from app.applications.service import change, lock_user
from app.auth.crypto import digest
from app.auth.service import failure
from app.db.models import (
    Application,
    EmployerGroup,
    EnrichmentRun,
    InitialDelivery,
    Job,
    JobPerson,
    JobSnapshot,
    PeopleSearchCache,
    Person,
    UserJobState,
    utcnow,
)
from app.db.session import session_factory
from app.people.discovery import (
    GROUPS,
    BraveSearch,
    JobContext,
    ProviderUnavailable,
    SearchResult,
    queries,
    select_people,
    supported_candidate,
)


def owned_job(session, user_id, job_id):
    delivered = session.scalar(
        select(InitialDelivery.id).where(InitialDelivery.user_id == user_id, InitialDelivery.job_id == job_id)
    )
    saved = session.scalar(
        select(UserJobState.id).where(UserJobState.user_id == user_id, UserJobState.job_id == job_id)
    )
    applied = session.scalar(select(Application.id).where(Application.user_id == user_id, Application.job_id == job_id))
    job = session.get(Job, job_id)
    if not job or not (delivered or saved or applied):
        raise failure(404, "JOB_NOT_FOUND", "Job not found in your retained records.")
    return job


def context_for(session, job):
    group = session.get(EmployerGroup, job.employer_group_id)
    snapshot = session.get(JobSnapshot, job.current_snapshot_id) if job.current_snapshot_id else None
    facts = snapshot.structured_fields if snapshot else {}
    # Named relationship claims are accepted only with retained structured
    # extraction evidence, never inferred from a company-wide employee title.
    relationship = facts.get("people_context", {})
    evidence = relationship.get("evidence_reference")
    return JobContext(
        str(job.id),
        group.canonical_name,
        job.title,
        relationship.get("department"),
        relationship.get("named_recruiter") if evidence else None,
        relationship.get("named_hiring_manager") if evidence else None,
        evidence,
    )


def enrich(user_id: UUID, job_id: UUID, settings, *, session_maker=None, provider=None):
    """Owns short transactions; reserves every billable query before the HTTP call.

    A crash after reservation can consume budget without results, but cannot
    silently refund a query that may have been billed. No transaction spans HTTP.
    """
    make_session = session_maker or session_factory()
    run_id = uuid4()
    with make_session.begin() as session:
        lock_user(session, user_id)
        job = owned_job(session, user_id, job_id)
        context = context_for(session, job)
        configured = settings.people_search_provider == "brave" and bool(settings.people_search_api_key)
        run = EnrichmentRun(
            id=run_id,
            job_id=job_id,
            state="SEARCHING" if configured or provider else "NOT_CONFIGURED",
            attempts=1,
            query_count=0,
            discovered_count=0,
            approved_count=0,
            cost_units=0,
        )
        session.add(run)
        if not configured and provider is None:
            return {"state": "NOT_CONFIGURED", "run_id": str(run_id), "approved_count": 0, "query_count": 0}
    search = provider or BraveSearch(settings.people_search_api_key)
    collected = []
    end_state, safe_error = "READY", None
    for query in queries(context):
        query_hash = digest(query.casefold())
        cached_results = None
        with make_session.begin() as session:
            # A single backend provider budget covers all jobs/devices/users.
            session.execute(text("SELECT pg_advisory_xact_lock(783210420)"))
            cached = session.scalar(select(PeopleSearchCache).where(PeopleSearchCache.query_hash == query_hash))
            if cached and cached.observed_at >= utcnow() - timedelta(days=1):
                cached_results = [
                    SearchResult(
                        row["url"], row["title"], row["description"], datetime.fromisoformat(row["observed_at"])
                    )
                    for row in cached.result_payload.get("results", [])
                ]
            else:
                day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                used = session.scalar(
                    select(func.coalesce(func.sum(EnrichmentRun.query_count), 0)).where(
                        EnrichmentRun.started_at >= day_start
                    )
                )
                if used >= settings.people_daily_query_budget:
                    end_state = "PENDING_BUDGET"
                    break
                run = session.get(EnrichmentRun, run_id)
                run.query_count += 1
                run.cost_units += 1
        if cached_results is not None:
            results = cached_results
        else:
            try:
                results = search.search(query)
            except ProviderUnavailable as exc:
                end_state, safe_error = exc.state, exc.reason
                break
            except (KeyError, ValueError, TypeError):
                end_state, safe_error = "UNAVAILABLE", "Public search returned an unreadable result"
                break
            with make_session.begin() as session:
                session.execute(text("SELECT pg_advisory_xact_lock(783210420)"))
                cached = session.scalar(select(PeopleSearchCache).where(PeopleSearchCache.query_hash == query_hash))
                payload = {"results": [{**asdict(row), "observed_at": row.observed_at.isoformat()} for row in results]}
                if cached:
                    cached.result_payload, cached.observed_at = payload, utcnow()
                else:
                    session.add(
                        PeopleSearchCache(
                            query_hash=query_hash, query_text=query, result_payload=payload, observed_at=utcnow()
                        )
                    )
        collected.extend(results)
    candidates = [person for row in collected if (person := supported_candidate(row, context, utcnow()))]
    selected = select_people(candidates)
    with make_session.begin() as session:
        lock_user(session, user_id)
        run = session.get(EnrichmentRun, run_id)
        run.discovered_count = len({row.url for row in collected})
        run.approved_count = len(selected)
        run.last_error = safe_error
        run.state = (
            end_state
            if end_state != "READY"
            else "READY"
            if len(selected) >= 10
            else "PARTIALLY_FOUND"
            if selected
            else "NO_CREDIBLE_PROFILES"
        )
        for candidate in selected:
            person = session.scalar(select(Person).where(Person.linkedin_url == candidate.profile_url))
            if not person:
                person = Person(
                    id=uuid4(),
                    linkedin_url=candidate.profile_url,
                    name=candidate.name,
                    headline=candidate.role,
                    company=candidate.company,
                    checked_at=candidate.checked_at,
                )
                session.add(person)
            person.name, person.headline, person.company = candidate.name, candidate.role, candidate.company
            person.checked_at = candidate.checked_at
            person.employment_evidence = {
                "source_url": candidate.source_url,
                "text": candidate.evidence_text,
                "verification": candidate.verification,
                "observed_at": candidate.checked_at.isoformat(),
            }
            session.flush()
            relation = session.scalar(
                select(JobPerson).where(JobPerson.job_id == job_id, JobPerson.person_id == person.id)
            )
            if not relation:
                relation = JobPerson(job_id=job_id, person_id=person.id)
                session.add(relation)
            relation.relationship_group = candidate.group
            relation.evidence_classification = candidate.evidence_label
            relation.supporting_references = [candidate.source_url] + (
                [context.evidence_reference] if context.evidence_reference else []
            )
            relation.explanation, relation.checked_at = candidate.explanation, candidate.checked_at
        change(session, user_id, "jobs", job_id, 1)
        return {
            "state": run.state,
            "run_id": str(run_id),
            "approved_count": len(selected),
            "query_count": run.query_count,
        }


def job_people(session, user_id, job_id, settings):
    job = owned_job(session, user_id, job_id)
    run = session.scalar(
        select(EnrichmentRun)
        .where(EnrichmentRun.job_id == job_id)
        .order_by(EnrichmentRun.started_at.desc(), EnrichmentRun.id.desc())
        .limit(1)
    )
    records = list(
        session.execute(
            select(Person, JobPerson)
            .join(JobPerson, JobPerson.person_id == Person.id)
            .where(JobPerson.job_id == job_id)
        )
    )
    records.sort(key=lambda row: (GROUPS.index(row[1].relationship_group), row[0].name.casefold(), str(row[0].id)))
    rows = [
        {
            "id": str(person.id),
            "name": person.name,
            "role": person.headline,
            "company": person.company,
            "linkedin_url": person.linkedin_url,
            "group": relation.relationship_group,
            "evidence_label": relation.evidence_classification,
            "explanation": relation.explanation,
            "checked_at": relation.checked_at,
            "evidence": person.employment_evidence,
            "stale": relation.checked_at < utcnow() - timedelta(days=30),
            "job_id": str(job.id),
        }
        for person, relation in records[:10]
    ]
    state = (
        run.state if run else "PENDING" if settings.integration_state("people") == "CONFIGURED" else "NOT_CONFIGURED"
    )
    return {
        "job_id": str(job.id),
        "title": job.title,
        "state": state,
        "items": rows,
        "next_cursor": None,
        "query_count": run.query_count if run else 0,
        "approved_count": run.approved_count if run else 0,
    }
