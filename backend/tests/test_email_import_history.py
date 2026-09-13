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
        ("Thank you for applying to Spring Example", "no-reply@springexample.com", "Spring Example", None, "MEDIUM"),
        (
            "Application received by Metro Transit Authority",
            "GovJobs <noreply@governmentjobs.com>",
            "Metro Transit Authority",
            None,
            "MEDIUM",
        ),
        ("Contoso LLC-Thank you for your application, Sai", "ADP <noreply@adp.com>", "Contoso LLC", None, "MEDIUM"),
        (
            "Thank you for applying for Revenue Operations Analyst at Sitecore Example",
            "no-reply@example-ats.com",
            "Sitecore Example",
            "Revenue Operations Analyst",
            "HIGH",
        ),
        (
            "Thank You for Applying to the role Supply Chain Analyst at Post Example",
            "no-reply@example-ats.com",
            "Post Example",
            "Supply Chain Analyst",
            "HIGH",
        ),
        (
            "Sai Abhinav, Thank You for Applying to Brex Example!",
            "no-reply@example-ats.com",
            "Brex Example",
            None,
            "MEDIUM",
        ),
        (
            "We have received your application for Data Solutions Analyst",
            '"Liberty Example @" <jobs@libertyexample.com>',
            "Liberty Example",
            "Data Solutions Analyst",
            "MEDIUM",
        ),
        (
            "Your application for the Business Analytics Analyst position",
            "Oracle <noreply@oracle.example>",
            "Oracle",
            "Business Analytics Analyst",
            "MEDIUM",
        ),
        (
            "UBC Careers | Sr. Data Analyst - Patient Access Services - Remote",
            "no-reply@example-ats.com",
            "UBC",
            "Sr. Data Analyst",
            "MEDIUM",
        ),
        (
            "Nordstrom Example: Application Confirmation",
            "no-reply@example-ats.com",
            "Nordstrom Example",
            None,
            "MEDIUM",
        ),
        (
            "Thank You for Applying at Business Services Building",
            '"Uni Example" <uuhc+autoreply@icims.example>',
            "Uni Example",
            None,
            "LOW",
        ),
    ],
)
def test_subject_rules_extract_company_and_title(subject, sender, company, title, confidence):
    proposal = _propose(subject, sender)
    assert proposal.company == company
    if title is None:
        assert proposal.title == import_history._PLACEHOLDER_TITLE
    else:
        assert proposal.title == title
    assert proposal.confidence == confidence


def test_generic_subject_falls_back_to_sender_display_name_not_ats_domain():
    proposal = _propose("Thank you for applying!", '"Fabrikam Careers" <do-not-reply@mail.paylocity.com>')
    assert proposal.company == "Fabrikam" and proposal.confidence == "LOW"
    assert proposal.title == import_history._PLACEHOLDER_TITLE
    assert proposal.title == import_history._PLACEHOLDER_TITLE
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


def test_bulk_employer_mail_is_never_proposed_as_application_evidence():
    from app.email.import_history import _BULK_MAIL

    for subject in [
        "News from Schneider Electric - Innovation, Partnerships & People",
        "Registrations Are OPEN: Go Green 2026 Starts Now!",
        "Digital Talent News - Schneider Electric",
        "Confirm your identity",
    ]:
        assert _BULK_MAIL.search(subject), subject
    for subject in [
        "Thank You for Your Interest in The Home Depot",
        "RE: Healthcare Analyst Role - Resume for Consideration",
        "Your application status has changed",
    ]:
        assert not _BULK_MAIL.search(subject), subject
