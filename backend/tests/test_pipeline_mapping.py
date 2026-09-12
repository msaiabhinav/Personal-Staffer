"""Pure mapping checks exercise the real ingestion adapters without a fake SQL database."""

from types import SimpleNamespace
from uuid import uuid4

from test_eligibility_corpus import CORPUS, NOW

from app.connectors.contracts import FieldEvidence, NormalizedJob, OpeningVerification
from app.eligibility import JobEvidence, evaluate_job
from app.jobs.pipeline import (
    _compare_namespaced,
    _complete_review,
    _finalize_evaluation,
    _map_evidence,
    _profile_rules,
    normalized_identity,
)


def normalized(**changes):
    bundle = JobEvidence.model_validate(CORPUS["cases"][0]["bundle"])
    data = {
        "source_type": "fixture",
        "tenant": "synthetic",
        "external_id": "REQ1",
        "employer_name": "Synthetic Employer",
        "title": bundle.title,
        "description_text": bundle.description,
        "description_complete": True,
        "source_url": bundle.source_url,
        "employer_url": "https://fixture.invalid/jobs/REQ1",
        "application_url": "https://fixture.invalid/jobs/REQ1/apply",
        "requisition_id": "REQ1",
        "country_codes": ["US"],
        "workplace_states": ["CT"],
        "employment_type": "FULL_TIME",
        "work_arrangement": "REMOTE",
        "publication": bundle.publication,
        "fetched_at": NOW,
        "synthetic": True,
    }
    data.update(changes)
    return NormalizedJob(**data)


def opening(**changes):
    data = {
        "status": "ACTIVE",
        "identity_match": True,
        "actionable": True,
        "application_url": "https://fixture.invalid/jobs/REQ1/apply",
        "final_url": "https://fixture.invalid/jobs/REQ1",
        "checked_at": NOW,
        "evidence_text": "Synthetic active opening identity and form",
    }
    data.update(changes)
    return OpeningVerification(**data)


def mapped(normal):
    return _map_evidence(
        normal,
        opening(),
        SimpleNamespace(id=uuid4(), first_seen=NOW),
        SimpleNamespace(id=uuid4()),
        uuid4(),
        normal.publication,
    )


def test_mapping_never_infers_entity_or_ct_remote_from_office():
    result = mapped(normalized())
    assert result.legal_entity_id is None and result.everify.status == "UNKNOWN"
    assert result.explicit_remote_states == []
    assert result.workplace_states == ["CT"]


def test_remote_state_mapping_uses_actual_state_fact_values():
    result = mapped(
        normalized(
            workplace_states=["NY"],
            field_evidence={
                "remote_eligible_states": [
                    FieldEvidence(
                        field_path="remoteEligibility",
                        value=["CT", "MA"],
                        source_url="https://fixture.invalid/job/REQ1",
                        observed_at=NOW,
                    )
                ]
            },
        )
    )
    assert result.explicit_remote_states == ["CT", "MA"]
    assert result.workplace_states == ["NY"]


def test_profile_changes_restrict_previously_eligible_role():
    evaluation = evaluate_job(JobEvidence.model_validate(CORPUS["cases"][0]["bundle"]), now=NOW, allow_synthetic=True)
    profile = SimpleNamespace(id=uuid4(), version=3, role_families=["Analytics engineering"])
    evaluation = _finalize_evaluation(_profile_rules(evaluation, profile, NOW))
    assert evaluation.decision == "INELIGIBLE"
    assert evaluation.rules[-1].reason_code == "PROFILE_FAMILY_NOT_SELECTED"
    assert evaluation.rules[-1].rule_version == "profile-3"


def test_repost_boolean_at_source_level_is_not_per_opening_evidence():
    assert not _complete_review({"repost_identity_reviewed": True}, content_hash="abc")
    assert not _complete_review(
        {
            "reviewer": "someone",
            "evidence_reference": "reference",
            "checked_at": NOW.isoformat(),
            "content_hash": "old",
        },
        content_hash="new",
    )
    assert not _complete_review(
        {"reviewer": "someone", "evidence_reference": "reference", "checked_at": "invalid", "content_hash": "same"},
        content_hash="same",
    )
    assert _complete_review(
        {
            "reviewer": "someone",
            "evidence_reference": "reference",
            "checked_at": NOW.isoformat(),
            "content_hash": "same",
        },
        content_hash="same",
    )


def test_unscoped_equal_requisition_is_not_a_cross_employer_merge():
    source = SimpleNamespace(connector_type="fixture", tenant="synthetic", employer_group_id=uuid4(), capabilities={})
    a = normalized_identity(source, normalized(), opening(), canonical_id=uuid4())
    b = a.model_copy(
        update={
            "canonical_id": str(uuid4()),
            "source": "other",
            "employer_destination": "https://fixture.invalid/other/REQ1",
        }
    )
    assert not a.requisition_verified
    assert _compare_namespaced(a, b, None, None).decision == "REVIEW"


def test_reviewed_common_namespace_can_merge_crossposts_but_different_namespaces_cannot():
    review = {
        "namespace": "synthetic-legal-ats-system",
        "reviewer": "human",
        "evidence_reference": "synthetic://map",
        "checked_at": NOW.isoformat(),
    }
    source = SimpleNamespace(
        connector_type="fixture",
        tenant="synthetic",
        employer_group_id=uuid4(),
        capabilities={"requisition_namespace": review},
    )
    a = normalized_identity(source, normalized(), opening(), canonical_id=uuid4())
    b = a.model_copy(
        update={
            "canonical_id": str(uuid4()),
            "source": "other",
            "employer_destination": "https://fixture.invalid/other/REQ1",
        }
    )
    assert _compare_namespaced(a, b, review["namespace"], review["namespace"]).decision == "SAME"
    assert _compare_namespaced(a, b, review["namespace"], "different-namespace").decision == "REVIEW"


def test_source_id_reused_with_different_requisition_needs_review():
    source = SimpleNamespace(connector_type="fixture", tenant="synthetic", employer_group_id=uuid4(), capabilities={})
    a = normalized_identity(source, normalized(), opening(), canonical_id=uuid4())
    b = a.model_copy(update={"canonical_id": str(uuid4()), "requisition_id": "REQ2"})
    assert _compare_namespaced(a, b, None, None).decision == "REVIEW"
    b = b.model_copy(update={"external_id": "DIFFERENT"})
    assert _compare_namespaced(a, b, None, None).decision == "DISTINCT"


def test_identity_review_cannot_transfer_to_reused_source_id_requisition():
    from app.jobs.pipeline import _identity_resolution_matches

    review = {
        "decision": "DISTINCT",
        "content_hash": "same-content",
        "source_identity": "source:fixture:synthetic:1",
        "requisition_id": "REQ1",
        "reviewer": "reviewer",
        "evidence_reference": "synthetic://evidence",
        "checked_at": NOW.isoformat(),
    }
    assert _identity_resolution_matches(
        review, content_hash="same-content", source_identity="source:fixture:synthetic:1", requisition_id="REQ1"
    )
    assert not _identity_resolution_matches(
        review, content_hash="same-content", source_identity="source:fixture:synthetic:1", requisition_id="REQ2"
    )
    assert not _identity_resolution_matches(
        review, content_hash="same-content", source_identity="source:fixture:other:1", requisition_id="REQ1"
    )
