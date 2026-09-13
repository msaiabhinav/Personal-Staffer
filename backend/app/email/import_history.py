"""One-time import of pre-existing applications from Gmail confirmation emails.

The normal path keeps a human in the loop: unmatched confirmations become review items.
The owner asked for a one-time bulk import of applications made before Personal Staffer
existed. This module proposes company/title/date from each open UNMATCHED_CONFIRMATION
review using the retained subject and sender only, shows the proposal, and — only when
explicitly applied — resolves each review through the same `resolve` path the UI uses
(CREATE_APPLICATION for the first email of a company+title, LINK for later ones). Nothing
is invented: when a title cannot be read the subject is kept as the title and the original
subject/sender are written into the application notes for correction in the app.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC
from email.utils import parseaddr
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select

from app.db.models import EmailMessage, ReviewItem, User

# Applicant-tracking mail domains never name the employer.
_ATS_DOMAINS = (
    "greenhouse",
    "icims",
    "myworkday",
    "workday",
    "adp.com",
    "paylocity",
    "successfactors",
    "governmentjobs",
    "lever.co",
    "ashbyhq",
    "smartrecruiters",
    "taleo",
    "oraclecloud",
    "jobvite",
    "bamboohr",
    "ultipro",
    "workable",
    "breezy",
    "applytojob",
    "recruitee",
    "hire.lever",
    "eightfold",
    "phenom",
    "avature",
    "brassring",
    "kenexa",
    "dayforce",
    "ceridian",
    "linkedin",
    "indeed",
    "ziprecruiter",
    "glassdoor",
    "no-reply",
    "noreply",
)

_STRIP_TITLE = re.compile(
    r"\s*[-–—:]?\s*(?:\(?(?:req|job|requisition|id|#)\s*[:#]?\s*[A-Z0-9-]+\)?)\s*$", re.IGNORECASE
)
_TRAILING_ID = re.compile(r"\s*[-–—]\s*\d{4,}\s*$")
_ROLE_WORDS = re.compile(
    r"\b(analyst|engineer|scientist|manager|specialist|consultant|developer|lead|director|associate|coordinator|"
    r"architect|administrator|intern|analytics|analysis|data|business|intelligence|reporting|operations)\b",
    re.IGNORECASE,
)


@dataclass
class Proposal:
    review_id: UUID
    review_revision: int
    email_id: UUID
    received_at: object
    sender: str
    subject: str
    company: str | None
    title: str | None
    confidence: str  # HIGH | MEDIUM | LOW
    action: str = "CREATE"  # CREATE | LINK
    link_to: str | None = None  # key of the proposal that creates the application
    notes: list[str] = field(default_factory=list)
    title_extracted: bool = False

    @property
    def key(self) -> str:
        # Without a readable title, repeated confirmations from one company are one application.
        return f"{_norm(self.company)}|{_norm(self.title) if self.title_extracted else ''}"


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" -–—:,.|")
    value = _TRAILING_ID.sub("", value)
    value = re.sub(r"\s*\(\s*[A-Z0-9-]{3,}\s*\)\s*$", "", value)  # trailing "(63123)" style ids
    value = _STRIP_TITLE.sub("", value)
    value = re.sub(
        r"\s*\((?:full[- ]time|part[- ]time|remote|hybrid|onsite)[^)]*\)\s*$", "", value, flags=re.IGNORECASE
    )
    return value.strip(" -–—:,.|") or None


def _sender_company(sender: str) -> str | None:
    name, address = parseaddr(sender or "")
    domain = address.split("@")[-1].lower()
    if name:
        cleaned = re.sub(
            r"\b(careers?|talent|recruiting|recruitment|hiring|team|hr|human resources|jobs|no[- ]?reply|"
            r"do[- ]not[- ]reply|notifications?|applicant tracking|ats|via|icims|workday|greenhouse|lever|ashby)\b",
            "",
            name,
            flags=re.IGNORECASE,
        )
        cleaned = _clean(cleaned.replace("+autoreply", ""))
        if cleaned and not any(a in cleaned.lower() for a in _ATS_DOMAINS) and len(cleaned) > 1:
            return cleaned
    if domain and not any(a in domain for a in _ATS_DOMAINS):
        label = domain.split(".")[-2] if "." in domain else domain
        return label.capitalize()
    return None


_SUBJECT_RULES = [
    # "Simplot Company: Application received – Commercial Reporting and Analytics Analyst - Boise"
    (
        re.compile(
            r"^(?P<company>[^:]{2,80}):\s*application received\s*[-–—:]\s*(?P<title>.+?)(?:\s+-\s+[^-]{2,40})?$",
            re.IGNORECASE,
        ),
        "HIGH",
    ),
    # "Your Application with Boston Scientific - Senior Sales Operations Analyst - Technology (63...)"
    (
        re.compile(r"^your application (?:with|to|at|for)\s+(?P<company>.+?)\s*[-–—]\s*(?P<title>.+)$", re.IGNORECASE),
        "HIGH",
    ),
    # "Your application for the position Business Intelligence & Project Analyst at M. G. Newell"
    (
        re.compile(
            r"^(?:your )?application for (?:the )?(?:position|role)(?: of)?\s+(?P<title>.+?)\s+at\s+(?P<company>.+)$",
            re.IGNORECASE,
        ),
        "HIGH",
    ),
    # "Business Performance Analyst Full time-26003447 at Texas Health Resources"
    (
        re.compile(
            r"^(?P<title>.+?)\s+(?:full[- ]time|part[- ]time|prn|per diem)[-\s]*[A-Z0-9-]*\s+at\s+(?P<company>.+)$",
            re.IGNORECASE,
        ),
        "HIGH",
    ),
    # "Thank you for applying to Spring Health" / "Your application to Workhelix"
    (
        re.compile(
            r"^(?:thank you for (?:applying|your application)|your application|application received)\s+(?:to|at|by|with|for)\s+(?P<company>.+)$",
            re.IGNORECASE,
        ),
        "MEDIUM",
    ),
    # "S&S Activewear LLC-Thank you for your application, Sai Abhinav"
    (re.compile(r"^(?P<company>.+?)\s*[-–—:]\s*thank you for (?:your application|applying)", re.IGNORECASE), "MEDIUM"),
    # "Application received by Massachusetts Bay Transportation Authority"
    (
        re.compile(
            r"^application (?:received|complete|submitted)\s+(?:by|at|to|with)\s+(?P<company>.+)$", re.IGNORECASE
        ),
        "MEDIUM",
    ),
    # "<Title> at <Company>" / "<Title> - <Company>" when the title looks like a role
    (re.compile(r"^(?P<title>.+?)\s+at\s+(?P<company>.+)$", re.IGNORECASE), "MEDIUM"),
]


def propose(session, user_id: UUID) -> list[Proposal]:
    rows = session.execute(
        select(ReviewItem, EmailMessage)
        .join(EmailMessage, EmailMessage.id == ReviewItem.target_id)
        .where(
            ReviewItem.user_id == user_id,
            ReviewItem.review_type == "EMAIL_APPLICATION",
            ReviewItem.reason == "UNMATCHED_CONFIRMATION",
            ReviewItem.state == "OPEN",
        )
        .order_by(EmailMessage.received_at)
    ).all()
    proposals: list[Proposal] = []
    for review, mail in rows:
        subject = re.sub(r"\s+", " ", mail.subject or "").strip()
        company = title = None
        confidence = "LOW"
        for pattern, level in _SUBJECT_RULES:
            m = pattern.match(subject)
            if not m:
                continue
            groups = m.groupdict()
            candidate_title = _clean(groups.get("title"))
            candidate_company = _clean(groups.get("company"))
            # The generic "<x> at <y>" rule only counts when <x> reads like a role.
            if level == "MEDIUM" and candidate_title and not _ROLE_WORDS.search(candidate_title):
                continue
            company, title, confidence = candidate_company, candidate_title, level
            break
        notes = []
        if not company:
            company = _sender_company(mail.sender)
            if company:
                notes.append("company inferred from sender")
                confidence = "LOW"
        if title and not _ROLE_WORDS.search(title):
            confidence = "LOW"
        if not title:
            notes.append("title not found in subject; subject kept as title")
            confidence = "LOW"
        proposals.append(
            Proposal(
                review_id=review.id,
                review_revision=review.revision,
                email_id=mail.id,
                received_at=mail.received_at,
                sender=mail.sender or "",
                subject=subject,
                company=company,
                title=title or subject or "Application (see email)",
                confidence=confidence,
                notes=notes,
                title_extracted=bool(title),
            )
        )
    # Collapse repeated confirmations for the same company+title into one application.
    first_by_key: dict[str, Proposal] = {}
    for proposal in proposals:
        if not proposal.company:
            continue
        key = proposal.key
        if key in first_by_key:
            proposal.action = "LINK"
            proposal.link_to = str(first_by_key[key].review_id)
        else:
            first_by_key[key] = proposal
    return proposals


def apply(session, user_id: UUID, proposals: list[Proposal], *, include_low: bool) -> dict:
    from app.api.schemas import ManualApplicationInput
    from app.email.router import ResolveReview, resolve

    user = session.get(User, user_id)
    if user is None:
        raise ValueError("Unknown user")
    created: dict[str, str] = {}  # review_id -> application_id
    counts = {"created": 0, "linked": 0, "skipped_low": 0, "skipped_no_company": 0}
    for proposal in proposals:
        if not proposal.company:
            counts["skipped_no_company"] += 1
            continue
        if proposal.confidence == "LOW" and not include_low:
            counts["skipped_low"] += 1
            continue
        reason = "One-time Gmail history import of applications made before Personal Staffer"
        operation_id = f"gmail-import:{proposal.review_id}"
        if proposal.action == "LINK" and proposal.link_to in created:
            payload = ResolveReview(
                action="LINK",
                expected_revision=proposal.review_revision,
                application_id=UUID(created[proposal.link_to]),
                application_revision=None,
                reason=reason,
            )
            # LINK requires the current application revision; read it.
            from app.db.models import Application

            app = session.get(Application, UUID(created[proposal.link_to]))
            payload.application_revision = app.revision
            resolve(session, SimpleNamespace(id=user.id), proposal.review_id, payload, operation_id)
            counts["linked"] += 1
            continue
        notes = "\n".join(
            [
                "Imported from Gmail (one-time history import).",
                f"Email subject: {proposal.subject}",
                f"Sender: {proposal.sender}",
                f"Extraction confidence: {proposal.confidence}"
                + (f" ({'; '.join(proposal.notes)})" if proposal.notes else ""),
            ]
        )
        payload = ResolveReview(
            action="CREATE_APPLICATION",
            expected_revision=proposal.review_revision,
            reason=reason,
            application=ManualApplicationInput(
                title=proposal.title[:1000],
                company=proposal.company[:1000],
                applied_at=proposal.received_at.astimezone(UTC),
                notes=notes,
            ),
        )
        result = resolve(session, SimpleNamespace(id=user.id), proposal.review_id, payload, operation_id)
        created[str(proposal.review_id)] = result["resolution"]["application_id"]
        counts["created"] += 1
    return counts
