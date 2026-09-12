from contextlib import nullcontext
from unittest.mock import Mock

import pytest
import redis
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.db import readiness, session
from app.main import app


@pytest.mark.parametrize("heads,ready", [(["previous_revision"], False), ([], False), (["shipped_head"], True)])
def test_readiness_requires_exact_migration_and_redis(monkeypatch, heads, ready):
    connection = Mock()
    connection.execute.return_value.scalars.return_value = heads
    engine = Mock()
    engine.connect.return_value = nullcontext(connection)
    broker = Mock()
    monkeypatch.setattr(session, "get_engine", lambda: engine)
    monkeypatch.setattr(readiness, "expected_heads", lambda: frozenset({"shipped_head"}))
    monkeypatch.setattr(redis.Redis, "from_url", lambda *args, **kwargs: broker)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == (200 if ready else 503)
    assert broker.ping.call_count == int(ready)


def test_database_failure_does_not_leak_connection_details(monkeypatch):
    engine = Mock()
    engine.connect.side_effect = OperationalError("secret-host", {}, Exception("private-password"))
    monkeypatch.setattr(session, "get_engine", lambda: engine)
    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


def test_shipped_migration_path_resolves_without_working_directory(monkeypatch, tmp_path):
    readiness.expected_heads.cache_clear()
    monkeypatch.chdir(tmp_path)
    assert readiness.expected_heads()
