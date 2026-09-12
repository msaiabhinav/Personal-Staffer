"""Read-only offline regression replay. Never inserts demo jobs or employer approvals."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .engine import evaluate_job
from .models import JobEvidence


def replay_corpus(path: str | Path) -> dict:
    corpus = json.loads(Path(path).read_text())
    if not corpus.get("synthetic_only"):
        raise ValueError("this replay accepts the explicit synthetic corpus only")
    now = datetime.fromisoformat(corpus["frozen_evaluation_time"])
    rows = []
    for case in corpus["cases"]:
        evidence = JobEvidence.model_validate(case["bundle"])
        if not case.get("synthetic") or not evidence.synthetic or not evidence.everify.synthetic:
            raise ValueError("every synthetic fixture requires explicit synthetic labels")
        evaluation = evaluate_job(evidence, now=now, allow_synthetic=True)
        rule_decisions = {r.rule: r.decision.value for r in evaluation.rules}
        rule_matches = all(
            rule_decisions.get(name) == expected for name, expected in case.get("expected_rules", {}).items()
        )
        rows.append(
            {
                "id": case["id"],
                "split": case["split"],
                "template_group": case["template_group"],
                "expected": case["expected_decision"],
                "actual": evaluation.decision.value,
                "correct": evaluation.decision == case["expected_decision"] and rule_matches,
                "expected_rules": case.get("expected_rules", {}),
                "actual_rules": rule_decisions,
                "reasons": evaluation.reason_codes,
            }
        )
    metrics = {}
    for split in ("regression", "heldout", "all"):
        items = [row for row in rows if split == "all" or row["split"] == split]
        true_eligible = sum(row["expected"] == row["actual"] == "ELIGIBLE" for row in items)
        expected_eligible = sum(row["expected"] == "ELIGIBLE" for row in items)
        actual_eligible = sum(row["actual"] == "ELIGIBLE" for row in items)
        metrics[split] = {
            "cases": len(items),
            "correct": sum(row["correct"] for row in items),
            "outcomes": dict(Counter(row["actual"] for row in items)),
            "hard_rule_false_accepts": sum(
                row["expected"] != "ELIGIBLE" and row["actual"] == "ELIGIBLE" for row in items
            ),
            "eligible_recall": true_eligible / expected_eligible if expected_eligible else None,
            "eligible_precision": true_eligible / actual_eligible if actual_eligible else None,
            "review_rate": sum(row["actual"] == "NEEDS_REVIEW" for row in items) / len(items) if items else None,
        }
    per_rule = {}
    for row in rows:
        for name, expected in row["expected_rules"].items():
            summary = per_rule.setdefault(
                name, {"annotated_cases": 0, "correct": 0, "expected_fails": 0, "detected_fails": 0, "actual_fails": 0}
            )
            summary["annotated_cases"] += 1
            summary["correct"] += expected == row["actual_rules"][name]
            summary["expected_fails"] += expected == "FAIL"
            summary["actual_fails"] += row["actual_rules"][name] == "FAIL"
            summary["detected_fails"] += expected == row["actual_rules"][name] == "FAIL"
    for value in per_rule.values():
        value["fail_precision"] = value["detected_fails"] / value["actual_fails"] if value["actual_fails"] else None
        value["fail_recall"] = value["detected_fails"] / value["expected_fails"] if value["expected_fails"] else None
    return {
        "corpus_version": corpus["corpus_version"],
        "synthetic_only": True,
        "frozen_evaluation_time": corpus["frozen_evaluation_time"],
        "metrics": metrics,
        "per_rule_labeled_metrics": per_rule,
        "failures": [row for row in rows if not row["correct"]],
        "live_source_coverage": "NOT_VERIFIED_BY_SYNTHETIC_REPLAY",
        "limitations": "Finite synthetic tests do not establish production accuracy; real evidence bundles and multi-day audit remain required.",
    }
