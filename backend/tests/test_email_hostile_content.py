import base64
from datetime import UTC, datetime, timedelta

import pytest

from app.email.parser import (
    MAX_MIME_DEPTH,
    MAX_MIME_PARTS,
    ApplicationIdentity,
    automatic_transition,
    classify,
    decode_message,
    match_application,
    sender_trust,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
BODY = "Your application was rejected for Data Analyst at Example Corporation"


def payload(
    body=BODY,
    mime="text/plain",
    sender="recruiter@example.test",
    auth="mx.google.com; dmarc=pass header.from=example.test",
):
    return {
        "id": "hostile-case",
        "threadId": "one",
        "internalDate": str(int(NOW.timestamp() * 1000)),
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": mime,
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": "Application update"},
                {"name": "Authentication-Results", "value": auth},
            ],
            "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()},
        },
    }


def trusted(message):
    return sender_trust(message, official_domains=["example.test"], mailbox_identity="owner@example.test")


def transition(message, trust):
    identity = ApplicationIdentity("app1", "Example Corporation", "Data Analyst", NOW - timedelta(days=1))
    return automatic_transition(
        "APPLIED",
        identity.applied_at,
        False,
        message,
        classify(message),
        match_application(message, [identity]),
        sender_trusted=trust["trusted"],
    )


@pytest.mark.parametrize(
    "quote",
    [
        f"<blockquote>{BODY}</blockquote>",
        f'<div class="gmail_quote">{BODY}</div>',
        f'<div class="gmail_quote gmail_quote_container">{BODY}</div>',
        f'<div class="yahoo_quoted">{BODY}</div>',
        f'<div id="divRplyFwdMsg">Earlier message</div><p>{BODY}</p>',
    ],
)
def test_quoted_html_rejection_does_not_become_current_stage(quote):
    message = decode_message(payload("<p>Here is a copy of the earlier correspondence.</p>" + quote, mime="text/html"))
    assert "rejected" not in message.body
    assert classify(message).status is None
    assert not transition(message, trusted(message))[0]


def test_current_interview_survives_quoted_rejection():
    message = decode_message(
        payload(
            "<p>We invite you to an interview for Data Analyst at Example Corporation.</p><blockquote>"
            + BODY
            + "</blockquote>",
            mime="text/html",
        )
    )
    assert classify(message).status == "INTERVIEWING"
    assert transition(message, trusted(message))[0]


def test_attached_rfc822_without_filename_is_not_recursively_interpreted():
    data = payload("Please see attached correspondence.")
    data["payload"]["mimeType"] = "multipart/mixed"
    data["payload"]["parts"] = [
        {
            "mimeType": "text/plain",
            "body": {"data": base64.urlsafe_b64encode(b"Please see attached correspondence.").decode()},
        },
        {
            "mimeType": "message/rfc822",
            "parts": [{"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(BODY.encode()).decode()}}],
        },
    ]
    message = decode_message(data)
    assert "rejected" not in message.body
    assert "ATTACHMENT_IGNORED" in message.content_omissions


@pytest.mark.parametrize("bad", ["%%%", "a", "not valid base64!", "😀"])
def test_malformed_base64_becomes_review_instead_of_exception(bad):
    data = payload()
    data["payload"]["body"]["data"] = bad
    message = decode_message(data)
    assert "MALFORMED_BASE64" in message.content_issues
    assert classify(message).review
    assert not trusted(message)["trusted"]


def test_mime_depth_and_part_budgets_force_review():
    deep = {"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(BODY.encode()).decode()}}
    for _ in range(MAX_MIME_DEPTH + 2):
        deep = {"mimeType": "multipart/mixed", "parts": [deep]}
    data = payload()
    deep["headers"] = data["payload"]["headers"]
    data["payload"] = deep
    assert "MIME_STRUCTURE_LIMIT" in decode_message(data).content_issues
    data = payload()
    data["payload"]["mimeType"] = "multipart/mixed"
    data["payload"]["parts"] = [{"mimeType": "text/plain", "body": {}}] * (MAX_MIME_PARTS + 1)
    assert "MIME_STRUCTURE_LIMIT" in decode_message(data).content_issues


@pytest.mark.parametrize(
    "auth",
    [
        "other.example; dmarc=pass header.from=example.test",
        "mx.google.com; dmarc=fail header.from=example.test",
        "mx.google.com; spf=pass smtp.mailfrom=example.test",
        "mx.google.com; dmarc=pass header.from=evil.test",
        "mx.google.com; dmarc=pass header.from=example.test; dmarc=fail header.from=evil.test",
        "mx.google.com; dmarc=pass header.from=example.test header.from=evil.test",
    ],
)
def test_authentication_results_cannot_be_guessed_or_ambiguous(auth):
    message = decode_message(payload(auth=auth))
    assert not trusted(message)["trusted"]
    assert not transition(message, trusted(message))[0]


@pytest.mark.parametrize(
    "header",
    [
        {"name": "From", "value": "attacker@evil.test"},
        {"name": "Authentication-Results", "value": "mx.google.com; dmarc=pass header.from=example.test"},
    ],
)
def test_duplicate_from_or_auth_headers_require_review(header):
    data = payload()
    data["payload"]["headers"].append(header)
    assert not trusted(decode_message(data))["trusted"]


@pytest.mark.parametrize(
    "sender", ["a@example.test, b@example.test", "Employer <attacker@evil.test>", "invalid sender"]
)
def test_actual_from_address_controls_alignment(sender):
    assert not trusted(decode_message(payload(sender=sender)))["trusted"]


@pytest.mark.parametrize("label", ["SPAM", "TRASH", "DRAFT", "SENT"])
def test_untrusted_gmail_labels_cannot_mutate_applications(label):
    data = payload()
    data["labelIds"].append(label)
    message = decode_message(data)
    assert trusted(message)["reason"] == "EXCLUDED_GMAIL_LABEL"
    assert not transition(message, trusted(message))[0]


def test_authenticated_self_sent_and_unassociated_ats_mail_require_review():
    message = decode_message(payload(sender="owner@example.test"))
    assert trusted(message)["reason"] == "SELF_SENT_MESSAGE"
    message = decode_message(
        payload(sender="recruiting@shared-ats.test", auth="mx.google.com; dmarc=pass header.from=shared-ats.test")
    )
    assert trusted(message)["reason"] == "SENDER_EMPLOYER_ASSOCIATION_UNREVIEWED"
    proof = sender_trust(message, reviewed_senders=["recruiting@shared-ats.test"])
    assert proof["trusted"]
    assert not sender_trust(message, reviewed_senders=["other@shared-ats.test"])["trusted"]


def test_no_auto_transition_without_explicit_sender_affiliation():
    message = decode_message(payload())
    assert transition(message, trusted(message))[0]
    identity = ApplicationIdentity("app1", "Example Corporation", "Data Analyst", NOW - timedelta(days=1))
    assert not automatic_transition(
        "APPLIED", identity.applied_at, False, message, classify(message), match_application(message, [identity])
    )[0]
