"""Company-centric read model (ADR 0006) on real PostgreSQL."""

from datetime import timedelta
from uuid import uuid4

import pytest
import test_database_core
from sqlalchemy.orm import Session

from app.applications.service import lock_user
from app.db.models import (
    Application,
    ApplicationEvent,
    EmailApplicationLink,
    EmailMessage,
    EmployerGroup,
    GmailConnection,
    ReviewItem,
    User,
    WatchlistEntry,
    utcnow,
)
from app.email.companies import company_view, search_companies

pytestmark = pytest.mark.postgres
engine = test_database_core.pg_engine


@pytest.fixture
def owner(engine):
    with Session(engine) as session, session.begin():
        user = User(id=uuid4(), google_subject="subject", verified_email="owner@example.test", display_name="Owner")
        session.add(user)
        session.flush()
        return user.id


def _application(session, owner, company, title, status="APPLIED", days=10):
    app = Application(
        id=uuid4(),
        user_id=owner,
        title=title,
        company=company,
        applied_at=utcnow() - timedelta(days=days),
        applied_date_source="USER",
        current_status=status,
        revision=1,
        notes="",
        added_by_user=True,
    )
    session.add(app)
    session.flush()
    session.add(
        ApplicationEvent(
            application_id=app.id,
            event_type="APPLIED",
            status="APPLIED",
            effective_at=app.applied_at,
            operation_id=f"apply-{app.id}",
        )
    )
    if status != "APPLIED":
        session.add(
            ApplicationEvent(
                application_id=app.id,
                event_type="STATUS_CHANGED",
                status=status,
                effective_at=app.applied_at + timedelta(days=2),
                actor="EMAIL",
                operation_id=f"status-{app.id}",
                evidence={"status_evidence": "we decided not to move forward"},
            )
        )
    session.flush()
    return app


def _mail(session, conn, gmail_id, thread, sender, subject, classification, days, status=None):
    row = EmailMessage(
        id=uuid4(),
        connection_id=conn.id,
        gmail_message_id=gmail_id,
        thread_id=thread,
        sender=sender,
        subject=subject,
        excerpt="Thank you for applying. " + subject,
        received_at=utcnow() - timedelta(days=days),
        classification=classification,
        evidence={"proposed_status": status, "match_state": "UNMATCHED"},
    )
    session.add(row)
    session.flush()
    return row


def test_company_view_assembles_applications_threads_and_reviews(engine, owner):
    with Session(engine) as session, session.begin():
        lock_user(session, owner)
        kraft = _application(session, owner, "Kraft Heinz", "Sr. Customer Sales Analyst", status="REJECTED", days=30)
        _application(session, owner, "Kraft Heinz Company", "Business Analyst", days=5)
        _application(session, owner, "Uber", "Data Analyst", days=8)
        conn = GmailConnection(
            id=uuid4(),
            user_id=owner,
            google_identity="owner@example.test",
            refresh_token_encrypted="x",
            granted_scopes=[],
            sync_health="HEALTHY",
        )
        session.add(conn)
        session.flush()
        confirmation = _mail(
            session,
            conn,
            "m1",
            "t1",
            "KraftHeinz Careers <no-reply@myworkday.com>",
            "Thank you for applying to Kraft Heinz",
            "CONFIRMATION",
            30,
            "APPLIED",
        )
        session.add(
            EmailApplicationLink(email_id=confirmation.id, application_id=kraft.id, match_state="USER_CONFIRMED")
        )
        _mail(
            session,
            conn,
            "m2",
            "t1",
            "KraftHeinz Careers <no-reply@myworkday.com>",
            "Your application - Kraft Heinz update",
            "REJECTION",
            28,
            "REJECTED",
        )
        stray = _mail(
            session,
            conn,
            "m3",
            "t2",
            "Talent <talent@kraftheinz.com>",
            "Getting Started: Welcome to KraftHeinz's Talent Community",
            "UNKNOWN_TEMPLATE",
            3,
        )
        session.add(
            ReviewItem(
                id=uuid4(), user_id=owner, review_type="EMAIL_APPLICATION", target_id=stray.id, reason="UNMATCHED"
            )
        )
        _mail(session, conn, "m4", "t3", "Uber Careers <noreply@uber.com>", "Your Uber application", "REJECTION", 6)
        group = EmployerGroup(canonical_name="Kraft Heinz", normalized_name="kraft heinz", grouping_evidence={})
        session.add(group)
        session.flush()
        session.add(WatchlistEntry(user_id=owner, employer_group_id=group.id))
        kraft_id = str(kraft.id)
    with Session(engine) as session:
        view = company_view(session, owner, "kraft heinz")
        assert view["name"] == "Kraft Heinz"
        assert view["summary"]["applications"] == 2  # "Kraft Heinz Company" collapses onto the same key
        assert view["summary"]["emails"] == 3 and view["summary"]["threads"] == 2
        assert view["summary"]["open_reviews"] == 1 and view["summary"]["watched"] is True
        assert view["summary"]["email_kinds"] == {"Application confirmed": 1, "Rejected": 1, "Employer email": 1}
        newest_thread = view["threads"][0]
        assert newest_thread["thread_id"] == "t2" and newest_thread["messages"][0]["open_review_id"]
        older = view["threads"][1]["messages"]
        assert [m["kind"] for m in older] == ["Application confirmed", "Rejected"]
        assert older[0]["linked_application_id"] == kraft_id and older[0]["link_state"] == "USER_CONFIRMED"
        rejected = next(a for a in view["applications"] if a["id"] == kraft_id)
        assert [e["status"] for e in rejected["events"]] == ["APPLIED", "REJECTED"]
        assert rejected["events"][1]["reason"] == "we decided not to move forward"
        assert view["watchlist"]["resolution_state"] == "REGISTERED" and view["postings"]["sources"] == 0
        # Uber mail never leaks into the Kraft Heinz view, and vice versa.
        assert all("uber" not in m["subject"].lower() for t in view["threads"] for m in t["messages"])
        uber = company_view(session, owner, "Uber")
        assert uber["summary"] == {
            "applications": 1,
            "latest_status": "AWAITING_RESPONSE",
            "emails": 1,
            "threads": 1,
            "email_kinds": {"Rejected": 1},
            "open_reviews": 0,
            "watched": False,
        }
        assert company_view(session, owner, "Nobody Corp")["summary"]["applications"] == 0

        results = search_companies(session, owner, "kra")
        assert results[0]["name"] == "Kraft Heinz" and results[0]["applications"] == 2 and results[0]["watched"]
        assert results[0]["emails"] >= 2
        assert search_companies(session, owner, "  ") == []
        assert [r["name"] for r in search_companies(session, owner, "uber")] == ["Uber"]
