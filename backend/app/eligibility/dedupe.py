"""Conservative identity comparison. Similarity can quarantine, never merge."""

from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field

from .models import Contract


class JobIdentity(Contract):
    canonical_id: str
    source: str | None = None
    tenant: str | None = None
    external_id: str | None = None
    employer_group_id: str | None = None
    requisition_id: str | None = None
    requisition_verified: bool = False
    employer_destination: str | None = None
    destination_identity_verified: bool = False
    title: str = ""
    location: str = ""
    description: str = ""
    explicit_same_opening: list[str] = Field(default_factory=list)


class DuplicateDecision(Contract):
    decision: Literal["SAME", "DISTINCT", "REVIEW"]
    reason: str
    evidence: list[str]
    version: str = "dedupe-1.0"


def canonical_destination(url: str) -> str:
    """Drop known trackers only. Preserve every other identity-bearing query value."""
    parsed = urlsplit(url)
    params = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid"}
    ]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", urlencode(sorted(params)), ""))


def description_hash(description: str) -> str:
    normalized = re.sub(r"\s+", " ", description).strip().casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()


def compare_identity(a: JobIdentity, b: JobIdentity) -> DuplicateDecision:
    if a.canonical_id == b.canonical_id:
        return DuplicateDecision(decision="SAME", reason="CANONICAL_ID", evidence=[a.canonical_id])
    if b.canonical_id in a.explicit_same_opening or a.canonical_id in b.explicit_same_opening:
        return DuplicateDecision(
            decision="SAME", reason="EXPLICIT_CROSSPOST_OR_REPOST", evidence=[a.canonical_id, b.canonical_id]
        )
    same_source = bool(
        a.source
        and a.tenant
        and a.external_id
        and (a.source, a.tenant, a.external_id) == (b.source, b.tenant, b.external_id)
    )
    same_employer = bool(a.employer_group_id and a.employer_group_id == b.employer_group_id)
    verified_reqs = (
        same_employer and a.requisition_verified and b.requisition_verified and a.requisition_id and b.requisition_id
    )
    if same_source:
        if verified_reqs and a.requisition_id != b.requisition_id:
            return DuplicateDecision(
                decision="REVIEW",
                reason="SOURCE_ID_REUSED_WITH_DIFFERENT_REQUISITION",
                evidence=[a.external_id, a.requisition_id, b.requisition_id],
            )
        return DuplicateDecision(
            decision="SAME", reason="SOURCE_TENANT_EXTERNAL_ID", evidence=[a.source, a.tenant, a.external_id]
        )
    if verified_reqs:
        if a.requisition_id == b.requisition_id:
            return DuplicateDecision(
                decision="SAME",
                reason="VERIFIED_EMPLOYER_REQUISITION",
                evidence=[a.employer_group_id, a.requisition_id],
            )
        return DuplicateDecision(
            decision="DISTINCT", reason="DIFFERENT_VERIFIED_REQUISITIONS", evidence=[a.requisition_id, b.requisition_id]
        )
    if (
        same_employer
        and a.destination_identity_verified
        and b.destination_identity_verified
        and a.employer_destination
        and b.employer_destination
        and canonical_destination(a.employer_destination) == canonical_destination(b.employer_destination)
    ):
        # Even unverified conflicting requisition strings defeat automatic URL equality.
        if a.requisition_id and b.requisition_id and a.requisition_id != b.requisition_id:
            return DuplicateDecision(
                decision="REVIEW",
                reason="DESTINATION_REQUISITION_CONFLICT",
                evidence=[a.employer_destination, a.requisition_id, b.requisition_id],
            )
        return DuplicateDecision(
            decision="SAME",
            reason="VERIFIED_EMPLOYER_DESTINATION",
            evidence=[canonical_destination(a.employer_destination)],
        )
    if (
        same_employer
        and a.title.casefold() == b.title.casefold()
        and a.location.casefold() == b.location.casefold()
        and a.description
        and b.description
        and SequenceMatcher(None, a.description.casefold(), b.description.casefold(), autojunk=False).ratio() >= 0.92
    ):
        return DuplicateDecision(
            decision="REVIEW",
            reason="SIMILARITY_ONLY",
            evidence=[description_hash(a.description), description_hash(b.description)],
        )
    return DuplicateDecision(decision="DISTINCT", reason="NO_STRONG_IDENTITY_MATCH", evidence=[])


def identity_tombstones(job: JobIdentity) -> list[str]:
    keys = []
    if job.source and job.tenant and job.external_id:
        keys.append(f"source:{job.source}|{job.tenant}|{job.external_id}")
    if job.employer_group_id and job.requisition_verified and job.requisition_id:
        keys.append(f"req:{job.employer_group_id}|{job.requisition_id}")
    if job.employer_group_id and job.destination_identity_verified and job.employer_destination:
        keys.append("url:" + job.employer_group_id + "|" + canonical_destination(job.employer_destination))
    return keys
