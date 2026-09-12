"""Public-result enrichment; no LinkedIn login or profile scraping."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx

from app.email.parser import plain_html

GROUPS = ("Recruiter or HR", "Hiring Manager", "Same Hiring Team", "Same Department/Relevant Department Leader")


class ProviderUnavailable(RuntimeError):
    def __init__(self, state: str, reason: str):
        super().__init__(reason)
        self.state = state
        self.reason = reason


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    description: str
    observed_at: datetime


class BraveSearch:
    """Optional real HTTP adapter. Provider selection requires deployment review."""

    def __init__(self, api_key: str, transport=None):
        self.api_key = api_key
        self.transport = transport

    def search(self, query: str) -> list[SearchResult]:
        if not self.api_key:
            raise ProviderUnavailable("NOT_CONFIGURED", "Public search credentials are not configured")
        try:
            with httpx.Client(timeout=30, transport=self.transport, follow_redirects=False) as client:
                response = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
                    params={"q": query, "count": 20, "country": "us", "search_lang": "en"},
                )
                if response.status_code == 429:
                    raise ProviderUnavailable("RATE_LIMITED", "Search provider rate limit reached")
                if response.status_code in {401, 403}:
                    raise ProviderUnavailable("UNAVAILABLE", "Search provider denied access")
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ProviderUnavailable("UNAVAILABLE", "Search result response exceeds size limit")
                payload = response.json()
        except httpx.HTTPError as exc:
            raise ProviderUnavailable("UNAVAILABLE", "Search provider request failed") from exc
        now = datetime.now(UTC)
        return [
            SearchResult(
                str(row.get("url", "")),
                plain_html(str(row.get("title", "")))[:500],
                plain_html(str(row.get("description", "")))[:2000],
                now,
            )
            for row in payload.get("web", {}).get("results", [])[:20]
        ]


def normalized_linkedin(url: str) -> str | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or parts.username or parts.port not in {None, 443}:
        return None
    if host != "linkedin.com" and not re.fullmatch(r"(?:www|[a-z]{2})\.linkedin\.com", host):
        return None
    match = re.fullmatch(r"/in/([A-Za-z0-9_%\-]+)/?", parts.path)
    if not match:
        return None
    return "https://www.linkedin.com/in/" + match[1].lower()


@dataclass(frozen=True)
class JobContext:
    job_id: str
    company: str
    title: str
    department: str | None = None
    named_recruiter: str | None = None
    named_hiring_manager: str | None = None
    evidence_reference: str | None = None


@dataclass(frozen=True)
class PersonCandidate:
    profile_url: str
    name: str
    role: str
    company: str
    group: str
    evidence_label: str
    explanation: str
    evidence_text: str
    source_url: str
    checked_at: datetime
    verification: str = "SEARCH_RESULT_ONLY"


def _contains(text: str, value: str | None):
    return bool(value and re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.IGNORECASE))


def supported_candidate(result: SearchResult, context: JobContext, now: datetime) -> PersonCandidate | None:
    url = normalized_linkedin(result.url)
    if not url or result.observed_at < now - timedelta(days=30):
        return None
    title = re.sub(r"\s*[|\-]\s*LinkedIn\s*$", "", result.title, flags=re.IGNORECASE)
    pieces = re.split(r"\s+[|\-–]\s+", title, maxsplit=1)
    if len(pieces) != 2:
        return None
    name, role = pieces
    if not (2 <= len(name.split()) <= 6) or not re.search(r"[A-Za-z]", name):
        return None
    text = role + "\n" + result.description
    # A snippet mentioning prior experience does not substantiate current work.
    if not _contains(role, context.company):
        return None
    if re.search(r"\b(former|previously|ex-|retired|past employee)\b", text, re.IGNORECASE):
        return None
    group = None
    label = "LIKELY"
    explanation = (
        "Search result reports a current professional role at this employer; the profile page was not inspected."
    )
    if context.named_hiring_manager and _contains(name, context.named_hiring_manager) and context.evidence_reference:
        group, label = GROUPS[1], "CONFIRMED"
        explanation = "The retained job evidence explicitly names this hiring manager; current employment is supported by a public search result."
    elif re.search(r"\b(recruiter|recruiting|talent acquisition|human resources|HR)\b", role, re.IGNORECASE):
        group = GROUPS[0]
        if context.named_recruiter and _contains(name, context.named_recruiter) and context.evidence_reference:
            label = "CONFIRMED"
            explanation = (
                "The retained job evidence names this recruiter; public search supports the employer relationship."
            )
        else:
            explanation = "Public search reports a recruiting or HR role at the employer; responsibility for this opening is unconfirmed."
    elif (
        context.department
        and _contains(text, context.department)
        and re.search(r"\b(manager|director|head|lead)\b", role, re.IGNORECASE)
    ):
        group = GROUPS[3]
        explanation = (
            "Public search supports leadership in the relevant department; involvement in this opening is unconfirmed."
        )
    if not group:
        return None
    return PersonCandidate(
        url,
        name.strip(),
        role.strip(),
        context.company,
        group,
        label,
        explanation,
        text[:2000],
        result.url,
        result.observed_at,
    )


def select_people(candidates: list[PersonCandidate]) -> list[PersonCandidate]:
    unique = {}
    for candidate in candidates:
        previous = unique.get(candidate.profile_url)
        if not previous or (candidate.evidence_label == "CONFIRMED" and previous.evidence_label != "CONFIRMED"):
            unique[candidate.profile_url] = candidate
    groups = {
        group: sorted(
            (c for c in unique.values() if c.group == group), key=lambda c: (c.name.casefold(), c.profile_url)
        )
        for group in GROUPS
    }
    # Allocate across available groups round-robin, then present group/name order.
    selected = []
    while len(selected) < 10 and any(groups.values()):
        for group in GROUPS:
            if groups[group] and len(selected) < 10:
                selected.append(groups[group].pop(0))
    return sorted(selected, key=lambda c: (GROUPS.index(c.group), c.name.casefold(), c.profile_url))


def queries(context: JobContext) -> list[str]:
    company = context.company.replace('"', " ")[:150]
    terms = ["recruiter", '"talent acquisition"', '"human resources"']
    if context.department:
        department = context.department.replace('"', " ")[:100]
        terms += [f'"{department}" manager', f'"{department}" director']
    terms += [
        f'"{name.replace(chr(34), " ")}"' for name in [context.named_recruiter, context.named_hiring_manager] if name
    ]
    return [f'site:linkedin.com/in/ "{company}" {term}' for term in terms][:8]
