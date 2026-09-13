"""Company-centric read model over applications, employer email and postings (ADR 0006).

Read-only. Nothing here re-classifies mail or changes an application; it assembles what the
owner already has so one company can be understood at a glance: what was applied for, what
the employer wrote back (grouped by Gmail thread) and what the scanners currently see.
"""

from __future__ import annotations

import re
from collections import defaultdict
from email.utils import parseaddr
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.applications.service import application_dict, effective_events
from app.db.models import (
    Application,
    EmailApplicationLink,
    EmailMessage,
    EmployerGroup,
    GmailConnection,
    Job,
    JobEvaluation,
    ReviewItem,
    RuleResult,
    SourceRegistry,
    WatchlistEntry,
)
from app.email.import_history import _company_key, _sender_company

# Words that show an email is about the owner's own candidacy rather than marketing.
_JOB_MAIL = re.compile(
    r"\b(applicat|applied|applying|candida|interview|assessment|recruit|position|role|resume|"
    r"offer|hiring|talent|opportunit|thank you for)",
    re.IGNORECASE,
)
_KIND_LABELS = {
    "CONFIRMATION": "Application confirmed",
    "REJECTION": "Rejected",
    "INTERVIEW": "Interview",
    "ASSESSMENT": "Assessment",
    "OFFER": "Offer",
    "POSITION_CLOSED": "Position closed",
    "INFORMATION_NEEDED": "Information requested",
    "STATUS_CHANGED": "Status update",
    "CONDITIONAL_OR_NEGATED": "Ambiguous wording",
    "UNKNOWN_TEMPLATE": "Employer email",
    "MALFORMED_OR_INCOMPLETE_CONTENT": "Employer email (partial content)",
    "FORWARDED": "Forwarded",
}


def _mentions(text: str, key: str) -> bool:
    return bool(key) and bool(re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", text))


def _domain_key(sender: str) -> str:
    _, address = parseaddr(sender or "")
    return address.split("@")[-1].lower()


def _names_company(mail: EmailMessage, key: str) -> bool:
    """Subject or sender names the company, allowing the squashed spelling domains and
    display names use ("kraftheinz.com", "KraftHeinz Careers") for a multi-word key."""
    if not key:
        return False
    haystack = _company_key(mail.subject) + " " + _company_key(_sender_company(mail.sender) or "")
    if _mentions(haystack, key):
        return True
    squashed = key.replace(" ", "")
    if len(squashed) < 5:
        return False  # Too short to trust a squashed match ("uber" inside "uberlandia").
    tokens = set(haystack.split()) | set(_domain_key(mail.sender).split("."))
    return squashed in tokens


def search_companies(session: Session, user_id: UUID, query: str, *, limit: int = 20) -> list[dict]:
    """Companies the owner has any trace of, ranked by how much evidence they carry."""
    needle = _company_key(query)
    if not needle:
        return []
    scores: dict[str, dict] = {}

    def bump(name: str, field: str, amount: int = 1):
        key = _company_key(name)
        if not key or needle not in key:
            return
        entry = scores.setdefault(key, {"name": name, "applications": 0, "emails": 0, "watched": False, "postings": 0})
        if field == "watched":
            entry["watched"] = True
        else:
            entry[field] += amount
        if len(name) < len(entry["name"]):
            entry["name"] = name  # Prefer the shortest spelling as the display name.

    for app in session.scalars(
        select(Application).where(Application.user_id == user_id, Application.voided_at.is_(None))
    ):
        bump(app.company, "applications")
    for entry, group in session.execute(
        select(WatchlistEntry, EmployerGroup)
        .outerjoin(EmployerGroup, EmployerGroup.id == WatchlistEntry.employer_group_id)
        .where(WatchlistEntry.user_id == user_id, WatchlistEntry.enabled.is_(True))
    ):
        bump(group.canonical_name if group else entry.requested_name, "watched")
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id))
    if connection:
        known = sorted(scores, key=len, reverse=True)  # Longest key first ("unc health" before "unc").
        for mail in session.scalars(select(EmailMessage).where(EmailMessage.connection_id == connection.id)):
            # Mail that names a company the owner already tracks counts for that company, whatever
            # the sender's spelling; otherwise the sender's own name becomes a candidate.
            owner_key = next((key for key in known if _names_company(mail, key)), None)
            if owner_key:
                scores[owner_key]["emails"] += 1
                continue
            sender_company = _sender_company(mail.sender)
            if sender_company:
                bump(sender_company, "emails")
            elif _names_company(mail, needle):
                bump(query.strip(), "emails")
    for group in session.scalars(select(EmployerGroup)):
        if needle in _company_key(group.canonical_name):
            open_count = len(
                session.scalars(
                    select(Job.id).where(
                        Job.employer_group_id == group.id,
                        Job.canonical_redirect_id.is_(None),
                        Job.availability != "CLOSED",
                    )
                ).all()
            )
            bump(group.canonical_name, "postings", open_count)
    ranked = sorted(
        scores.values(),
        key=lambda e: (-(e["applications"] * 3 + e["emails"] + (2 if e["watched"] else 0)), e["name"].lower()),
    )
    return ranked[:limit]


def company_view(session: Session, user_id: UUID, name: str) -> dict:
    key = _company_key(name)
    apps = [
        app
        for app in session.scalars(
            select(Application)
            .where(Application.user_id == user_id, Application.voided_at.is_(None))
            .order_by(Application.applied_at.desc(), Application.id)
        )
        if _mentions(_company_key(app.company), key)
    ]
    app_ids = {app.id for app in apps}
    display = min((app.company for app in apps), key=len, default=name.strip())

    applications = []
    for app in apps:
        events = effective_events(session, app.id)
        applications.append(
            {
                **application_dict(app),
                "events": [
                    {
                        "id": str(event.id),
                        "event_type": event.event_type,
                        "status": event.status,
                        "actor": event.actor,
                        "effective_at": event.effective_at.isoformat(),
                        "reason": (event.evidence or {}).get("status_evidence") or (event.evidence or {}).get("reason"),
                    }
                    for event in sorted(events, key=lambda e: (e.effective_at, e.recorded_at))
                ],
            }
        )

    # Every email linked to these applications, plus every email naming the company.
    connection = session.scalar(select(GmailConnection).where(GmailConnection.user_id == user_id))
    messages: dict[UUID, dict] = {}
    if connection:
        linked = (
            session.execute(
                select(EmailMessage, EmailApplicationLink)
                .join(EmailApplicationLink, EmailApplicationLink.email_id == EmailMessage.id)
                .where(EmailApplicationLink.application_id.in_(app_ids), EmailMessage.connection_id == connection.id)
            ).all()
            if app_ids
            else []
        )
        for mail, link in linked:
            entry = messages.setdefault(mail.id, _message(mail))
            entry["linked_application_id"] = str(link.application_id)
            entry["link_state"] = link.match_state
        for mail in session.scalars(select(EmailMessage).where(EmailMessage.connection_id == connection.id)):
            if mail.id in messages:
                continue
            if _names_company(mail, key):
                messages[mail.id] = _message(mail)
        if messages:
            open_reviews = {
                row.target_id: row
                for row in session.scalars(
                    select(ReviewItem).where(
                        ReviewItem.user_id == user_id,
                        ReviewItem.review_type == "EMAIL_APPLICATION",
                        ReviewItem.state == "OPEN",
                        ReviewItem.target_id.in_(list(messages)),
                    )
                )
            }
            for email_id, review in open_reviews.items():
                messages[email_id]["open_review_id"] = str(review.id)
                messages[email_id]["review_reason"] = review.reason

    threads: dict[str, list[dict]] = defaultdict(list)
    for entry in messages.values():
        threads[entry["thread_id"]].append(entry)
    thread_rows = []
    for thread_id, rows in threads.items():
        rows.sort(key=lambda r: r["received_at"])
        thread_rows.append(
            {
                "thread_id": thread_id,
                "subject": rows[0]["subject"],
                "first_at": rows[0]["received_at"],
                "last_at": rows[-1]["received_at"],
                "messages": rows,
                "latest_kind": rows[-1]["kind"],
            }
        )
    thread_rows.sort(key=lambda t: t["last_at"], reverse=True)

    watch = None
    group_ids: set[UUID] = set()
    for entry, group in session.execute(
        select(WatchlistEntry, EmployerGroup)
        .outerjoin(EmployerGroup, EmployerGroup.id == WatchlistEntry.employer_group_id)
        .where(WatchlistEntry.user_id == user_id, WatchlistEntry.enabled.is_(True))
    ):
        label = group.canonical_name if group else entry.requested_name
        if key and key == _company_key(label):
            watch = {"id": str(entry.id), "resolution_state": "REGISTERED" if group else "PENDING"}
            if group:
                group_ids.add(group.id)
    for group in session.scalars(select(EmployerGroup)):
        if key and key == _company_key(group.canonical_name):
            group_ids.add(group.id)
    postings = {"open": 0, "relevant": 0, "sources": 0, "employer_group_id": None}
    if group_ids:
        postings["employer_group_id"] = str(min(group_ids, key=str))
        postings["sources"] = len(
            session.scalars(
                select(SourceRegistry.id).where(
                    SourceRegistry.employer_group_id.in_(group_ids), SourceRegistry.enabled.is_(True)
                )
            ).all()
        )
        open_jobs = session.scalars(
            select(Job).where(
                Job.employer_group_id.in_(group_ids),
                Job.canonical_redirect_id.is_(None),
                Job.availability != "CLOSED",
            )
        ).all()
        postings["open"] = len(open_jobs)
        if open_jobs:
            latest = (
                select(JobEvaluation.id)
                .where(
                    JobEvaluation.job_id.in_([job.id for job in open_jobs]),
                    or_(JobEvaluation.user_id == user_id, JobEvaluation.user_id.is_(None)),
                )
                .distinct(JobEvaluation.job_id)
                .order_by(JobEvaluation.job_id, JobEvaluation.evaluated_at.desc(), JobEvaluation.id)
            )
            postings["relevant"] = len(
                session.scalars(
                    select(JobEvaluation.job_id)
                    .join(RuleResult, RuleResult.evaluation_id == JobEvaluation.id)
                    .where(
                        JobEvaluation.id.in_(latest),
                        RuleResult.rule_code == "role_relevance",
                        RuleResult.reason_code != "ROLE_UNRELATED",
                    )
                ).all()
            )

    kinds = defaultdict(int)
    for entry in messages.values():
        kinds[entry["kind"]] += 1
    latest_status = None
    if applications:
        latest_status = max(applications, key=lambda a: a["applied_at"])["display_status"]
    return {
        "name": display,
        "key": key,
        "summary": {
            "applications": len(applications),
            "latest_status": latest_status,
            "emails": len(messages),
            "threads": len(thread_rows),
            "email_kinds": dict(kinds),
            "open_reviews": sum(1 for m in messages.values() if m.get("open_review_id")),
            "watched": watch is not None,
        },
        "applications": applications,
        "threads": thread_rows,
        "watchlist": watch,
        "postings": postings,
    }


def _message(mail: EmailMessage) -> dict:
    evidence = mail.evidence or {}
    return {
        "id": str(mail.id),
        "thread_id": mail.thread_id,
        "sender": mail.sender,
        "subject": mail.subject,
        "excerpt": (mail.excerpt or "")[:600],
        "received_at": mail.received_at.isoformat(),
        "classification": mail.classification,
        "kind": _KIND_LABELS.get(mail.classification, "Employer email"),
        "proposed_status": evidence.get("proposed_status"),
        "match_state": evidence.get("match_state"),
        "job_related": bool(_JOB_MAIL.search((mail.subject or "") + " " + (mail.excerpt or "")[:300])),
    }
