"""Full synthetic HTTP path and demo isolation on real PostgreSQL migrations."""

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import test_database_core
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Application, EVerifyEvidence, InitialDelivery, User, UserJobState
from app.db.session import get_session

pg_engine = test_database_core.pg_engine
pytestmark = pytest.mark.postgres


@pytest.fixture
def demo_client(pg_engine, monkeypatch):
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("DEMO_MODE", "true")
    get_settings.cache_clear()
    from app.main import app

    def database():
        with Session(pg_engine) as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    previous = app.dependency_overrides.get(get_session)
    app.dependency_overrides[get_session] = database
    with TestClient(app) as client:
        yield client
    if previous is None:
        app.dependency_overrides.pop(get_session, None)
    else:
        app.dependency_overrides[get_session] = previous
    get_settings.cache_clear()


def test_demo_http_workflow_and_repeated_smoke_are_durable(demo_client, pg_engine):
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_demo.py"
    spec = importlib.util.spec_from_file_location("staffer_demo_smoke", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    first = module.run_workflow(demo_client)
    repeated = module.run_workflow(demo_client)
    assert first["application_id"] == repeated["application_id"]
    login = demo_client.post("/api/v1/auth/demo", json={"device_id": str(uuid4()), "platform": "WINDOWS"}).json()
    headers = {"Authorization": "Bearer " + login["access_token"]}
    page = demo_client.post("/api/v1/sync/snapshot?limit=100", headers=headers).json()
    items = list(page["items"])
    while page["has_more"]:
        page = demo_client.get(
            f"/api/v1/sync/snapshot/{page['snapshot_id']}?offset={page['next_offset']}&limit=100", headers=headers
        ).json()
        items.extend(page["items"])
    groups = [item["data"] for item in items if item["entity_type"] == "employer_group"]
    assert any(group["canonical_name"].startswith("DEMO") for group in groups)
    # The Windows client's default feed query must be accepted over real HTTP (query strings are text).
    for hours in ("24", "48", "72"):
        feed = demo_client.get(f"/api/v1/jobs?scope=today&posted_within_hours={hours}", headers=headers)
        assert feed.status_code == 200, feed.text
    priority = demo_client.get("/api/v1/jobs?scope=priority&posted_within_hours=72", headers=headers)
    assert priority.status_code == 200 and len(priority.json()["items"]) == 2
    rejected = demo_client.get("/api/v1/jobs?scope=today&posted_within_hours=36", headers=headers)
    assert rejected.status_code == 422
    # The specification's priority employers are watched from the first demo sign-in.
    watchlist = demo_client.get("/api/v1/watchlist?limit=100", headers=headers).json()["items"]
    watched = {entry["company"] for entry in watchlist}
    assert {"Thermo Fisher Scientific", "Henry Ford Health", "Tata Consultancy Services"} <= watched
    assert all(entry["resolution_state"] == "REGISTERED" for entry in watchlist)
    assert len(watchlist) == 12
    evaluations = [item["data"] for item in items if item["entity_type"] == "job_evaluation"]
    assert evaluations and evaluations[0]["evidence"]["rules"]
    snapshots = [item["data"] for item in items if item["entity_type"] == "job_snapshot"]
    assert snapshots[0]["structured_fields"]["job_evidence"]["synthetic"] is True
    with Session(pg_engine) as session:
        assert session.scalar(select(func.count()).select_from(Application)) == 1
        assert session.scalar(select(func.count()).select_from(InitialDelivery)) == 2
        assert (
            session.scalar(select(func.count()).select_from(UserJobState).where(UserJobState.is_saved.is_(True))) == 1
        )
        evidence = session.scalar(select(EVerifyEvidence))
        assert evidence.synthetic is True


def test_demo_refuses_database_with_real_owner(demo_client, pg_engine):
    with Session(pg_engine) as session, session.begin():
        session.add(User(google_subject="real-owner-subject", verified_email="owner@example.test"))
    result = demo_client.post("/api/v1/auth/demo", json={"device_id": str(uuid4()), "platform": "WINDOWS"})
    assert result.status_code == 409
    assert result.json()["code"] == "DEMO_ISOLATION_REQUIRED"


def test_demo_route_unavailable_when_demo_disabled(demo_client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    get_settings.cache_clear()
    result = demo_client.post("/api/v1/auth/demo", json={"device_id": str(uuid4()), "platform": "WINDOWS"})
    assert result.status_code == 404


def test_notification_bulk_actions_over_http_are_idempotent(demo_client):
    login = demo_client.post("/api/v1/auth/demo", json={"device_id": str(uuid4()), "platform": "WINDOWS"}).json()
    headers = {"Authorization": "Bearer " + login["access_token"]}
    before = demo_client.get("/api/v1/notifications?limit=100", headers=headers).json()
    assert before["unread_count"] > 0
    key = {**headers, "Idempotency-Key": f"read-all-{uuid4()}"}
    first = demo_client.post("/api/v1/notifications/read-all", headers=key)
    assert first.status_code == 200, first.text
    assert first.json()["updated"] == before["unread_count"]
    assert demo_client.post("/api/v1/notifications/read-all", headers=key).json() == first.json()  # replay
    assert demo_client.get("/api/v1/notifications/unread-count", headers=headers).json()["unread_count"] == 0
    key = {**headers, "Idempotency-Key": f"delete-all-{uuid4()}"}
    removed = demo_client.post("/api/v1/notifications/delete-all", json={"read_only": True}, headers=key)
    assert removed.status_code == 200, removed.text
    assert removed.json()["deleted"] == len(before["items"])
    assert demo_client.get("/api/v1/notifications", headers=headers).json()["items"] == []
    missing = demo_client.post("/api/v1/notifications/delete-all", json={}, headers=headers)
    assert missing.status_code == 422  # Idempotency-Key is mandatory for every mutation.


def test_dashboard_reports_activity_and_attention_counts(demo_client):
    path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_demo.py"
    spec = importlib.util.spec_from_file_location("staffer_demo_smoke_dashboard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.run_workflow(demo_client)
    login = demo_client.post("/api/v1/auth/demo", json={"device_id": str(uuid4()), "platform": "WINDOWS"}).json()
    headers = {"Authorization": "Bearer " + login["access_token"]}
    dashboard = demo_client.get("/api/v1/dashboard", headers=headers).json()
    assert dashboard["total"] == 1
    assert dashboard["watchlist_companies"] == 12
    assert dashboard["open_reviews"] >= 0 and dashboard["unread_notifications"] >= 0
    recent = dashboard["recent_events"]
    assert recent and recent[0]["application_id"] == result["application_id"]
    assert recent[0]["status"] == "APPLIED" and recent[0]["actor"] == "USER"
    assert {"company", "title", "effective_at"} <= set(recent[0])
    # Reading the dashboard never mutates state: unread count matches the inbox endpoint.
    unread = demo_client.get("/api/v1/notifications/unread-count", headers=headers).json()["unread_count"]
    assert dashboard["unread_notifications"] == unread
