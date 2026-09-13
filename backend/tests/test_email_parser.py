from datetime import UTC, datetime, timedelta

import pytest

from app.email.parser import (
    ApplicationIdentity,
    MailEvidence,
    automatic_transition,
    classify,
    decode_message,
    match_application,
)

NOW = datetime(2026, 9, 12, 12, tzinfo=UTC)


def mail(body, subject="Application update", thread="t1"):
    import base64

    return decode_message(
        {
            "id": "m1",
            "threadId": thread,
            "internalDate": str(int(NOW.timestamp() * 1000)),
            "labelIds": ["INBOX"],
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "noreply@shared-ats.example"},
                    {"name": "Subject", "value": subject},
                    {
                        "name": "Authentication-Results",
                        "value": "mx.google.com; dmarc=pass header.from=shared-ats.example",
                    },
                ],
                "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
            },
        }
    )


def app(identifier="a1", title="Data Analyst", **kwargs):
    return ApplicationIdentity(identifier, "Example Corporation", title, NOW - timedelta(days=3), **kwargs)


@pytest.mark.parametrize(
    "body,status",
    [
        ("Thank you for applying for Data Analyst at Example Corporation", "APPLIED"),
        ("We invite you to an interview for Data Analyst at Example Corporation", "INTERVIEWING"),
        ("Please complete the technical assessment for Data Analyst at Example Corporation", "ASSESSMENT"),
        ("Your application was rejected for Data Analyst at Example Corporation", "REJECTED"),
        ("We are pleased to offer you the Data Analyst position at Example Corporation", "OFFER"),
    ],
)
def test_email_supported_templates(body, status):
    message = mail(body)
    meaning = classify(message)
    match = match_application(message, [app()])
    assert meaning.status == status
    assert match.application_id == "a1"
    assert automatic_transition(
        "APPLIED", NOW - timedelta(days=1), False, message, meaning, match, sender_trusted=True
    )[0]


def test_at_39_ambiguous_rejection_never_selects_arbitrary_application():
    message = mail("Your application was rejected at Example Corporation for Data Analyst")
    match = match_application(message, [app(), app("a2")])
    assert match.state == "AMBIGUOUS"
    assert match.application_id is None
    assert not automatic_transition("APPLIED", NOW, False, message, classify(message), match)[0]


def test_sender_alone_cannot_match_application():
    message = mail("Your application was rejected")
    assert match_application(message, [app()]).state == "UNMATCHED"


def test_requisition_requires_employer():
    message = mail("Your application was rejected for requisition R100")
    assert match_application(message, [app(requisition_id="R100")]).state == "UNMATCHED"


def test_at_40_delayed_confirmation_does_not_regress_interview():
    message = mail("Thank you for applying for Data Analyst at Example Corporation")
    match = match_application(message, [app()])
    assert automatic_transition(
        "INTERVIEWING", NOW - timedelta(days=1), False, message, classify(message), match, sender_trusted=True
    ) == (False, "CONFIRMATION_DOES_NOT_REGRESS")


def test_at_41_manual_correction_is_not_reapplied():
    message = mail("Your application was rejected for Data Analyst at Example Corporation")
    assert automatic_transition(
        "APPLIED", NOW, True, message, classify(message), match_application(message, [app()])
    ) == (False, "EMAIL_EFFECT_CORRECTED")


def test_at_42_generic_status_and_unmatched_confirmation_require_review():
    assert classify(mail("Your status has changed")).review
    confirmation = mail("Thank you for applying")
    assert match_application(confirmation, [app()]).state == "UNMATCHED"


def test_forwarded_and_conditional_messages_review():
    assert classify(
        MailEvidence("m", "t", "sender", "Fwd: Interview", "Please complete the assessment", NOW, True)
    ).review
    assert classify(mail("If we invite you to an interview, we will contact you.")).review


def test_old_effect_does_not_overwrite_newer_stage():
    message = mail("Your application was rejected for Data Analyst at Example Corporation")
    assert (
        automatic_transition(
            "INTERVIEWING",
            NOW + timedelta(hours=1),
            False,
            message,
            classify(message),
            match_application(message, [app()]),
            sender_trusted=True,
        )[1]
        == "OLDER_THAN_CURRENT_EVENT"
    )


def test_html_email_no_scripts_images_attachments_or_quoted_status():
    import base64

    content = '<div>Thank you for applying</div><script>steal()</script><img src="https://tracker.invalid/x">\nOn Monday person wrote:\nYour application was rejected'
    message = decode_message(
        {
            "id": "m",
            "threadId": "t",
            "internalDate": str(int(NOW.timestamp() * 1000)),
            "payload": {
                "mimeType": "text/html",
                "headers": [{"name": "Subject", "value": "Received"}],
                "body": {"data": base64.urlsafe_b64encode(content.encode()).decode()},
            },
        }
    )
    assert "steal" not in message.body
    assert "rejected" not in message.body
    assert classify(message).status == "APPLIED"


def test_not_selected_and_invited_to_interview_phrasings_classify():
    from app.email.parser import classify_text

    assert classify_text("You were not selected for Sr. Analyst, Commercial Analytics at Example") == "REJECTED"
    assert classify_text("You are invited to interview with Example") == "INTERVIEWING"
    assert classify_text("Reminder about your interview with Example") is None  # No new stage.
    assert classify_text("Thank you for applying to Example") is None  # Confirmations are not a stage.
