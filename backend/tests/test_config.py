import pytest
from pydantic import ValidationError

from app.config.settings import Settings


def test_optional_config_states_and_no_synthetic_production():
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
