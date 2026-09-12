from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.schemas import ApplyInput, ManualApplicationInput, SyncOperations
from app.applications.service import application_dict
from app.db.models import Application


def test_timestamps_require_explicit_timezone():
    with pytest.raises(ValidationError):
        ApplyInput(expected_revision=0, applied_at="2026-09-12T11:00:00")
    assert ApplyInput(expected_revision=0, applied_at="2026-09-12T11:00:00-04:00").applied_at.tzinfo


@pytest.mark.parametrize(
    "url", ["javascript:alert(1)", "file:///etc/passwd", "https://user:secret@example.com/jobs/one", "not a URL"]
)
def test_manual_application_rejects_executable_or_credential_urls(url):
    with pytest.raises(ValidationError):
        ManualApplicationInput(title="Analyst", company="Example", application_url=url)


def test_manual_application_no_resume_or_url_required():
    payload = ManualApplicationInput(title="Analyst", company="Example")
    assert payload.application_url is None
    with pytest.raises(ValidationError):
        ManualApplicationInput(title="Analyst", company="Example", resume="unexpected")


def test_offline_operation_batch_has_explicit_bound():
    with pytest.raises(ValidationError):
        SyncOperations(
            operations=[
                {
                    "operation_id": f"operation-{i}",
                    "command": "save",
                    "target_id": uuid4(),
                    "payload": {"saved": True, "expected_revision": 0},
                }
                for i in range(51)
            ]
        )


def test_awaiting_response_derived_only_from_applied():
    clock = datetime.now(UTC)
    app = Application(
        id=uuid4(), title="Analyst", company="Example", applied_at=clock - timedelta(hours=25), current_status="APPLIED"
    )
    assert application_dict(app, clock)["display_status"] == "AWAITING_RESPONSE"
    app.current_status = "INTERVIEWING"
    assert application_dict(app, clock)["display_status"] == "INTERVIEWING"


def test_all_state_routes_documented_and_authenticated():
    from app.main import app

    client = TestClient(app)
    for route in ["/jobs", "/saved-jobs", "/applications", "/notifications", "/dashboard", "/sync/changes"]:
        response = client.get("/api/v1" + route)
        assert response.status_code == 401, response.text
        assert response.json()["code"]
    schema = client.get("/api/v1/openapi.json").json()
    for path in [
        "/api/v1/jobs/{job_id}/saved",
        "/api/v1/jobs/{job_id}/apply",
        "/api/v1/applications/{application_id}/corrections",
        "/api/v1/sync/operations",
    ]:
        assert path in schema["paths"]


def test_official_employer_evidence_requires_entity_and_retained_proof():
    from app.api.admin import validate_employer_evidence
    from app.api.errors import DomainError
    from app.api.schemas import EmployerEvidenceInput
    from app.db.models import EmployerEntity

    clock = datetime.now(UTC)
    entity = EmployerEntity(id=uuid4(), legal_name="Example Payroll LLC")
    values = {
        "entity_id": entity.id,
        "status": "CONFIRMED",
        "legal_name_as_found": entity.legal_name,
        "source_reference": "https://www.e-verify.gov/employer-search",
        "snapshot": "Official reviewed record: Example Payroll LLC participated in E-Verify.",
        "checked_at": clock,
        "verification_method": "REVIEWED_OFFICIAL_SOURCE",
    }
    validate_employer_evidence(EmployerEvidenceInput(**values), entity, clock)
    for change in (
        {"legal_name_as_found": "Unrelated Parent Inc"},
        {"source_reference": "https://e-verify.gov.evil.example/record"},
        {"snapshot": "A brand is known but its payroll entity is not."},
        {"synthetic": True},
    ):
        with pytest.raises(DomainError):
            validate_employer_evidence(EmployerEvidenceInput(**{**values, **change}), entity, clock)


def test_watchlist_name_is_pending_request_and_identity_is_unambiguous():
    from app.api.schemas import WatchlistInput

    assert WatchlistInput(company_name="  Example Startup  ").company_name == "Example Startup"
    with pytest.raises(ValidationError):
        WatchlistInput(company_name=" ", employer_group_id=None)
    with pytest.raises(ValidationError):
        WatchlistInput(company_name="Example", employer_group_id=uuid4())
