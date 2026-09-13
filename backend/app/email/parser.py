"""Conservative, versioned email meaning and application identity extraction.

No sender-only matches, numeric confidence or model generated status claims.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any, ClassVar

PARSER_VERSION = "email-templates-2"
MAX_MIME_PARTS = 128
MAX_MIME_DEPTH = 16
MAX_ENCODED_PART_BYTES = 300_000
MAX_DECODED_BYTES = 200_000
MAX_BODY_CHARS = 100_000
UNSAFE_LABELS = frozenset({"SPAM", "TRASH", "DRAFT", "SENT"})


class _Text(HTMLParser):
    """Exclude quotation containers and hidden content before interpreting text."""

    _void: ClassVar[set[str]] = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    _quote_markers: ClassVar[set[str]] = {
        "gmail_quote",
        "gmail_quote_container",
        "yahoo_quoted",
        "protonmail_quote",
        "moz-cite-prefix",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.stack = []
        self.issues = set()
        self.quoted_removed = False
        self.cut_remainder = False

    def handle_starttag(self, tag, attrs):
        attributes = {str(key).casefold(): str(value or "").casefold() for key, value in attrs}
        markers = set(attributes.get("class", "").split()) | {attributes.get("id", "")}
        quote = tag == "blockquote" or attributes.get("type") == "cite" or bool(markers & self._quote_markers)
        if attributes.get("id") == "divrplyfwdmsg":
            self.cut_remainder = True  # Outlook marks the start of its appended older message.
            quote = True
        self.quoted_removed = self.quoted_removed or quote
        style = attributes.get("style", "").replace(" ", "")
        blocked = (
            self.cut_remainder
            or (self.stack and self.stack[-1][1])
            or quote
            or tag in {"script", "style", "template", "noscript"}
            or "hidden" in attributes
            or "display:none" in style
            or "visibility:hidden" in style
        )
        if len(self.stack) >= 64:
            self.issues.add("HTML_DEPTH_LIMIT")
            self.cut_remainder = True
            blocked = True
        if not blocked and tag in {"p", "div", "br", "li", "tr"}:
            self.parts.append("\n")
        if tag not in self._void:
            self.stack.append((tag, bool(blocked)))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self._void:
            return
        positions = [index for index, item in enumerate(self.stack) if item[0] == tag]
        if not positions:
            self.issues.add("MALFORMED_HTML")
            return
        position = positions[-1]
        if position != len(self.stack) - 1:
            self.issues.add("MALFORMED_HTML")
        del self.stack[position:]

    def handle_data(self, data):
        if not self.cut_remainder and not (self.stack and self.stack[-1][1]):
            self.parts.append(data)


def plain_html(value: str) -> str:
    parser = _Text()
    parser.feed(value)
    parser.close()
    return unescape("".join(parser.parts))


def current_content(body: str) -> str:
    """Strip quoted chains; forwarding is separately marked review-only."""
    lines = []
    for line in body.splitlines():
        if re.match(
            r"^\s*(On .+wrote:|[- ]*Original Message[- ]*|[- ]*Forwarded message[- ]*|From:\s)", line, re.IGNORECASE
        ):
            break
        if not line.lstrip().startswith(">"):
            lines.append(line)
    return "\n".join(lines).strip()


def _address(value: str) -> tuple[str, str]:
    from email import policy
    from email.parser import HeaderParser

    if re.search(r"[\r\n](?![ \t])", value):
        return "", ""
    try:
        parsed = HeaderParser(policy=policy.default).parsestr("From: " + value + "\n\n")["From"]
        if parsed.defects or len(parsed.addresses) != 1:
            return "", ""
        address = parsed.addresses[0]
        domain = address.domain.encode("idna").decode("ascii").lower()
        if not address.username or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or ".." in domain:
            return "", ""
        return address.username + "@" + domain, domain
    except (ValueError, TypeError, AttributeError, UnicodeError, IndexError):
        return "", ""


def sender_authentication(headers: dict[str, list[str]]) -> dict:
    from_headers = headers.get("from", [])
    auth_headers = headers.get("authentication-results", [])
    evidence = {
        "policy_version": "gmail-sender-trust-1",
        "source": "GMAIL_API_PAYLOAD_HEADERS",
        "from_header_count": len(from_headers),
        "authentication_results_count": len(auth_headers),
        "authenticated": False,
        "from_address": "",
        "from_domain": "",
        "limitation": "Header-based conservative screening is not proof against account compromise or imported mail.",
    }
    if len(from_headers) != 1:
        return {**evidence, "reason": "AMBIGUOUS_FROM_HEADER"}
    address, domain = _address(from_headers[0])
    evidence.update(from_address=address, from_domain=domain)
    if not address:
        return {**evidence, "reason": "INVALID_FROM_HEADER"}
    if len(auth_headers) != 1:
        return {**evidence, "reason": "MISSING_OR_AMBIGUOUS_AUTHENTICATION_RESULTS"}
    raw = re.sub(r"\r?\n[ \t]+", " ", auth_headers[0])
    evidence["authentication_results"] = raw[:4000]
    if len(raw) > 16000 or "\r" in raw or "\n" in raw:
        return {**evidence, "reason": "MALFORMED_AUTHENTICATION_RESULTS"}
    pieces = raw.split(";")
    if pieces[0].strip().lower() != "mx.google.com":
        return {**evidence, "reason": "UNTRUSTED_AUTHENTICATION_SERVICE"}
    dmarc = [part for part in pieces[1:] if re.search(r"\bdmarc\s*=", part, re.IGNORECASE)]
    if len(dmarc) != 1:
        return {**evidence, "reason": "MISSING_OR_AMBIGUOUS_DMARC_RESULT"}
    result = re.fullmatch(r"\s*dmarc\s*=\s*([a-z]+)\b(.*)", dmarc[0], re.IGNORECASE | re.DOTALL)
    if not result or result[1].lower() != "pass":
        return {**evidence, "reason": "DMARC_NOT_PASS"}
    aligned = re.findall(r'\bheader\.from\s*=\s*(?:"([^"\s]+)"|([^\s;()]+))', result[2], re.IGNORECASE)
    if len(aligned) != 1:
        return {**evidence, "reason": "AMBIGUOUS_DMARC_FROM"}
    authenticated_domain = (aligned[0][0] or aligned[0][1]).lower()
    evidence["dmarc_header_from"] = authenticated_domain
    if authenticated_domain != domain:
        return {**evidence, "reason": "DMARC_FROM_NOT_ALIGNED"}
    return {**evidence, "authenticated": True, "reason": "GOOGLE_DMARC_PASS_ALIGNED", "authserv_id": "mx.google.com"}


@dataclass(frozen=True)
class MailEvidence:
    message_id: str
    thread_id: str
    sender: str
    subject: str
    body: str
    received_at: datetime
    forwarded: bool = False
    labels: tuple[str, ...] = ()
    content_issues: tuple[str, ...] = ()
    content_omissions: tuple[str, ...] = ()
    authentication: dict = field(default_factory=dict)


def decode_message(payload: dict[str, Any]) -> MailEvidence:
    root = payload.get("payload", {})
    if not isinstance(root, dict):
        root = {}
    headers: dict[str, list[str]] = {}
    issues, omissions = set(), set()
    root_headers = root.get("headers", [])
    if not isinstance(root_headers, list):
        issues.add("MALFORMED_HEADERS")
        root_headers = []
    for header in root_headers[:256]:
        if isinstance(header, dict) and isinstance(header.get("name"), str) and isinstance(header.get("value"), str):
            headers.setdefault(header["name"].casefold(), []).append(header["value"])
        else:
            issues.add("MALFORMED_HEADER")
    if len(root_headers) > 256:
        issues.add("HEADER_COUNT_LIMIT")
    if len(headers.get("subject", [])) > 1:
        issues.add("AMBIGUOUS_SUBJECT_HEADER")
    texts, htmls = [], []
    seen_parts, total_bytes = 0, 0

    def visit(part, depth=0):
        nonlocal seen_parts, total_bytes
        seen_parts += 1
        if depth > MAX_MIME_DEPTH or seen_parts > MAX_MIME_PARTS:
            issues.add("MIME_STRUCTURE_LIMIT")
            return
        if not isinstance(part, dict):
            issues.add("MALFORMED_MIME_PART")
            return
        mime = str(part.get("mimeType", "")).casefold().split(";", 1)[0]
        part_headers = part.get("headers", [])
        if not isinstance(part_headers, list):
            issues.add("MALFORMED_HEADERS")
            part_headers = []
        disposition = next(
            (
                str(h.get("value", "")).casefold()
                for h in part_headers
                if isinstance(h, dict) and str(h.get("name", "")).casefold() == "content-disposition"
            ),
            "",
        )
        if mime == "message/rfc822" or part.get("filename") or disposition.startswith("attachment"):
            omissions.add("ATTACHMENT_IGNORED")
            return
        content = part.get("body", {})
        if not isinstance(content, dict):
            issues.add("MALFORMED_MIME_BODY")
            return
        data = content.get("data")
        if mime in {"text/plain", "text/html"} and content.get("attachmentId"):
            issues.add("TEXT_ATTACHMENT_NOT_FETCHED")
        if data is not None and mime in {"text/plain", "text/html"}:
            if not isinstance(data, str) or len(data) > MAX_ENCODED_PART_BYTES:
                issues.add("MIME_CONTENT_LIMIT")
                return
            try:
                decoded_bytes = base64.b64decode(data + "=" * (-len(data) % 4), altchars=b"-_", validate=True)
            except (ValueError, TypeError):
                issues.add("MALFORMED_BASE64")
                return
            total_bytes += len(decoded_bytes)
            if total_bytes > MAX_DECODED_BYTES:
                issues.add("MIME_CONTENT_LIMIT")
                return
            try:
                decoded = decoded_bytes.decode("utf-8")
            except UnicodeDecodeError:
                issues.add("INVALID_OR_UNSUPPORTED_TEXT_ENCODING")
                decoded = decoded_bytes.decode("utf-8", errors="replace")
            if mime == "text/plain":
                texts.append(decoded)
            else:
                parser = _Text()
                parser.feed(decoded)
                parser.close()
                issues.update(parser.issues)
                if parser.quoted_removed:
                    omissions.add("HTML_QUOTED_CONTENT_REMOVED")
                htmls.append("".join(parser.parts))
        children = part.get("parts", [])
        if not isinstance(children, list):
            issues.add("MALFORMED_MIME_PARTS")
            return
        if children and not mime.startswith("multipart/"):
            issues.add("UNEXPECTED_NESTED_MIME_PART")
            return
        for child in children:
            if seen_parts >= MAX_MIME_PARTS:
                issues.add("MIME_STRUCTURE_LIMIT")
                break
            visit(child, depth + 1)

    visit(root)
    body = "\n".join(texts or htmls)
    if len(body) > MAX_BODY_CHARS:
        issues.add("BODY_LENGTH_LIMIT")
        body = body[:MAX_BODY_CHARS]
    subject = (headers.get("subject") or [""])[0][:1000]
    forwarded = bool(
        re.match(r"\s*(fw|fwd):", subject, re.IGNORECASE) or re.search(r"forwarded message", body, re.IGNORECASE)
    )
    try:
        received = datetime.fromtimestamp(int(payload["internalDate"]) / 1000, UTC)
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        received = datetime(1970, 1, 1, tzinfo=UTC)
        issues.add("RECEIVED_TIME_UNAVAILABLE")
    labels = payload.get("labelIds", [])
    if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
        issues.add("MALFORMED_LABELS")
        labels = []
    return MailEvidence(
        str(payload["id"]),
        str(payload.get("threadId", "")),
        (headers.get("from") or [""])[0][:1000],
        subject,
        current_content(body),
        received,
        forwarded,
        tuple(labels),
        tuple(sorted(issues)),
        tuple(sorted(omissions)),
        sender_authentication(headers),
    )


def sender_trust(message: MailEvidence, *, official_domains=(), reviewed_senders=(), mailbox_identity="") -> dict:
    evidence = {
        **message.authentication,
        "labels": list(message.labels),
        "content_issues": list(message.content_issues),
        "content_omissions": list(message.content_omissions),
        "trusted": False,
        "affiliation": None,
    }
    address = message.authentication.get("from_address", "")
    domain = message.authentication.get("from_domain", "")
    if UNSAFE_LABELS.intersection(message.labels):
        return {**evidence, "reason": "EXCLUDED_GMAIL_LABEL"}
    if address and address.casefold() == mailbox_identity.casefold():
        return {**evidence, "reason": "SELF_SENT_MESSAGE"}
    if message.content_issues or message.forwarded:
        return {**evidence, "reason": "MESSAGE_CONTENT_REQUIRES_REVIEW"}
    if not message.authentication.get("authenticated"):
        return {**evidence, "reason": message.authentication.get("reason", "SENDER_AUTHENTICATION_UNKNOWN")}
    normalized_domains = {str(value).strip().casefold().removeprefix("www.") for value in official_domains if value}
    if domain in normalized_domains:
        return {**evidence, "trusted": True, "reason": "AUTHENTICATED_OFFICIAL_EMPLOYER_DOMAIN", "affiliation": domain}
    if address in set(reviewed_senders):
        return {
            **evidence,
            "trusted": True,
            "reason": "AUTHENTICATED_PREVIOUSLY_REVIEWED_EXACT_SENDER",
            "affiliation": address,
        }
    return {**evidence, "reason": "SENDER_EMPLOYER_ASSOCIATION_UNREVIEWED"}


@dataclass(frozen=True)
class Meaning:
    kind: str
    status: str | None
    evidence: str
    review: bool
    parser_version: str = PARSER_VERSION


_TEMPLATES = [
    (
        "REJECTION",
        "REJECTED",
        r"(?:we (?:have )?(?:decided|will|are unable) (?:not to (?:move|proceed)|to (?:move forward with other|pursue other)|to offer)|we (?:will not|won't) be (?:moving|proceeding)|your application (?:was|has been) (?:unsuccessful|rejected)|you (?:were|have) not (?:been )?selected|unfortunately[^\n.]{0,100}(?:not (?:be )?(?:moving forward|selected)|other candidates))",
    ),
    (
        "OFFER",
        "OFFER",
        r"(?:we are (?:pleased|delighted|excited) to offer you|offer of employment|attached (?:is )?your (?:employment |job )?offer)",
    ),
    (
        "INTERVIEW",
        "INTERVIEWING",
        r"(?:invite you to (?:an? |the |a final )?interview|you are invited to (?:an? |the )?interview|schedule (?:an? |your |the )interview|interview (?:invitation|has been scheduled)|selected (?:you )?for (?:an? |the )interview)",
    ),
    (
        "ASSESSMENT",
        "ASSESSMENT",
        r"(?:please complete (?:the |an? |our )?(?:online |technical )?assessment|invited to (?:take|complete) (?:an? |the )assessment)",
    ),
    (
        "CONFIRMATION",
        "APPLIED",
        r"(?:thank you for (?:applying|your application)|we (?:have )?received your application|application (?:has been |was )?received)",
    ),
    (
        "POSITION_CLOSED",
        None,
        r"(?:position (?:has been |is now |was )?(?:closed|filled)|no longer (?:accepting applications|available))",
    ),
    ("INFORMATION_NEEDED", None, r"(?:additional information|more information|additional documents)"),
    ("STATUS_CHANGED", None, r"(?:your (?:application )?status has (?:been )?(?:changed|updated)|application update)"),
]


def classify_text(text: str) -> str | None:
    """Status implied by subject/excerpt text alone (no MIME context); None when unclear."""
    matches = [(kind, status) for kind, status, pattern in _TEMPLATES if re.search(pattern, text, re.IGNORECASE)]
    stages = {status for kind, status in matches if status and kind != "CONFIRMATION"}
    return next(iter(stages)) if len(stages) == 1 else None


def classify(message: MailEvidence) -> Meaning:
    text = message.subject + "\n" + message.body
    if message.content_issues:
        return Meaning("MALFORMED_OR_INCOMPLETE_CONTENT", None, "; ".join(message.content_issues), True)
    if message.forwarded:
        return Meaning("FORWARDED", None, message.subject, True)
    matches = [
        (kind, status, m.group(0))
        for kind, status, pattern in _TEMPLATES
        if (m := re.search(pattern, text, re.IGNORECASE))
    ]
    # Confirmation boilerplate in later employer messages is not a new stage.
    status_matches = [m for m in matches if m[1] is not None]
    meaningful = [m for m in status_matches if m[0] != "CONFIRMATION"] or status_matches or matches
    stages = {status for _, status, _ in meaningful if status}
    if len(stages) > 1:
        return Meaning("CONTRADICTORY", None, "; ".join(m[2] for m in meaningful), True)
    if meaningful:
        kind, status, evidence = meaningful[0]
        # Conditionals and negations must not activate keyword templates.
        if re.search(r"\b(?:if|not|never)\b.{0,40}" + re.escape(evidence), text, re.IGNORECASE):
            return Meaning("CONDITIONAL_OR_NEGATED", None, evidence, True)
        return Meaning(kind, status, evidence, status is None)
    related = bool(
        re.search(r"\b(application|interview|recruiter|assessment|hiring|requisition)\b", text, re.IGNORECASE)
    )
    return Meaning("UNKNOWN_TEMPLATE" if related else "UNRELATED", None, message.subject, related)


@dataclass(frozen=True)
class ApplicationIdentity:
    id: str
    company: str
    title: str
    applied_at: datetime
    requisition_id: str | None = None
    thread_ids: frozenset[str] = field(default_factory=frozenset)
    location: str | None = None


@dataclass(frozen=True)
class Match:
    state: str
    application_id: str | None
    candidates: tuple[str, ...]
    reasons: tuple[str, ...]


def _contains(phrase: str | None, text: str) -> bool:
    return bool(phrase and re.search(r"(?<!\w)" + re.escape(phrase.casefold()) + r"(?!\w)", text))


def match_application(message: MailEvidence, applications: list[ApplicationIdentity]) -> Match:
    text = (message.subject + "\n" + message.body).casefold()
    matches: dict[str, str] = {}
    for app in applications:
        company = _contains(app.company, text)
        if message.thread_id and message.thread_id in app.thread_ids:
            matches[app.id] = "KNOWN_APPLICATION_THREAD"
        elif company and _contains(app.requisition_id, text):
            matches[app.id] = "EMPLOYER_AND_VERIFIED_REQUISITION"
        elif company and _contains(app.title, text):
            # Company+specific title plus temporal consistency; all candidates
            # are retained so repeated applications cannot be guessed apart.
            age = (message.received_at - app.applied_at).total_seconds()
            if -300 <= age <= 366 * 86400:
                matches[app.id] = "COMPANY_TITLE_AND_APPLICATION_DATE"
    if len(matches) == 1:
        identifier, reason = next(iter(matches.items()))
        return Match("MATCHED", identifier, (identifier,), (reason,))
    return Match("AMBIGUOUS" if matches else "UNMATCHED", None, tuple(sorted(matches)), tuple(matches.values()))


def automatic_transition(
    current_status: str,
    latest_effective: datetime,
    manual_corrected: bool,
    message: MailEvidence,
    meaning: Meaning,
    match: Match,
    *,
    sender_trusted: bool = False,
) -> tuple[bool, str]:
    if manual_corrected:
        return False, "EMAIL_EFFECT_CORRECTED"
    if not sender_trusted or not message.authentication.get("authenticated"):
        return False, "SENDER_TRUST_REVIEW_REQUIRED"
    if match.state != "MATCHED" or meaning.review or not meaning.status:
        return False, "REVIEW_REQUIRED"
    if message.received_at < latest_effective:
        return False, "OLDER_THAN_CURRENT_EVENT"
    if meaning.status == "APPLIED" and current_status != "APPLIED":
        return False, "CONFIRMATION_DOES_NOT_REGRESS"
    if current_status in {"REJECTED", "OFFER"} and meaning.status != current_status:
        return False, "TERMINAL_STATUS_CONFLICT"
    return True, "DETERMINISTIC_MATCH_AND_TEMPLATE"
