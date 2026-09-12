import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import Settings

INTEGRATION_ENV = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_REDIRECT_URI",
    "GMAIL_REDIRECT_URI",
    "OWNER_ALLOWED_EMAIL",
    "TOKEN_ENCRYPTION_KEY",
    "FCM_CREDENTIALS_FILE",
    "FCM_PROJECT_ID",
    "PEOPLE_SEARCH_PROVIDER",
    "PEOPLE_SEARCH_API_KEY",
    "USAJOBS_API_KEY",
    "USAJOBS_USER_AGENT",
)


def test_optional_config_states_and_no_synthetic_production(monkeypatch):
    # The suite may run inside a live-local container that carries real integration values.
    for key in INTEGRATION_ENV:
        monkeypatch.delenv(key, raising=False)
    config = Settings(_env_file=None)
    assert all(config.integration_state(x) == "NOT_CONFIGURED" for x in ["google", "gmail", "people", "fcm", "usajobs"])
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="production", demo_mode=True)


@pytest.mark.parametrize(
    "values",
    [
        {"daily_job_limit": 51},
        {"company_daily_limit": 3},
        {"cycle_days": 31},
        {"max_posting_age_hours": 73},
        {"database_url": "sqlite:///bad.db"},
        {"token_encryption_key": "not-a-key"},
    ],
)
def test_unsafe_configuration_refused(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


ENV_EXAMPLE = Path(__file__).resolve().parents[2] / ".env.example"


def test_documented_env_example_loads(monkeypatch):
    # Regression: Literal[32]/Literal[72] rejected the string values every dotenv file supplies,
    # so the README's `Copy-Item .env.example .env` path failed before the first migration.
    for key in list(os.environ):
        if key.upper() in {"CYCLE_DAYS", "MAX_POSTING_AGE_HOURS", "APP_ENV", "DEMO_MODE"}:
            monkeypatch.delenv(key, raising=False)
    config = Settings(_env_file=ENV_EXAMPLE)
    assert (config.cycle_days, config.max_posting_age_hours) == (32, 72)
    assert config.app_env == "local" and config.demo_mode is False


def test_policy_constants_accept_env_strings_and_refuse_other_values(monkeypatch):
    monkeypatch.setenv("CYCLE_DAYS", "32")
    monkeypatch.setenv("MAX_POSTING_AGE_HOURS", "72")
    config = Settings(_env_file=None)
    assert (config.cycle_days, config.max_posting_age_hours) == (32, 72)
    monkeypatch.setenv("CYCLE_DAYS", "33")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
