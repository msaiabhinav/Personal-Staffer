from fastapi.testclient import TestClient

from app.main import app


def test_public_health_and_version_report_real_state():
    with TestClient(app) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "alive"}
        result = client.get("/api/v1/version").json()
        assert result["release_artifacts"] == []
        assert result["demo_mode"] is False


def test_unauthenticated_private_routes_are_rejected_without_database():
    with TestClient(app) as client:
        for path in ["/me", "/jobs", "/applications", "/notifications", "/gmail/status", "/people"]:
            response = client.get("/api/v1" + path)
            assert response.status_code == 401, (path, response.text)
            assert set(response.json()) == {"code", "user_message", "retryable", "request_id", "details"}


def test_input_validation_never_echoes_secrets():
    with TestClient(app) as client:
        marker = "private-value-that-must-not-appear"
        response = client.post("/api/v1/auth/login/start", json={"challenge": marker, "platform": marker})
        assert response.status_code == 422
        assert marker not in response.text


def test_openapi_contract_paths_and_no_claimed_release():
    schema = app.openapi()
    assert all(path.startswith("/api/v1/") for path in schema["paths"])
    for path in [
        "/jobs/{job_id}/apply",
        "/jobs/{job_id}/saved",
        "/applications/{application_id}/corrections",
        "/sync/operations",
    ]:
        assert "/api/v1" + path in schema["paths"]
