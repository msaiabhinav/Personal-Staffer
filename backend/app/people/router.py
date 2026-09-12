from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.applications.service import execute_operation
from app.auth.dependencies import current_user
from app.config import get_settings
from app.db.models import Application, EmployerGroup, InitialDelivery, Job, User, UserJobState
from app.db.session import get_session
from app.email.router import queue_work
from app.people.service import job_people, owned_job

router = APIRouter(tags=["people"])
DB = Annotated[Session, Depends(get_session)]
Owner = Annotated[User, Depends(current_user)]


@router.get("/jobs/{job_id}/people")
def people_for_job(job_id: UUID, user: Owner, session: DB):
    return job_people(session, user.id, job_id, get_settings())


@router.get("/people")
def people(
    user: Owner,
    session: DB,
    job_id: UUID | None = None,
    company: str | None = None,
    q: str | None = None,
    cursor: UUID | None = None,
    limit: int = Query(default=25, ge=1, le=100),
):
    retained = select(InitialDelivery.job_id).where(InitialDelivery.user_id == user.id)
    saved = select(UserJobState.job_id).where(UserJobState.user_id == user.id)
    applied = select(Application.job_id).where(Application.user_id == user.id, Application.job_id.is_not(None))
    query = (
        select(Job)
        .join(EmployerGroup, Job.employer_group_id == EmployerGroup.id)
        .where(or_(Job.id.in_(retained), Job.id.in_(saved), Job.id.in_(applied)))
    )
    if job_id:
        query = query.where(Job.id == job_id)
    if company:
        query = query.where(EmployerGroup.canonical_name.ilike("%" + company[:255] + "%"))
    if q:
        query = query.where(
            or_(Job.title.ilike("%" + q[:255] + "%"), EmployerGroup.canonical_name.ilike("%" + q[:255] + "%"))
        )
    if cursor:
        query = query.where(Job.id > cursor)
    jobs = list(session.scalars(query.order_by(Job.id).limit(limit + 1)))
    return {
        "items": [job_people(session, user.id, job.id, get_settings()) for job in jobs[:limit]],
        "next_cursor": str(jobs[limit - 1].id) if len(jobs) > limit else None,
    }


@router.post("/jobs/{job_id}/people-refresh", status_code=202)
def refresh_people(
    job_id: UUID,
    user: Owner,
    session: DB,
    operation_id: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
):
    owned_job(session, user.id, job_id)
    return execute_operation(
        session,
        user.id,
        operation_id,
        "people.refresh",
        job_id,
        {},
        lambda: queue_work(
            session, user.id, "people.enrich", {"user_id": str(user.id), "job_id": str(job_id)}, operation_id
        ),
    )
