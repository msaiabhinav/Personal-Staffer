"""Sender and hostile MIME effects on actual PostgreSQL application projections."""

from uuid import uuid4

import pytest
import test_auth_email_people_postgres as db_fixtures
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_auth_email_people_postgres import message, seed_application, seed_connection

from app.applications.service import lock_user
from app.db.models import ApplicationEvent, EmailMessage, EmployerBrand, EmployerGroup, Job, ReviewItem
from app.email.service import process_message

engine = db_fixtures.engine
owner = db_fixtures.owner
pytestmark = pytest.mark.postgres


def test_authenticated_shared_ats_requires_review_before_any_event(engine, owner):
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        application = seed_application(session, owner)
        connection = seed_connection(session, owner)
        assert process_message(session, connection, message()) == "REVIEW"
        assert application.current_status == "APPLIED"
        assert session.scalar(select(func.count()).select_from(ApplicationEvent)) == 1
        row = session.scalar(select(EmailMessage))
        assert row.evidence["sender_security"]["authenticated"] is True
        assert row.evidence["sender_security"]["trusted"] is False
        assert session.scalar(select(ReviewItem)).reason == "SENDER_EMPLOYER_ASSOCIATION_UNREVIEWED"


def test_registered_official_domain_with_google_alignment_can_update(engine, owner):
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        group = EmployerGroup(id=uuid4(), canonical_name="Example Corporation", normalized_name="example corporation")
        session.add(group)
        session.flush()
        session.add(
            EmployerBrand(group_id=group.id, display_name="Example Corporation", canonical_domain="employer.example")
        )
        job = Job(employer_group_id=group.id, title="Data Analyst")
        session.add(job)
        session.flush()
        application = seed_application(session, owner)
        application.job_id = job.id
        connection = seed_connection(session, owner)
        payload = message()
        for header in payload["payload"]["headers"]:
            if header["name"] == "From":
                header["value"] = "recruiting@employer.example"
            if header["name"] == "Authentication-Results":
                header["value"] = "mx.google.com; dmarc=pass header.from=employer.example"
        assert process_message(session, connection, payload) == "APPLIED"
        assert application.current_status == "REJECTED"
        assert (
            session.scalar(select(EmailMessage)).evidence["sender_security"]["reason"]
            == "AUTHENTICATED_OFFICIAL_EMPLOYER_DOMAIN"
        )


def test_malformed_base64_commits_review_and_following_message_can_process(engine, owner):
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        application = seed_application(session, owner)
        connection = seed_connection(session, owner)
        malformed = message("malformed")
        malformed["payload"]["body"]["data"] = "%%%"
        assert process_message(session, connection, malformed) == "REVIEW"
        assert process_message(session, connection, message("next-good")) == "REVIEW"
        assert application.current_status == "APPLIED"
        assert session.scalar(select(func.count()).select_from(ReviewItem)) == 2
