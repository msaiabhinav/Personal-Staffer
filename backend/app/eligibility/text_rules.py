"""Conservative deterministic clause extraction with exact source offsets."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .models import EvidenceRef, Fact, JobEvidence, Policy, RuleDecision, RuleResult


@dataclass(frozen=True)
class Clause:
    text: str
    start: int
    end: int
    section: str


def clauses(text: str) -> list[Clause]:
    result: list[Clause] = []
    section = "UNKNOWN"
    # Keep decimal numbers intact. Newlines preserve qualification section boundaries.
    for match in re.finditer(r"[^\n;!?]+(?:[!?]|(?=\n|;|$))", text):
        line = match.group().strip()
        if not line:
            continue
        if re.match(
            r"(?:preferred|desired|nice.to.have|bonus)\s*(?:qualifications|requirements|skills|:|$)",
            line,
            re.IGNORECASE,
        ):
            section = "PREFERRED"
        elif re.match(
            r"(?:required|minimum|basic|essential)\s*(?:qualifications|requirements|skills|:|$)", line, re.IGNORECASE
        ):
            section = "REQUIRED"
        elif re.match(r"(?:responsibilities|about us|benefits|compensation|what you.ll do)\s*:?$", line, re.IGNORECASE):
            section = "UNKNOWN"
        # Full stops ending sentences, but not U.S. or decimal numbers.
        for sentence in re.finditer(r".+?(?:\.(?=\s+[A-Z]|$)|$)", match.group()):
            raw = sentence.group()
            if not raw.strip():
                continue
            start = match.start() + sentence.start() + len(raw) - len(raw.lstrip())
            end = match.start() + sentence.end() - len(raw) + len(raw.rstrip())
            result.append(Clause(text[start:end], start, end, section))
    return result


def ref(job: JobEvidence, clause: Clause | None = None, field: str | None = None) -> EvidenceRef:
    return EvidenceRef(
        snapshot_id=job.snapshot_id,
        source_url=job.source_url,
        field_path=field,
        text=clause.text if clause else None,
        start=clause.start if clause else None,
        end=clause.end if clause else None,
        observed_at=job.fetched_at,
    )


def result(
    rule: str,
    decision: RuleDecision | str,
    reason: str,
    message: str,
    evidence: list[EvidenceRef],
    flags: list[str] | None = None,
) -> RuleResult:
    return RuleResult(
        rule=rule, decision=decision, reason_code=reason, message=message, evidence=evidence, flags=flags or []
    )


def _is_quoted(text: str) -> bool:
    # Literal policy examples / third-party quote contexts are not current applicant policy.
    return bool(
        re.search(r'["“”]|\b(?:example|quoted|previous posting|old policy|sample wording)\b', text, re.IGNORECASE)
    )


def _requiredness(clause: Clause, *, experience: bool = False) -> str:
    text = clause.text
    if re.search(r"\b(?:not required|no .{0,25} required|do(?:es)? not require)\b", text, re.IGNORECASE):
        return "NOT_REQUIRED"
    required = bool(
        re.search(r"\b(?:required|must|minimum|at least|essential|need(?:s|ed)? to)\b", text, re.IGNORECASE)
    )
    preferred = bool(
        re.search(r"\b(?:preferred|desired|desirable|a plus|nice.to.have|bonus|ideally)\b", text, re.IGNORECASE)
    )
    if required and preferred:
        return "UNKNOWN"
    if preferred:
        return "PREFERRED"
    if required:
        return "REQUIRED"
    if clause.section != "UNKNOWN":
        return clause.section
    return "REQUIRED" if experience else "UNKNOWN"


SPONSORSHIP_DENIALS = (
    r"\b(?:cannot|can't|unable to|will not|won't|do not|does not)\s+(?:currently\s+|now\s+)?(?:offer|provide|support|consider|facilitate)\s+(?:\w+\s+){0,4}(?:sponsorship|visa transfers?)\b",
    r"\b(?:cannot|can't|unable to|will not|won't|do not|does not)\s+sponsor\b",
    r"\bno\s+(?:(?:visa|immigration|employment|work)\s+)?sponsorship\b(?!\s+(?:is\s+)?(?:required|needed|necessary))",
    r"\b(?:sponsorship|visa transfers?)\s+(?:(?:is|are|will be)\s+)?(?:not available|unavailable|not offered|not provided|not supported|not possible)\b",
    r"\b(?:without|not require|must not need)\s+(?:the need for\s+)?(?:(?:current|future|now|any|employment|visa)\s+){0,4}sponsorship\b",
    r"\bno\s+(?:visa\s+)?transfers?\b",
    r"\b(?:only\s+(?:u\.?s\.?\s+)?(?:citizens|permanent residents)|(?:u\.?s\.?\s+)?(?:citizens|permanent residents)\s+(?:and\s+permanent residents\s+)?only)\b",
    r"\b(?:must be|restricted to|limited to)\s+(?:a\s+)?(?:u\.?s\.?\s+)?(?:citizen|permanent resident)\b",
    r"\b(?:permanent(?:ly)?\s+(?:and\s+)?unrestricted|unrestricted\s+permanent)\s+(?:work\s+)?authori[sz]ation\b",
    r"\b(?:opt|stem[ -]?opt|cpt|visa[ -]candidates?)\b.{0,65}\b(?:not eligible|ineligible|not accepted|not considered|cannot apply|need not apply)\b",
    r"\b(?:no|excluding|cannot accept|do not accept)\s+(?:opt|stem[ -]?opt|cpt|visa[ -]candidates?)\b",
)


def sponsorship_rule(job: JobEvidence) -> tuple[RuleResult, Fact]:
    if not job.description_complete:
        return (
            result(
                "sponsorship",
                "UNKNOWN",
                "SPONSORSHIP_EVIDENCE_INCOMPLETE",
                "Sponsorship cannot be assessed from an incomplete JD.",
                [ref(job, field="description_complete")],
            ),
            Fact(field="sponsorship", state="UNKNOWN", evidence=[ref(job, field="description_complete")]),
        )
    negative, available, ambiguous = [], [], []
    for clause in clauses(job.description):
        t = clause.text
        if not re.search(r"sponsor|visa|citizen|permanent resident|authori[sz]ation|\b(?:opt|cpt)\b", t, re.IGNORECASE):
            continue
        if re.search(
            r"\b(?:do not|does not|not)\s+(?:prohibit|exclude|ban|restrict)\b.{0,40}\b(?:visa|sponsorship)",
            t,
            re.IGNORECASE,
        ):
            continue
        denial = any(re.search(pattern, t, re.IGNORECASE) for pattern in SPONSORSHIP_DENIALS)
        if _is_quoted(t) and denial:
            ambiguous.append(clause)
        elif denial:
            negative.append(clause)
        elif re.search(
            r"\b(?:sponsorship\s+(?:is\s+)?(?:available|offered|provided)|(?:offer|provide|support)\s+(?:visa\s+)?sponsorship|visa candidates\s+(?:are\s+)?welcome)\b",
            t,
            re.IGNORECASE,
        ):
            available.append(clause)
        elif re.search(r"\bno sponsorship\s+(?:is\s+)?(?:required|needed|necessary)\b", t, re.IGNORECASE):
            # Not the same as employer refusal. Conditional boilerplate still needs review.
            if re.search(r"\b(?:if|when|who)\b", t, re.IGNORECASE):
                ambiguous.append(clause)
        elif re.search(r"sponsorship|visa transfer|visa candidates|stem[ -]?opt|\bcpt\b", t, re.IGNORECASE):
            ambiguous.append(clause)
    evidence = [ref(job, c) for c in negative + available + ambiguous]
    if negative:
        return (
            result(
                "sponsorship",
                "FAIL",
                "SPONSORSHIP_RESTRICTED",
                "Explicit work-authorization or sponsorship restriction.",
                evidence,
            ),
            Fact(
                field="sponsorship",
                state="CONFLICTING" if available else "KNOWN",
                value="RESTRICTED",
                polarity="NEGATIVE",
                evidence=evidence,
            ),
        )
    if ambiguous:
        return (
            result(
                "sponsorship",
                "REVIEW",
                "SPONSORSHIP_AMBIGUOUS",
                "Sponsorship wording needs contextual review.",
                evidence,
            ),
            Fact(field="sponsorship", state="UNKNOWN", evidence=evidence),
        )
    return (
        result(
            "sponsorship",
            "PASS",
            "SPONSORSHIP_AVAILABLE" if available else "SPONSORSHIP_NOT_STATED",
            "Available" if available else "Not stated; no exclusion found in complete JD.",
            evidence or [ref(job, field="description")],
        ),
        Fact(
            field="sponsorship",
            state="KNOWN" if available else "NOT_STATED",
            value="AVAILABLE" if available else "NOT_STATED",
            evidence=evidence or [ref(job, field="description")],
        ),
    )


CLEARANCE_TERMS = r"\b(?:security clearance|clearance|public trust|government suitability|doe\s+[ql]|ts[ /-]sci)\b"
NO_CLEARANCE = r"\b(?:no\s+(?:security\s+)?clearance\s+(?:is\s+)?(?:required|needed)|(?:security\s+)?clearance\s*:?\s*(?:is\s+)?(?:not\s+(?:required|needed)|none|n/a)|do(?:es)? not require\s+(?:a\s+)?(?:security\s+)?clearance|(?:not necessary|no need) to (?:obtain|hold|maintain)\s+(?:a\s+)?(?:security\s+)?clearance)\b"


def clearance_rule(job: JobEvidence) -> tuple[RuleResult, Fact]:
    if not job.description_complete:
        return (
            result(
                "clearance",
                "UNKNOWN",
                "CLEARANCE_EVIDENCE_INCOMPLETE",
                "Clearance cannot be assessed from an incomplete JD.",
                [ref(job, field="description_complete")],
            ),
            Fact(field="clearance", state="UNKNOWN", evidence=[ref(job, field="description_complete")]),
        )
    required, preferred, negated, ambiguous = [], [], [], []
    for clause in clauses(job.description):
        t = clause.text
        if not re.search(CLEARANCE_TERMS, t, re.IGNORECASE):
            continue
        if _is_quoted(t):
            ambiguous.append(clause)
        elif re.search(NO_CLEARANCE, t, re.IGNORECASE):
            # Contrasting clauses could contain a second requirement; never drop it.
            if re.search(r"\b(?:but|however|although)\b", t, re.IGNORECASE):
                ambiguous.append(clause)
            else:
                negated.append(clause)
        elif re.search(
            r"\b(?:ability|able|eligible|willing)\s+to\s+(?:obtain|maintain)|\b(?:obtain|maintain|hold|possess)\b.{0,35}(?:clearance|public trust)|(?:current|active)\s+.{0,15}clearance",
            t,
            re.IGNORECASE,
        ):
            if _requiredness(clause) == "PREFERRED":
                preferred.append(clause)
            else:
                required.append(clause)
        elif _requiredness(clause) == "PREFERRED":
            preferred.append(clause)
        elif _requiredness(clause) == "REQUIRED":
            required.append(clause)
        else:
            ambiguous.append(clause)
    evidence = [ref(job, c) for c in required + preferred + negated + ambiguous]
    if required:
        return (
            result(
                "clearance",
                "FAIL",
                "CLEARANCE_REQUIRED",
                "Required clearance or ability to obtain/maintain it is excluded.",
                evidence,
            ),
            Fact(field="clearance", state="KNOWN", value="REQUIRED", requiredness="REQUIRED", evidence=evidence),
        )
    if ambiguous:
        return (
            result("clearance", "REVIEW", "CLEARANCE_AMBIGUOUS", "Clearance requiredness is unresolved.", evidence),
            Fact(field="clearance", state="UNKNOWN", evidence=evidence),
        )
    value = "PREFERRED_ONLY" if preferred else "NOT_REQUIRED" if negated else "NO_REQUIREMENT_FOUND"
    return (
        result(
            "clearance",
            "PASS",
            "CLEARANCE_" + value,
            "Preferred only" if preferred else "Not required" if negated else "No requirement found in complete JD.",
            evidence or [ref(job, field="description")],
            ["CLEARANCE_PREFERRED"] if preferred else [],
        ),
        Fact(
            field="clearance",
            state="KNOWN" if (preferred or negated) else "NOT_STATED",
            value=value,
            requiredness="PREFERRED" if preferred else "NOT_REQUIRED" if negated else "UNKNOWN",
            evidence=evidence or [ref(job, field="description")],
        ),
    )


NUMBERS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "eleven": "11",
    "twelve": "12",
    "fifteen": "15",
    "twenty": "20",
}
N = r"(?:\d+(?:\.\d+)?|" + "|".join(NUMBERS) + ")"
EXPERIENCE = re.compile(
    r"(?P<comp>at least|at minimum|minimum(?: of)?|more than|greater than|over|up to|at most|no more than|less than|under)?\s*(?P<low>"
    + N
    + r")(?:\s*\(\d+\))?\s*(?P<plus>\+)?(?:\s*(?:-|–|—|to)\s*(?P<high>"
    + N
    + r"))?\s*(?P<unit>years?|yrs?|months?)\b",
    re.IGNORECASE,
)


def _number(value: str) -> Decimal:
    return Decimal(NUMBERS.get(value.casefold(), value))


def experience_rule(job: JobEvidence, policy: Policy) -> tuple[RuleResult, list[Fact]]:
    if not job.description_complete:
        return result(
            "experience",
            "UNKNOWN",
            "EXPERIENCE_EVIDENCE_INCOMPLETE",
            "Experience cannot be assessed from an incomplete JD.",
            [ref(job, field="description_complete")],
        ), [Fact(field="experience", state="UNKNOWN", evidence=[ref(job, field="description_complete")])]
    facts, required, ambiguous, all_refs = [], [], [], []
    for clause in clauses(job.description):
        t = clause.text
        matches = list(EXPERIENCE.finditer(t))
        if not matches:
            if re.search(
                r"\b(?:no (?:prior |previous |work |professional )?experience (?:is )?(?:required|needed)|entry.level.{0,15}no experience)\b",
                t,
                re.IGNORECASE,
            ):
                r = ref(job, clause)
                facts.append(
                    Fact(
                        field="experience",
                        state="KNOWN",
                        value={"minimum": "0", "maximum": "0", "comparator": "EXACT", "unit": "years", "as_written": t},
                        requiredness="REQUIRED",
                        evidence=[r],
                    )
                )
                required.append((Decimal(0), Decimal(0), "EXACT", r))
            continue
        # Company age, benefits tenure and history must never become a candidate requirement.
        if re.search(
            r"\b(?:founded|established|company has|company with|we have|we.ve been|after employment|after (?:one|two|\d+) years|vesting|anniversary|paid time off)\b",
            t,
            re.IGNORECASE,
        ) and not re.search(r"\b(?:you|candidate|applicant|required|must)\b", t, re.IGNORECASE):
            continue
        refs = [ref(job, clause)]
        all_refs.extend(refs)
        alt = bool(
            re.search(r"\b(?:or|alternatively)\b", t, re.IGNORECASE)
            and (len(matches) > 1 or re.search(r"bachelor|master|degree|equivalent", t, re.IGNORECASE))
        )
        for match in matches:
            low = _number(match.group("low"))
            high = _number(match.group("high")) if match.group("high") else low
            unit = match.group("unit").lower()
            if unit.startswith("month"):
                low, high = low / 12, high / 12
            comp = (match.group("comp") or "").lower()
            comparator = (
                "RANGE"
                if match.group("high")
                else "PLUS"
                if match.group("plus")
                else "AT_LEAST"
                if comp in ("at least", "at minimum", "minimum", "minimum of")
                else "MORE_THAN"
                if comp in ("more than", "greater than", "over")
                else "UP_TO"
                if comp in ("up to", "at most", "no more than")
                else "LESS_THAN"
                if comp in ("less than", "under")
                else "EXACT"
            )
            # Comparators can follow the duration or be separated from it by "experience".
            trailing = t[match.end() :]
            leading = t[: match.start()]
            if comparator == "EXACT" and (
                re.match(
                    r"\s*(?:of\s+)?(?:relevant\s+)?(?:experience\s+)?(?:or more|and above|and over|minimum|at (?:a )?minimum)\b",
                    trailing,
                    re.IGNORECASE,
                )
                or re.search(
                    r"\b(?:minimum|at least)\s+(?:required\s+)?(?:experience\s*)?(?:of\s*)?[:=]?\s*$",
                    leading,
                    re.IGNORECASE,
                )
            ):
                comparator = "AT_LEAST"
            # Mixed required/preferred wording needs clauses separated by conjunction, not a sentence-wide preference.
            local_start = max(
                t.rfind(",", 0, match.start("low")),
                t.rfind(" but ", 0, match.start("low")),
                t.rfind(" and ", 0, match.start("low")),
            )
            next_match = (
                matches[matches.index(match) + 1].start() if matches.index(match) + 1 < len(matches) else len(t)
            )
            local = (
                t[local_start + (5 if t[local_start : local_start + 5] in (" but ", " and ") else 1) : next_match]
                if local_start >= 0
                else t[:next_match]
            )
            requiredness = _requiredness(Clause(local, clause.start, clause.end, clause.section), experience=True)
            state = (
                "UNKNOWN"
                if (alt or _is_quoted(t) or requiredness == "UNKNOWN" or comparator == "LESS_THAN" or high < low)
                else "KNOWN"
            )
            facts.append(
                Fact(
                    field="experience",
                    state=state,
                    value={
                        "minimum": str(low),
                        "maximum": str(high) if comparator in ("EXACT", "RANGE", "UP_TO") else None,
                        "comparator": comparator,
                        "unit": "years",
                        "as_written": match.group().strip(),
                        "clause": t,
                        "alternative": alt,
                    },
                    requiredness=requiredness,
                    evidence=refs,
                )
            )
            if state == "UNKNOWN":
                ambiguous.extend(refs)
            elif requiredness == "REQUIRED":
                required.append((low, high, comparator, refs[0]))
    failed = []
    for low, high, comparator, evidence in required:
        if high > policy.maximum_exact_experience or (
            comparator in ("PLUS", "AT_LEAST", "MORE_THAN") and low >= policy.plus_exclusion_start
        ):
            failed.append(evidence)
    if failed:
        return result(
            "experience",
            "FAIL",
            "EXPERIENCE_ABOVE_POLICY",
            "A mandatory experience clause exceeds the allowed comparator/range policy.",
            failed,
        ), facts
    if ambiguous:
        return result(
            "experience",
            "REVIEW",
            "EXPERIENCE_AMBIGUOUS",
            "Experience alternatives, quoted clauses or requiredness need review.",
            ambiguous,
        ), facts
    if not required:
        return result(
            "experience",
            "REVIEW",
            "EXPERIENCE_NOT_STATED",
            "No interpretable mandatory experience requirement found in the complete JD.",
            all_refs or [ref(job, field="description")],
        ), facts or [Fact(field="experience", state="NOT_STATED", evidence=[ref(job, field="description")])]
    return result(
        "experience",
        "PASS",
        "EXPERIENCE_ALLOWED",
        "All mandatory experience clauses pass; preferred years are informational.",
        [item[3] for item in required],
    ), facts
