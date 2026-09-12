"""Pure, reproducible eligibility evaluation. No provider access or database writes."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from app.relevance.engine import analyze_relevance

from .models import Evaluation, Fact, JobEvidence, Policy, RuleDecision, RuleResult, Salary
from .text_rules import clauses, clearance_rule, experience_rule, ref, result, sponsorship_rule


def salary_band(salary: Salary, preferred: float = 80000) -> str:
    if (salary.currency or "").upper() != "USD" or (salary.interval or "").upper() not in ("YEAR", "YEARLY", "ANNUAL"):
        return "B"
    if salary.minimum is not None and salary.minimum >= preferred:
        return "A"
    if salary.maximum is not None and salary.maximum < preferred:
        return "C"
    return "B"


def priority_reasons(job: JobEvidence, *, eligible: bool, relevant: bool) -> list[str]:
    if not eligible or not relevant:
        return []
    reasons = []
    if job.watchlisted and job.employer_group_id:
        reasons.append("WATCHLIST")
    if (job.university or job.academic_medical_center) and {"US", "USA"}.intersection(
        c.upper() for c in job.country_codes
    ):
        reasons.append("UNIVERSITY")
    if (job.work_arrangement in ("ONSITE", "HYBRID") and "CT" in {s.upper() for s in job.workplace_states}) or (
        job.work_arrangement == "REMOTE" and "CT" in {s.upper() for s in job.explicit_remote_states}
    ):
        reasons.append("CONNECTICUT")
    return reasons


def _country(job: JobEvidence) -> RuleResult:
    refs = [ref(job, field="country_codes")]
    if job.country_conflicting:
        return result("country", "REVIEW", "COUNTRY_CONFLICTING", "U.S. hiring evidence conflicts.", refs)
    countries = {c.upper() for c in job.country_codes}
    if "US" in countries or "USA" in countries:
        return result(
            "country", "PASS", "COUNTRY_US_CONFIRMED", "U.S. workplace or hiring geography established.", refs
        )
    if countries:
        return result("country", "FAIL", "COUNTRY_NOT_US", "Confirmed hiring geography excludes the U.S.", refs)
    return result(
        "country",
        "UNKNOWN",
        "COUNTRY_NOT_ESTABLISHED",
        "Remote alone does not establish U.S. hiring eligibility.",
        refs,
    )


ENGAGEMENT = r"\b(?:contract.to.hire|fixed.term|part.time|temporary|seasonal|internship|per.diem|freelance|consulting engagement)\b"


def _employment(job: JobEvidence) -> RuleResult:
    refs = [ref(job, field="employment_type")]
    declared = (job.employment_type or "").replace("_", " ").lower()
    if declared in {
        "contract",
        "contractor",
        "contract to hire",
        "contract-to-hire",
        "fixed term",
        "fixed-term",
        "temporary",
        "part time",
        "part-time",
        "seasonal",
        "internship",
        "per diem",
        "per-diem",
        "freelance",
        "consulting",
    }:
        return result(
            "employment", "FAIL", "EMPLOYMENT_EXCLUDED", "The stated engagement is not permanent full-time.", refs
        )
    exclusions = []
    positives = []
    for clause in clauses(job.description):
        text = clause.text
        excluded = bool(
            re.search(ENGAGEMENT, text, re.IGNORECASE)
            or re.search(
                r"\b(?:this|the)\s+(?:is\s+a\s+|role is\s+(?:a\s+)?|position is\s+(?:a\s+)?)contract\b|\bcontract(?:or)? (?:role|position|job|engagement|assignment)\b|\b\d+.month contract\b|\b(?:employment|job|engagement|position)\s*(?:type)?\s*:\s*(?:contract|contractor|consultant)\b|^\s*contract(?:or)?\s*$",
                text,
                re.IGNORECASE,
            )
        )
        # Experience managing contracts, past internships and company type aren't engagement types.
        if excluded and not re.search(
            r"\b(?:prior|previous|past|manag(?:e|ing)|negotiate|vendor|customer)\b.{0,35}(?:contracts?|internship)|\bnot (?:a )?(?:contract|temporary|part.time)",
            text,
            re.IGNORECASE,
        ):
            exclusions.append(ref(job, clause))
        if re.search(r"\bfull[ -]time\b", text, re.IGNORECASE):
            positives.append(ref(job, clause))
    if exclusions:
        return result(
            "employment",
            "FAIL",
            "EMPLOYMENT_EXCLUDED",
            "JD states an excluded engagement; full-time metadata cannot override it.",
            exclusions + refs,
        )
    if job.staffing and (not job.permanent_placement or not job.payroll_entity_verified):
        return result(
            "employment",
            "UNKNOWN",
            "STAFFING_EMPLOYER_UNVERIFIED",
            "Permanent placement and actual payroll employer must be established.",
            [
                ref(job, field="staffing"),
                ref(job, field="permanent_placement"),
                ref(job, field="payroll_entity_verified"),
            ],
        )
    if declared in ("full time", "full-time", "permanent full time") or positives:
        return result(
            "employment",
            "PASS",
            "EMPLOYMENT_FULL_TIME",
            "Permanent full-time engagement established.",
            refs + positives,
        )
    return result(
        "employment", "UNKNOWN", "EMPLOYMENT_NOT_ESTABLISHED", "Full-time employment is not established.", refs
    )


def _freshness(job: JobEvidence, now: datetime, policy: Policy) -> RuleResult:
    pub = job.publication
    refs = [ref(job, field="publication")]
    if job.known_repost:
        return result(
            "freshness",
            "FAIL",
            "KNOWN_REPOST",
            "Known old/reposted identity cannot become new through publication updates.",
            [ref(job, field="known_repost")],
        )
    if pub.kind not in ("ORIGINAL", "LAST_PUBLICATION"):
        return result(
            "freshness",
            "UNKNOWN",
            "PUBLICATION_NOT_ESTABLISHED",
            "First-seen/update time is not publication evidence.",
            refs,
        )
    if pub.kind == "LAST_PUBLICATION" and not pub.repost_checked:
        return result(
            "freshness",
            "REVIEW",
            "REPOST_CHECK_REQUIRED",
            "Last-publication evidence requires independent repost checks.",
            refs,
        )
    if pub.earliest is None or pub.latest is None or pub.precision == "UNKNOWN":
        return result(
            "freshness",
            "UNKNOWN",
            "PUBLICATION_NOT_ESTABLISHED",
            "Publication precision and possible interval are required.",
            refs,
        )
    earliest_allowed = now - timedelta(hours=policy.max_posting_age_hours)
    future_allowed = now + timedelta(seconds=policy.clock_tolerance_seconds)
    if pub.latest < earliest_allowed:
        return result(
            "freshness", "FAIL", "POSTING_TOO_OLD", "All possible publication times are older than 72 hours.", refs
        )
    if pub.latest > future_allowed:
        return result(
            "freshness", "REVIEW", "PUBLICATION_FUTURE", "Publication interval extends beyond clock tolerance.", refs
        )
    if pub.earliest < earliest_allowed:
        return result(
            "freshness",
            "REVIEW",
            "PUBLICATION_BOUNDARY_UNRESOLVED",
            "Publication interval crosses the allowed freshness boundary.",
            refs,
        )
    return result(
        "freshness",
        "PASS",
        "POSTING_FRESH",
        "Just posted" if pub.earliest > now else "The entire publication interval is within the allowed window.",
        refs,
        ["CLOCK_SKEW_TOLERATED"] if pub.latest > now else [],
    )


def _everify(job: JobEvidence, now: datetime, policy: Policy, allow_synthetic: bool) -> RuleResult:
    strict = _everify_strict(job, now, policy, allow_synthetic)
    if policy.everify_gate == "REQUIRED" or strict.decision == "PASS":
        return strict
    # Informational mode: the fact and its reason stay visible, but the gate does not withhold.
    return RuleResult(
        rule="everify",
        rule_version=strict.rule_version,
        decision="PASS",
        reason_code=strict.reason_code + "_INFORMATIONAL",
        message=strict.message + " E-Verify is informational for this owner; delivery is not withheld.",
        evidence=strict.evidence,
        flags=[*strict.flags, "EVERIFY_INFORMATIONAL"],
    )


def _everify_strict(job: JobEvidence, now: datetime, policy: Policy, allow_synthetic: bool) -> RuleResult:
    ev = job.everify
    refs = [ref(job, field="legal_entity_id"), ref(job, field="everify")]
    if (job.synthetic or ev.synthetic) and not allow_synthetic:
        return result(
            "everify",
            "UNKNOWN",
            "SYNTHETIC_EVIDENCE_PROHIBITED",
            "Synthetic evidence cannot authorize production delivery.",
            refs,
        )
    if ev.status == "CONFLICTING":
        return result(
            "everify", "REVIEW", "EVERIFY_CONFLICTING", "Employer participation/identity evidence conflicts.", refs
        )
    if ev.status != "CONFIRMED":
        return result(
            "everify",
            "UNKNOWN",
            "EVERIFY_NOT_CONFIRMED",
            "Search misses and unsupported labels do not establish nonparticipation or approval.",
            refs,
        )
    if not job.legal_entity_id or not ev.identity_match or ev.legal_entity_id != job.legal_entity_id:
        return result(
            "everify",
            "UNKNOWN",
            "EVERIFY_ENTITY_UNRESOLVED",
            "Confirmed evidence must match the actual legal/payroll employer.",
            refs,
        )
    if not all((ev.legal_name, ev.source_reference, ev.evidence_hash, ev.checked_at, ev.method, ev.reviewer)):
        return result(
            "everify",
            "UNKNOWN",
            "EVERIFY_PROVENANCE_INCOMPLETE",
            "Confirmation requires legal name, source, retained hash, check date, method and reviewer.",
            refs,
        )
    assert ev.checked_at is not None
    if ev.checked_at > now + timedelta(seconds=policy.clock_tolerance_seconds):
        return result(
            "everify", "REVIEW", "EVERIFY_CHECK_FUTURE", "Employer evidence check date is in the future.", refs
        )
    deadline = (
        min(ev.checked_at + timedelta(days=policy.everify_recheck_days), ev.recheck_due_at)
        if ev.recheck_due_at
        else ev.checked_at + timedelta(days=policy.everify_recheck_days)
    )
    if now >= deadline:
        return result("everify", "UNKNOWN", "EVERIFY_STALE", "Employer confirmation passed its recheck deadline.", refs)
    return result(
        "everify", "PASS", "EVERIFY_CONFIRMED", "Current evidence identifies the matching legal employer.", refs
    )


def _opening(job: JobEvidence, now: datetime, policy: Policy) -> RuleResult:
    opening = job.opening
    refs = [ref(job, field="opening")]
    if opening.status == "CLOSED":
        return result("active_opening", "FAIL", "OPENING_CLOSED", "The particular opening is explicitly closed.", refs)
    if opening.http_status in (401, 403, 429) or (opening.http_status and opening.http_status >= 500):
        return result(
            "active_opening",
            "UNKNOWN",
            "OPENING_CHECK_BLOCKED",
            "Temporary access failure does not establish closure or activity.",
            refs,
        )
    if opening.generic_careers_redirect:
        return result(
            "active_opening",
            "UNKNOWN",
            "GENERIC_CAREERS_REDIRECT",
            "A generic careers page is not the particular active opening.",
            refs,
        )
    parsed = urlparse(opening.application_url or "")
    if not (
        opening.status == "ACTIVE"
        and opening.identity_match
        and opening.actionable
        and parsed.scheme in ("http", "https")
        and parsed.hostname
        and opening.checked_at
        and opening.evidence_text
    ):
        return result(
            "active_opening",
            "UNKNOWN",
            "OPENING_NOT_VERIFIED",
            "Specific identity, actionable application route and dated evidence are required.",
            refs,
        )
    if opening.checked_at > now + timedelta(seconds=policy.clock_tolerance_seconds):
        return result("active_opening", "REVIEW", "OPENING_CHECK_FUTURE", "Opening check date is in the future.", refs)
    if opening.checked_at + timedelta(hours=policy.opening_recheck_hours) < now:
        return result(
            "active_opening",
            "UNKNOWN",
            "OPENING_CHECK_STALE",
            "Opening evidence must be rechecked before delivery.",
            refs,
        )
    return result(
        "active_opening",
        "PASS",
        "OPENING_ACTIVE",
        "Specific opening has a recently verified actionable application route.",
        refs,
    )


def evaluate_job(
    job: JobEvidence, *, now: datetime, policy: Policy | None = None, allow_synthetic: bool = False
) -> Evaluation:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("evaluation time must be timezone-aware")
    now = now.astimezone(UTC)
    policy = policy or Policy()
    rules = [
        result(
            "description",
            "PASS" if job.description_complete and job.description.strip() else "UNKNOWN",
            "DESCRIPTION_COMPLETE"
            if job.description_complete and job.description.strip()
            else "DESCRIPTION_INCOMPLETE",
            "Complete readable JD retained."
            if job.description_complete and job.description.strip()
            else "Full successfully retrieved JD is mandatory.",
            [ref(job, field="description_complete")],
        ),
        _country(job),
        _employment(job),
        _freshness(job, now, policy),
        _everify(job, now, policy, allow_synthetic),
        _opening(job, now, policy),
    ]
    facts = [
        Fact(
            field="country",
            state="CONFLICTING" if job.country_conflicting else "KNOWN" if job.country_codes else "UNKNOWN",
            value=job.country_codes,
            evidence=[ref(job, field="country_codes")],
        ),
        Fact(
            field="employment",
            state="KNOWN" if job.employment_type else "UNKNOWN",
            value=job.employment_type,
            evidence=[ref(job, field="employment_type")],
        ),
        Fact(
            field="publication",
            state="KNOWN" if job.publication.earliest else "UNKNOWN",
            value=job.publication.model_dump(mode="json"),
            evidence=[ref(job, field="publication")],
        ),
        Fact(
            field="everify",
            state="CONFLICTING"
            if job.everify.status == "CONFLICTING"
            else "KNOWN"
            if job.everify.status == "CONFIRMED"
            else "UNKNOWN",
            value=job.everify.model_dump(mode="json"),
            evidence=[ref(job, field="everify")],
        ),
        Fact(
            field="active_opening",
            state="KNOWN" if job.opening.status != "UNKNOWN" else "UNKNOWN",
            value=job.opening.model_dump(mode="json"),
            evidence=[ref(job, field="opening")],
        ),
    ]
    sponsorship, sponsor_fact = sponsorship_rule(job)
    clearance, clearance_fact = clearance_rule(job)
    experience, experience_facts = experience_rule(job, policy)
    rules.extend([sponsorship, clearance, experience])
    facts.extend([sponsor_fact, clearance_fact, *experience_facts])
    relevance = analyze_relevance(
        job.title, job.description, complete=job.description_complete, vocabulary=policy.skill_vocabulary
    )
    rules.append(
        result(
            "role_relevance",
            "PASS" if relevance.relevant else "REVIEW" if relevance.relevant is None else "FAIL",
            "ROLE_RELEVANT"
            if relevance.relevant
            else "ROLE_RESPONSIBILITIES_UNRESOLVED"
            if relevance.relevant is None
            else "ROLE_UNRELATED",
            relevance.reason,
            [ref(job, field="title"), ref(job, field="description")],
        )
    )
    decision = (
        "INELIGIBLE"
        if any(r.decision == RuleDecision.FAIL for r in rules)
        else "NEEDS_REVIEW"
        if any(r.decision in (RuleDecision.UNKNOWN, RuleDecision.REVIEW) for r in rules)
        else "ELIGIBLE"
    )
    deadlines = []
    if job.publication.earliest:
        deadlines.append(job.publication.earliest + timedelta(hours=policy.max_posting_age_hours))
    if job.everify.checked_at:
        deadlines.append(job.everify.checked_at + timedelta(days=policy.everify_recheck_days))
    if job.everify.recheck_due_at:
        deadlines.append(job.everify.recheck_due_at)
    if job.opening.checked_at:
        deadlines.append(job.opening.checked_at + timedelta(hours=policy.opening_recheck_hours))
    return Evaluation(
        job_id=job.id,
        snapshot_id=job.snapshot_id,
        decision=decision,
        ruleset_version=policy.version,
        evaluated_at=now,
        valid_until=min(deadlines) if deadlines else None,
        rules=rules,
        facts=facts,
        salary_band=salary_band(job.salary, policy.preferred_salary_usd),
        priority_reasons=priority_reasons(job, eligible=decision == "ELIGIBLE", relevant=relevance.relevant is True),
        relevance=relevance,
        synthetic=job.synthetic or job.everify.synthetic,
    )
