"""Extraction rules for the one-time Gmail history import (subject/sender shapes seen live)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.email import import_history


def _propose(subject, sender="Careers <no-reply@example-ats.com>"):
    review = SimpleNamespace(id=uuid4(), revision=1)
    mail = SimpleNamespace(id=uuid4(), subject=subject, sender=sender, received_at=datetime(2026, 8, 1, tzinfo=UTC))

    class Session:
        def execute(self, _stmt):
            return SimpleNamespace(all=lambda: [(review, mail)])

    return import_history.propose(Session(), uuid4())[0]


@pytest.mark.parametrize(
    "subject,sender,company,title,confidence",
    [
        (
            "Acme Foods: Application received – Commercial Reporting and Analytics Analyst - Boise",
            "Acme Careers <careers@successfactors.com>",
            "Acme Foods",
            "Commercial Reporting and Analytics Analyst",
            "HIGH",
        ),
        (
            "Your Application with Northwind Medical - Senior Sales Operations Analyst - Technology (63123)",
            "Northwind <talent@northwind.example>",
            "Northwind Medical",
            "Senior Sales Operations Analyst - Technology",
            "HIGH",
        ),
        (
            "Your application for the position Business Intelligence & Project Analyst at M. G. Example",
            "ADP <noreply@adp.com>",
            "M. G. Example",
            "Business Intelligence & Project Analyst",
            "HIGH",
        ),
        (
            "Business Performance Analyst Full time-26003447 at Example Health Resources",
            "Example Health <jobs@examplehealth.org>",
            "Example Health Resources",
            "Business Performance Analyst",
            "HIGH",
        ),
        ("Thank you for applying to Spring Example", "no-reply@springexample.com", "Spring Example", None, "LOW"),
        (
            "Application received by Metro Transit Authority",
            "GovJobs <noreply@governmentjobs.com>",
            "Metro Transit Authority",
            None,
            "LOW",
        ),
        ("Contoso LLC-Thank you for your application, Sai", "ADP <noreply@adp.com>", "Contoso LLC", None, "LOW"),
    ],
)
def test_subject_rules_extract_company_and_title(subject, sender, company, title, confidence):
    proposal = _propose(subject, sender)
    assert proposal.company == company
    if title is None:
        assert proposal.title == subject  # Subject kept verbatim when no title is readable.
    else:
        assert proposal.title == title
    assert proposal.confidence == confidence


def test_generic_subject_falls_back_to_sender_display_name_not_ats_domain():
    proposal = _propose("Thank you for applying!", '"Fabrikam Careers" <do-not-reply@mail.paylocity.com>')
    assert proposal.company == "Fabrikam" and proposal.confidence == "LOW"
    ats_only = _propose("Thank You for Your Application!", "noreply@myworkday.com")
    assert ats_only.company is None  # Never name the ATS as the employer.


def test_repeated_confirmation_for_same_company_and_title_links_instead_of_creating():
    review_a, review_b = SimpleNamespace(id=uuid4(), revision=1), SimpleNamespace(id=uuid4(), revision=1)
    mails = [
        SimpleNamespace(
            id=uuid4(),
            subject="Your application to Workhelix Example",
            sender="a@workhelix.example",
            received_at=datetime(2026, 8, 1, tzinfo=UTC),
        ),
        SimpleNamespace(
            id=uuid4(),
            subject="Thank you for applying to Workhelix Example",
            sender="b@us.greenhouse-mail.io",
            received_at=datetime(2026, 8, 2, tzinfo=UTC),
        ),
    ]

    class Session:
        def execute(self, _stmt):
            return SimpleNamespace(all=lambda: [(review_a, mails[0]), (review_b, mails[1])])

    first, second = import_history.propose(Session(), uuid4())
    assert first.action == "CREATE" and second.action == "LINK" and second.link_to == str(first.review_id)
