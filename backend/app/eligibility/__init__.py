from .models import (
    Evaluation,
    EVerifyEvidence,
    EvidenceRef,
    Fact,
    FactState,
    FinalDecision,
    JobEvidence,
    OpeningEvidence,
    Policy,
    PublicationEvidence,
    RelevanceResult,
    RuleDecision,
    RuleResult,
    Salary,
)


def __getattr__(name):
    # Relevance imports the neutral evidence models. Delay evaluator imports so
    # importing relevance before eligibility is safe in a fresh process.
    if name in {"evaluate_job", "priority_reasons", "salary_band"}:
        from . import engine

        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EVerifyEvidence",
    "Evaluation",
    "EvidenceRef",
    "Fact",
    "FactState",
    "FinalDecision",
    "JobEvidence",
    "OpeningEvidence",
    "Policy",
    "PublicationEvidence",
    "RelevanceResult",
    "RuleDecision",
    "RuleResult",
    "Salary",
    "evaluate_job",
    "priority_reasons",
    "salary_band",
]
