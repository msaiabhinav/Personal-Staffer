"""Frozen, annotated synthetic corpus; no real source or employer claims."""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.eligibility import JobEvidence, evaluate_job

CORPUS_PATH = Path(__file__).parent / "fixtures" / "eligibility_synthetic_v1.json"
CORPUS = json.loads(CORPUS_PATH.read_text())
NOW = datetime.fromisoformat(CORPUS["frozen_evaluation_time"])


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda case: case["id"] + "-" + case["name"])
def test_annotated_evidence_bundle(case):
    job = JobEvidence.model_validate(case["bundle"])
    evaluation = evaluate_job(job, now=NOW, allow_synthetic=True)
    assert evaluation.decision == case["expected_decision"], evaluation.model_dump_json(indent=2)
    by_rule = {rule.rule: rule for rule in evaluation.rules}
    for name, decision in case["expected_rules"].items():
        assert by_rule[name].decision == decision
    assert evaluation.ruleset_version
    assert evaluation.synthetic
    assert case["label_rationale"]
    for rule in evaluation.rules:
        assert rule.reason_code and rule.rule_version and rule.evidence
    for fact in evaluation.facts:
        assert fact.extractor_version and fact.evidence
        for evidence in fact.evidence:
            assert evidence.snapshot_id == job.snapshot_id
            if evidence.text is not None:
                assert evidence.text == job.description[evidence.start : evidence.end]
            else:
                assert evidence.field_path


def test_heldout_is_reserved_by_template_group():
    assert len(CORPUS["cases"]) == 60
    regression = {c["template_group"] for c in CORPUS["cases"] if c["split"] == "regression"}
    heldout = {c["template_group"] for c in CORPUS["cases"] if c["split"] == "heldout"}
    assert regression.isdisjoint(heldout)
    assert sum(c["split"] == "heldout" for c in CORPUS["cases"]) == 12
    assert CORPUS["synthetic_only"]
    assert all(
        c["synthetic"] and c["bundle"]["synthetic"] and c["bundle"]["everify"]["synthetic"] for c in CORPUS["cases"]
    )


def test_synthetic_evidence_cannot_approve_production_delivery():
    job = JobEvidence.model_validate(CORPUS["cases"][0]["bundle"])
    evaluation = evaluate_job(job, now=NOW)
    assert evaluation.decision == "NEEDS_REVIEW"
    assert "SYNTHETIC_EVIDENCE_PROHIBITED" in evaluation.reason_codes


def test_false_accepts_recall_and_review_rate_are_measured():
    for split in ("regression", "heldout"):
        cases = [c for c in CORPUS["cases"] if c["split"] == split]
        results = [
            (c, evaluate_job(JobEvidence.model_validate(c["bundle"]), now=NOW, allow_synthetic=True)) for c in cases
        ]
        false_accepts = sum(c["expected_decision"] != "ELIGIBLE" and r.decision == "ELIGIBLE" for c, r in results)
        eligible_count = sum(c["expected_decision"] == "ELIGIBLE" for c, _ in results)
        true_accepts = sum(c["expected_decision"] == r.decision == "ELIGIBLE" for c, r in results)
        assert false_accepts == 0
        assert eligible_count > 0 and true_accepts / eligible_count == 1
        assert 0 < sum(r.decision == "NEEDS_REVIEW" for _, r in results) / len(results) < 1
