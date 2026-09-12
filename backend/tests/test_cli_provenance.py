"""Import/registration provenance validation before any database or network side effect."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.cli import parser, validate_pool_evidence, validate_real_source_bundle


@pytest.mark.parametrize(
    "bundle",
    [
        {},
        {"synthetic": True},
        {"synthetic": "false"},
        {"provenance": {"synthetic": None}},
        {"provenance": {"synthetic": True}, "synthetic": False},
    ],
)
def test_real_fixture_import_never_assumes_missing_synthetic_flag_is_real(bundle):
    with pytest.raises(ValueError):
        validate_real_source_bundle(bundle)


def test_real_fixture_import_requires_positive_provenance_and_time():
    bundle = {"provenance": {"synthetic": False, "observed_at": "2026-09-12T12:00:00+00:00"}}
    assert validate_real_source_bundle(bundle) == bundle["provenance"]
    with pytest.raises(ValueError):
        validate_real_source_bundle({"provenance": {"synthetic": False}})


def test_unreviewed_pool_name_cannot_be_verified_flag():
    assert validate_pool_evidence("Example", ["NYC"], None) == ([], {})
    with pytest.raises(SystemExit):
        parser().parse_args(
            [
                "register-source",
                "--type",
                "ashby",
                "--tenant",
                "example",
                "--employer",
                "Example",
                "--pool",
                "UNIVERSITY_VERIFIED",
            ]
        )


def test_startup_pool_proof_keeps_company_location_separate_from_job(tmp_path):
    file = tmp_path / "pools.json"
    evidence = {
        "NYC": {
            "source_reference": "https://example.test/about",
            "quoted_text": "Example has its headquarters in New York City.",
            "reviewer": "Operator",
            "checked_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "company_location_kind": "HEADQUARTERS",
            "location": "New York City",
            "startup_basis": "Reviewed current startup directory listing",
        }
    }
    file.write_text(json.dumps(evidence))
    verified, retained = validate_pool_evidence("Example", ["NYC"], file)
    assert verified == ["NYC_VERIFIED"]
    assert retained == evidence
    del evidence["NYC"]["company_location_kind"]
    file.write_text(json.dumps(evidence))
    with pytest.raises(ValueError):
        validate_pool_evidence("Example", ["NYC"], file)
