"""Extractive relevance: family + actual responsibilities, never a match score."""

from __future__ import annotations

import re

from app.eligibility.models import RelevanceResult

VERSION = "relevance-1.0"
SKILLS: dict[str, tuple[str, ...]] = {
    "SQL": ("sql",),
    "Power BI": ("power bi", "powerbi", "powwerbi"),
    "Python": ("python",),
    "Excel": ("excel",),
    "machine learning": ("machine learning", "ml"),
    "Snowflake": ("snowflake",),
    "AI": ("ai", "artificial intelligence"),
    "LLMs": ("llm", "llms", "large language model", "large language models"),
    "forecasting": ("forecasting",),
    "business analysis": ("business analysis",),
    "Tableau": ("tableau",),
    "Excel lookup functions": ("vlookup", "xlookup"),
    "Qlik": ("qlik", "qlikview", "qlik sense"),
    "pandas": ("pandas",),
    "Databricks": ("databricks",),
    "statistics": ("statistics", "statistical analysis"),
    "data analysis": ("data analysis",),
}
RELATED = {
    "SQL": ("postgresql", "mysql", "t-sql"),
    "Power BI": ("looker",),
    "machine learning": ("pytorch", "tensorflow", "scikit-learn"),
    "Snowflake": ("bigquery", "redshift"),
    "AI": ("generative ai",),
}
FAMILIES: dict[str, str] = {
    "Data analysis": r"\b(?:(?:data|product|customer|marketing|research data|insights)\s+analyst|data analytics)\b",
    "Business analysis": r"\b(?:business (?:systems |process )?analyst|technical (?:business )?analyst)\b",
    "Business intelligence": r"\b(?:business intelligence|bi analyst|reporting analyst|insights analyst)\b",
    "Operations and revenue": r"\b(?:(?:operations|sales|revenue(?: operations)?|growth) analyst|business operations|strategy\s*(?:and|&|/)\s*operations)\b",
    "AI and machine learning": r"\b(?:ai (?:analyst|engineer|solutions engineer)|artificial intelligence (?:analyst|engineer)|machine learning (?:analyst|engineer))\b",
    "Analytics engineering": r"\b(?:analytics engineer|data analytics engineer|analytical data model(?:ing|er))\b",
    "Deployment": r"\b(?:forward (?:deployed|deployment)(?: ai)? engineer|deployment strategist)\b",
    "Domain analysis": r"\b(?:(?:healthcare|supply chain|financial|institutional research|enrollment|student success) (?:data |business )?analyst)\b",
}
DUTIES = (
    r"\b(?:build|develop|create|maintain|design|deliver|automate|produce|own|prepare)\w*\b[^.!?\n]{0,70}\b(?:dashboards?|reports?|reporting|data models?|analytics|kpis?|forecasts?)\b",
    r"\b(?:analy[sz]e|evaluate|interpret|model|forecast|monitor|optimi[sz]e)\w*\b[^.!?\n]{0,80}\b(?:data|revenue|pricing|performance|kpis?|demand|sales|trends?|business processes|experiments?)\b",
    r"\b(?:implement|develop|deploy|train|build|integrate)\w*\b[^.!?\n]{0,70}\b(?:ai|machine learning|ml models?|llms?|predictive models?)\b",
    r"\b(?:gather|translate|document|analy[sz]e|map)\w*\b[^.!?\n]{0,70}\b(?:business requirements|business processes|data requirements)\b",
    r"\b(?:support|inform|enable|drive)\w*\b[^.!?\n]{0,60}\b(?:business decisions|decision making|data-driven decisions)\b",
    r"\b(?:design|run|analy[sz]e)\w*\b[^.!?\n]{0,60}\b(?:a/b tests|experimentation|statistical experiments)\b",
)
EXCLUDED_TITLES = r"\b(?:professor|faculty|postdoc(?:toral)?|teacher|lecturer|teaching assistant)\b"


def _contains(text: str, token: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", text, re.IGNORECASE))


def canonicalize_skills(vocabulary: list[str]) -> list[str]:
    normalized = []
    for item in vocabulary:
        canonical = next(
            (
                key
                for key, aliases in SKILLS.items()
                if item.strip().casefold() in (a.casefold() for a in (key, *aliases))
            ),
            item.strip(),
        )
        if canonical and canonical not in normalized:
            normalized.append(canonical)
    return normalized


def analyze_relevance(
    title: str, description: str, *, complete: bool = True, vocabulary: list[str] | None = None
) -> RelevanceResult:
    original = list(vocabulary) if vocabulary is not None else list(SKILLS)
    requested = canonicalize_skills(original)
    direct = [key for key in requested if any(_contains(description, alias) for alias in SKILLS.get(key, (key,)))]
    related = {key: [term for term in RELATED.get(key, ()) if _contains(description, term)] for key in requested}
    related = {key: vals for key, vals in related.items() if vals}
    required, preferred = [], []
    section = "UNKNOWN"
    for line in description.splitlines():
        if re.match(r"\s*(?:preferred|desired|nice.to.have|bonus)\b", line, re.IGNORECASE):
            section = "PREFERRED"
        elif re.match(r"\s*(?:required|minimum|basic|essential)\b", line, re.IGNORECASE):
            section = "REQUIRED"
        for clause in re.split(r"[.;\n]", line):
            target = (
                preferred
                if re.search(r"\b(?:preferred|desired|a plus|nice.to.have|bonus)\b", clause, re.IGNORECASE)
                else required
                if re.search(r"\b(?:required|must|minimum|essential)\b", clause, re.IGNORECASE)
                else preferred
                if section == "PREFERRED"
                else required
                if section == "REQUIRED"
                else None
            )
            if target is not None:
                for skill in direct:
                    if any(_contains(clause, a) for a in SKILLS.get(skill, (skill,))) and skill not in target:
                        target.append(skill)
    families = [family for family, pattern in FAMILIES.items() if re.search(pattern, title, re.IGNORECASE)]
    duties = []
    for line in description.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if (
                any(re.search(pattern, sentence, re.IGNORECASE) for pattern in DUTIES)
                and sentence.strip() not in duties
            ):
                duties.append(sentence.strip())
    # A nonstandard title needs at least two substantive responsibilities plus a family signal in duties.
    if not families and len(duties) >= 2:
        families = [
            family for family, pattern in FAMILIES.items() if re.search(pattern, " ".join(duties), re.IGNORECASE)
        ]
    if re.search(EXCLUDED_TITLES, title, re.IGNORECASE):
        relevant, reason = False, "Teaching, faculty and postdoctoral openings are outside the requested families."
    elif not complete:
        relevant, reason = None, "Complete responsibilities are unavailable."
    elif families and duties:
        relevant, reason = (
            True,
            f"{', '.join(families)}; supported by {len(duties)} extracted responsibility clause(s).",
        )
    elif families:
        relevant, reason = None, "Title matches a family, but substantive responsibilities are not established."
    else:
        relevant, reason = False, "No approved role family with substantive relevant responsibilities was established."
    return RelevanceResult(
        relevant=relevant,
        families=families,
        responsibility_evidence=duties,
        direct_skills=direct,
        related_skills=related,
        required_skills=required,
        preferred_skills=preferred,
        missing_requested_skills=[skill for skill in requested if skill not in direct],
        original_vocabulary=original,
        summary=" ".join(duties[:2]),
        reason=reason,
        version=VERSION,
    )
