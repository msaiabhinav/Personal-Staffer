from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import and_, or_, select

from app.applications.service import add_status_event, change, lock_user
from app.auth.crypto import SecretBox
from app.auth.provider import GMAIL_SCOPE, GoogleProvider
from app.db.models import (
    Application,
    EmailApplicationLink,
    EmailMessage,
    GmailConnection,
    GmailSyncState,
    Job,
    ReviewItem,
    utcnow,
)
from app.email.gmail import GmailAPI, GmailUnavailable, HistoryExpired
from app.email.parser import ApplicationIdentity, automatic_transition, classify, decode_message, match_application
from app.notifications.service import create_notification


def process_message(session, connection, payload):
    """Caller holds user lock. Identity, meaning and sender trust are separate gates.

    Header evidence comes from the authenticated Gmail API response. It is a
    conservative screening control, not an absolute guarantee against spoofing,
    account compromise, imported messages or an incorrect human association.
    """
    from app.applications.service import effective_events
    from app.db.models import EmployerBrand
    from app.email.parser import sender_trust

    existing = session.scalar(
        select(EmailMessage).where(
            EmailMessage.connection_id == connection.id, EmailMessage.gmail_message_id == payload["id"]
        )
    )
    if existing:
        return "DUPLICATE"
    mail = decode_message(payload)
    meaning = classify(mail)
    if meaning.kind == "UNRELATED":
        return "UNRELATED"
    apps = list(
        session.scalars(
            select(Application).where(Application.user_id == connection.user_id, Application.voided_at.is_(None))
        )
    )
    identities = []
    for application in apps:
        linked_threads = session.scalars(
            select(EmailMessage.thread_id)
            .join(EmailApplicationLink, EmailApplicationLink.email_id == EmailMessage.id)
            .where(
                EmailApplicationLink.application_id == application.id,
                or_(
                    and_(
                        EmailApplicationLink.match_state == "USER_CONFIRMED",
                        EmailApplicationLink.reviewed_at.is_not(None),
                    ),
                    and_(EmailApplicationLink.match_state == "MATCHED", EmailApplicationLink.event_id.is_not(None)),
                ),
                EmailApplicationLink.corrected_at.is_(None),
                EmailMessage.connection_id == connection.id,
            )
        )
        job = session.get(Job, application.job_id) if application.job_id else None
        identities.append(
            ApplicationIdentity(
                str(application.id),
                application.company,
                application.title,
                application.applied_at,
                requisition_id=job.requisition_id if job else None,
                thread_ids=frozenset(linked_threads),
            )
        )
    match = match_application(mail, identities)
    application = next((item for item in apps if str(item.id) == match.application_id), None)
    official_domains, reviewed_senders, reviewed_references = [], [], []
    if application:
        if application.job_id:
            job = session.get(Job, application.job_id)
            if job:
                official_domains = list(
                    session.scalars(
                        select(EmployerBrand.canonical_domain).where(
                            EmployerBrand.group_id == job.employer_group_id, EmployerBrand.canonical_domain.is_not(None)
                        )
                    )
                )
        reviewed = session.execute(
            select(EmailMessage, EmailApplicationLink)
            .join(EmailApplicationLink, EmailApplicationLink.email_id == EmailMessage.id)
            .where(
                EmailApplicationLink.application_id == application.id,
                EmailApplicationLink.match_state == "USER_CONFIRMED",
                EmailApplicationLink.reviewed_at.is_not(None),
                EmailApplicationLink.corrected_at.is_(None),
                EmailMessage.connection_id == connection.id,
            )
        ).all()
        for reviewed_mail, reviewed_link in reviewed:
            address = (reviewed_mail.evidence or {}).get("sender_security", {}).get("from_address")
            if address:
                reviewed_senders.append(address)
                if address == mail.authentication.get("from_address"):
                    reviewed_references.append(
                        {
                            "email_id": str(reviewed_mail.id),
                            "link_id": str(reviewed_link.id),
                            "reviewed_at": reviewed_link.reviewed_at.isoformat(),
                        }
                    )
    security = sender_trust(
        mail,
        official_domains=official_domains,
        reviewed_senders=reviewed_senders,
        mailbox_identity=connection.google_identity,
    )
    security["reviewed_sender_references"] = reviewed_references
    row = EmailMessage(
        id=uuid4(),
        connection_id=connection.id,
        gmail_message_id=mail.message_id,
        thread_id=mail.thread_id,
        sender=mail.sender,
        subject=mail.subject,
        excerpt=mail.body[:1000],
        received_at=mail.received_at,
        classification=meaning.kind,
        evidence={
            "template_version": meaning.parser_version,
            "template_evidence": meaning.evidence,
            "proposed_status": meaning.status,
            "match_state": match.state,
            "match_reasons": list(match.reasons),
            "sender_security": security,
            "received_time_verified": "RECEIVED_TIME_UNAVAILABLE" not in mail.content_issues,
        },
    )
    session.add(row)
    session.flush()
    links = {}
    for candidate in match.candidates:
        link = EmailApplicationLink(
            email_id=row.id,
            application_id=UUID(candidate),
            match_state=match.state,
            evidence={"reasons": list(match.reasons), "sender_security_reason": security["reason"]},
        )
        session.add(link)
        links[candidate] = link
    if application:
        latest = max(
            effective_events(session, application.id),
            key=lambda event: (event.effective_at, event.recorded_at),
            default=None,
        )
        allowed, reason = automatic_transition(
            application.current_status,
            latest.effective_at if latest else application.applied_at,
            False,
            mail,
            meaning,
            match,
            sender_trusted=security["trusted"],
        )
        if allowed or (security["trusted"] and reason in {"OLDER_THAN_CURRENT_EVENT", "CONFIRMATION_DOES_NOT_REGRESS"}):
            result = add_status_event(
                session,
                connection.user_id,
                application.id,
                SimpleNamespace(
                    expected_revision=application.revision,
                    status=meaning.status,
                    reason=meaning.evidence if allowed else reason,
                    effective_at=mail.received_at,
                ),
                f"gmail:{connection.id}:{mail.message_id}",
                actor="EMAIL",
                source_reference=f"gmail:{connection.id}:{mail.message_id}",
                evidence={
                    "email_id": str(row.id),
                    "template_version": meaning.parser_version,
                    "match_reasons": list(match.reasons),
                    "status_evidence": meaning.evidence,
                    "sender_security": security,
                },
            )
            links[match.application_id].event_id = UUID(result["event_id"])
            if not allowed:
                # A status change already notifies through add_status_event; evidence-only
                # mail still deserves an alert because the owner asked to hear about every
                # employer email, and it opens the application it was filed under.
                create_notification(
                    session,
                    connection.user_id,
                    "APPLICATION_EMAIL",
                    "applications",
                    application.id,
                    f"{application.company}: new email"[:250],
                    (mail.subject or "")[:160],
                    f"email:{row.id}",
                )
            return "APPLIED" if allowed else "EVIDENCE_ONLY"
        if not security["trusted"]:
            reason = security["reason"]
    else:
        reason = (
            "UNMATCHED_CONFIRMATION" if meaning.kind == "CONFIRMATION" and match.state == "UNMATCHED" else match.state
        )
    review = ReviewItem(
        id=uuid4(),
        user_id=connection.user_id,
        review_type="EMAIL_APPLICATION",
        target_id=row.id,
        reason=reason,
        evidence={
            "email_id": str(row.id),
            "subject": row.subject,
            "excerpt": row.excerpt,
            "proposed_status": meaning.status,
            "candidate_application_ids": list(match.candidates),
            "template_evidence": meaning.evidence,
            "template_version": meaning.parser_version,
            "sender_security": security,
            "received_time_verified": "RECEIVED_TIME_UNAVAILABLE" not in mail.content_issues,
        },
    )
    session.add(review)
    session.flush()
    change(session, connection.user_id, "reviews", review.id, 1)
    create_notification(
        session,
        connection.user_id,
        "EMAIL_REVIEW",
        "reviews",
        review.id,
        _email_title(mail.sender, row.subject),
        f"{row.subject[:160]} · needs your review",
        f"email-review:{row.id}",
    )
    return "REVIEW"


def _email_title(sender: str | None, subject: str | None) -> str:
    """Toast/list title that names who wrote, so the owner can triage without opening."""
    name = (sender or "").split("<", 1)[0].strip(" \"'") or (sender or "").strip()
    name = name or "Employer"
    return f"Email from {name}"[:250]


def synchronize(session, user_id, settings, api=None, provider=None, frozen_now=None):
    """Process at most one API page per transaction, persisting continuation.

    A baseline history ID is captured BEFORE initial reconciliation. Catch-up
    history after the bounded backfill recovers messages arriving during it.
    """
    lock_user(session, user_id)
    page_time = frozen_now or utcnow()
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id).with_for_update())
    if not connection or not connection.refresh_token_encrypted or connection.revoked_at:
        return {"state": "NOT_CONFIGURED" if not connection else "RECONNECT_REQUIRED", "processed": 0}
    if GMAIL_SCOPE not in connection.granted_scopes:
        connection.sync_health = "RECONNECT_REQUIRED"
        return {"state": connection.sync_health, "processed": 0}
    state = session.scalar(
        select(GmailSyncState).where(GmailSyncState.connection_id == connection.id).with_for_update()
    )
    if not state:
        state = GmailSyncState(connection_id=connection.id, reconciliation_progress={})
        session.add(state)
        session.flush()
    if api is None:
        box = SecretBox(settings.token_encryption_key)
        try:
            token = (provider or GoogleProvider(settings)).refresh(connection.refresh_token_encrypted, box)
        except Exception as exc:
            raise GmailUnavailable("RECONNECT_REQUIRED", "Gmail access could not be refreshed") from exc
        if token.get("refresh_token"):
            connection.refresh_token_encrypted = box.encrypt(token["refresh_token"])
        api = GmailAPI(token["access_token"])
    progress = dict(state.reconciliation_progress or {})
    if not state.history_cursor and progress.get("mode") != "BACKFILL":
        profile = api.profile()
        progress = {
            "mode": "BACKFILL",
            "baseline": str(profile["historyId"]),
            "after": (page_time - timedelta(days=settings.gmail_backfill_days)).isoformat(),
            "page_token": None,
            "processed": 0,
        }
    if progress.get("mode") == "BACKFILL":
        batch = api.backfill(
            datetime.fromisoformat(progress["after"]), progress.get("page_token"), connection.selected_label
        )
    else:
        try:
            batch = api.history(state.history_cursor, progress.get("page_token"), connection.selected_label)
        except HistoryExpired:
            profile = api.profile()
            progress = {
                "mode": "BACKFILL",
                "baseline": str(profile["historyId"]),
                "after": (page_time - timedelta(days=settings.gmail_backfill_days)).isoformat(),
                "page_token": None,
                "processed": 0,
            }
            batch = api.backfill(datetime.fromisoformat(progress["after"]), None, connection.selected_label)
    counts = {}
    for identifier in batch.message_ids:
        outcome = process_message(session, connection, api.message(identifier))
        counts[outcome] = counts.get(outcome, 0) + 1
    if batch.next_page_token:
        progress["page_token"] = batch.next_page_token
        progress["processed"] = progress.get("processed", 0) + len(batch.message_ids)
        progress.setdefault("mode", "HISTORY")
        state.reconciliation_progress = progress
        connection.sync_health = "SYNCING"
    else:
        # Set the cursor only after every relevant fetched message/event is
        # successfully staged. Request transaction atomically commits both.
        state.history_cursor = (
            progress["baseline"] if progress.get("mode") == "BACKFILL" else batch.history_cursor or state.history_cursor
        )
        state.reconciliation_progress = {}
        state.last_success = utcnow()
        connection.sync_health = "HEALTHY"
    session.flush()
    return {
        "state": connection.sync_health,
        "processed": len(batch.message_ids),
        "counts": counts,
        "has_more": bool(batch.next_page_token),
        "history_cursor": state.history_cursor,
    }
