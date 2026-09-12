"""Focused regressions for concrete security review findings; no external services."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import AuthRequestLimiter, RequestSafetyMiddleware

spec = importlib.util.spec_from_file_location(
    "staffer_backup", Path(__file__).resolve().parents[2] / "scripts/backup.py"
)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_configuration_secrets_are_hidden_in_repr_and_validation_errors():
    secret = "private-secret-do-not-print"
    settings = Settings(_env_file=None, google_client_secret=secret, people_search_api_key=secret)
    assert secret not in repr(settings)
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, google_client_secret=secret, public_base_url="https://backend.test/path")
    assert secret not in str(error.value)


@pytest.mark.parametrize(
    "origin",
    [
        "https://backend.test/path",
        "https://user:secret@backend.test",
        "https://backend.test?q=a",
        "https://backend.test#fragment",
        "file:///backend",
    ],
)
def test_public_origin_cannot_smuggle_paths_or_credentials(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, public_base_url=origin)


@pytest.mark.parametrize(
    "callback",
    [
        "http://staffer.example/callback",
        "https://evil.example/callback",
        "https://staffer.example/callback?x=1",
        "https://staffer.example/callback#secret",
    ],
)
def test_nonlocal_oauth_callbacks_are_bound_to_configured_https_origin(callback):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            public_base_url="https://staffer.example",
            database_url="postgresql://owner:secret@db/staffer",
            google_client_id="test",
            google_client_secret="secret",
            google_redirect_uri=callback,
            owner_allowed_email="owner@example.com",
            token_encryption_key=Fernet.generate_key().decode(),
        )


def test_auth_limiter_has_peer_and_global_bounds_and_expires():
    clock = [100.0]
    limiter = AuthRequestLimiter(capacity=2, clock=lambda: clock[0])
    assert limiter.allow("peer-a") and limiter.allow("peer-a")
    assert not limiter.allow("peer-a")
    assert all(limiter.allow(f"peer-{number}") for number in range(6))
    assert not limiter.allow("new-peer")
    clock[0] += 61
    assert limiter.allow("peer-a")


def guarded_app(*, max_bytes=64, auth_capacity=2):
    app = FastAPI()
    app.add_middleware(RequestSafetyMiddleware, max_bytes=max_bytes, auth_capacity=auth_capacity)
    calls = []

    @app.post("/api/v1/auth/login/start")
    async def consume(request: Request):
        data = await request.body()
        calls.append(data)
        return {"bytes": len(data)}

    return TestClient(app), calls


def test_auth_rate_limit_cannot_be_evaded_with_forwarding_headers():
    client, calls = guarded_app()
    for number in range(2):
        assert (
            client.post(
                "/api/v1/auth/login/start", headers={"X-Forwarded-For": f"192.0.2.{number}"}, content=b"x"
            ).status_code
            == 200
        )
    blocked = client.post("/api/v1/auth/login/start", headers={"X-Forwarded-For": "192.0.2.222"}, content=b"x")
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"
    assert len(calls) == 2


def test_declared_and_streamed_bodies_are_bounded_before_use():
    client, calls = guarded_app()
    assert client.post("/api/v1/auth/login/start", content=b"x" * 65).status_code == 413
    assert not calls
    response = client.post("/api/v1/auth/login/start", content=iter([b"x" * 40, b"y" * 40]))
    assert response.status_code == 413
    assert not calls


def test_backup_preserves_explicit_tls_and_ignores_ambient_target_overrides(monkeypatch):
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.200")
    monkeypatch.setenv("PGSERVICE", "wrong-target")
    monkeypatch.setenv("PGSSLMODE", "disable")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "private-secret")
    env = backup.database_environment(
        "postgresql+psycopg://owner:password@db.example/staffer?sslmode=verify-full&sslrootcert=%2Fsecure%2Fca.pem"
    )
    assert env["PGSSLMODE"] == "verify-full" and env["PGSSLROOTCERT"] == "/secure/ca.pem"
    assert env["PGHOST"] == "db.example"
    assert not {"PGHOSTADDR", "PGSERVICE", "GOOGLE_CLIENT_SECRET"} & env.keys()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://owner:pass@db/dbname%3Dstaffer%20host%3Dproduction_restore",
        "postgresql://owner:pass@db/postgresql%3A%2F%2Fproduction%2Fstaffer_restore",
        "postgresql://owner:pass@db/staffer_restore?host=production",
        "postgresql://owner:pass@db/staffer?sslmode=require&sslmode=disable",
        "postgresql://owner:pass@db/staffer?service=production",
        "postgresql://owner:pass%0Ainjected@db/staffer",
    ],
)
def test_backup_rejects_target_override_and_ambiguous_options(url):
    with pytest.raises(ValueError):
        backup.database_environment(url)


def test_restore_requires_independent_database_name_even_for_host_alias():
    source = "postgresql://owner:pass@db/staffer_restore"
    with pytest.raises(ValueError):
        backup.validate_restore_target(source, "postgresql://owner:pass@db-alias/staffer_restore")
    backup.validate_restore_target(source, "postgresql://owner:pass@db/new_restore")


def test_backup_password_uses_private_temporary_file_and_is_removed():
    with backup.protected_database_environment("postgresql://owner:p%3Ass@db/staffer") as env:
        path = Path(env["PGPASSFILE"])
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.read_text() == "db:5432:staffer:owner:p\\:ss\n"
        assert "PGPASSWORD" not in env and "DATABASE_URL" not in env
    assert not path.exists()


def test_backup_invokes_restic_command_exit_guard_without_plaintext_dump(monkeypatch):
    calls = []
    monkeypatch.setenv("DATABASE_URL", "postgresql://owner:password@db/staffer")
    monkeypatch.setenv("RESTIC_REPOSITORY", "s3:example.invalid/private")
    monkeypatch.setenv("RESTIC_PASSWORD_FILE", "/secure/restic")
    monkeypatch.setattr("sys.argv", ["backup.py", "backup"])

    def run(command, **kwargs):
        calls.append(command)
        if command[1] == "backup":
            assert "PGPASSWORD" not in kwargs["env"]
            assert Path(kwargs["env"]["PGPASSFILE"]).exists()
            assert kwargs["check"] is True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backup.subprocess, "run", run)
    backup.main()
    assert "--stdin-from-command" in calls[0] and "--stdin" not in calls[0]
    assert calls[0][-4:] == ["pg_dump", "--format=custom", "--no-owner", "--no-acl"]
    assert calls[1] == ["restic", "check"]
