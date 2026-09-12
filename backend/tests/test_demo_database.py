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
    assert groups and groups[0]["canonical_name"].startswith("DEMO")
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
