"""Validated deployment configuration. Optional integrations fail independently."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False, hide_input_in_errors=True)
    app_env: Literal["local", "staging", "production"] = "local"
    public_base_url: str = "http://127.0.0.1:5555"
    database_url: str = Field(default="postgresql+psycopg://staffer:staffer-local@127.0.0.1:5432/staffer", repr=False)
    redis_url: str = Field(default="redis://127.0.0.1:6379/0", repr=False)
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    google_redirect_uri: str = ""
    gmail_redirect_uri: str = ""
    owner_allowed_email: str = ""
    owner_google_subject: str = ""
    token_encryption_key: str = Field(default="", repr=False)
    api_auth_requests_per_minute: int = Field(default=60, ge=10, le=240)
    access_token_minutes: int = Field(default=15, ge=1, le=30)
    refresh_token_days: int = Field(default=30, ge=1, le=30)
    fcm_credentials_file: str = ""
    fcm_project_id: str = ""
    people_search_provider: str = ""
    people_search_api_key: str = Field(default="", repr=False)
    people_daily_query_budget: int = Field(default=400, ge=0, le=10000)
    usajobs_api_key: str = Field(default="", repr=False)
    usajobs_user_agent: str = ""
    schedule_timezone: Literal["America/New_York"] = "America/New_York"
    daily_report_time: Literal["11:00"] = "11:00"
    daily_job_limit: int = Field(default=50, ge=1, le=50)
    company_daily_limit: int = Field(default=2, ge=1, le=2)
    # Hard policy: exactly 32 and 72. Bounded ints (not Literal) so the documented .env
    # string values "32"/"72" coerce while any other value is still refused.
    cycle_days: int = Field(default=32, ge=32, le=32)
    max_posting_age_hours: int = Field(default=72, ge=72, le=72)
    preferred_salary_usd: int = Field(default=80000, ge=0)
    everify_recheck_days: int = Field(default=30, ge=1, le=30)
    gmail_sync_interval_seconds: int = Field(default=300, ge=60)
    gmail_backfill_days: int = Field(default=30, ge=1, le=90)
    worker_concurrency: int = Field(default=2, ge=1, le=8)
    browser_concurrency: int = Field(default=1, ge=1, le=2)
    source_connect_timeout: int = Field(default=10, ge=1, le=30)
    source_request_timeout: int = Field(default=30, ge=1, le=60)
    raw_candidate_retention_days: int = Field(default=30, ge=1)
    backup_repository: str = ""
    demo_mode: bool = False

    @property
    def environment(self) -> str:
        return self.app_env

    @property
    def owner_google_email(self) -> str:
        return self.owner_allowed_email

    @property
    def people_search_key(self) -> str:
        return self.people_search_api_key

    @model_validator(mode="after")
    def validate_safety(self):
        if urlsplit(self.database_url).scheme not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("DATABASE_URL must use PostgreSQL")
        origin = urlsplit(self.public_base_url)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.path not in {"", "/"}
            or origin.query
            or origin.fragment
        ):
            raise ValueError("PUBLIC_BASE_URL must be an HTTP(S) origin")
        try:
            _ = origin.port
        except ValueError as exc:
            raise ValueError("PUBLIC_BASE_URL has an invalid port") from exc
        if self.token_encryption_key:
            try:
                Fernet(self.token_encryption_key.encode())
            except (ValueError, TypeError) as exc:
                raise ValueError("TOKEN_ENCRYPTION_KEY must be a Fernet key") from exc
        if self.app_env != "local":
            if self.demo_mode or origin.scheme != "https":
                raise ValueError("Nonlocal environments require HTTPS and prohibit demo mode")
            if not all(
                [
                    self.google_client_id,
                    self.google_client_secret,
                    self.google_redirect_uri,
                    self.owner_allowed_email,
                    self.token_encryption_key,
                ]
            ):
                raise ValueError(
                    "Nonlocal environments require explicit owner, OAuth and token encryption configuration"
                )
            if "staffer-local" in self.database_url:
                raise ValueError("Local database credentials cannot be used outside local development")
            for callback in [self.google_redirect_uri, self.gmail_redirect_uri]:
                if not callback:
                    continue
                parsed = urlsplit(callback)
                if (
                    parsed.scheme != "https"
                    or parsed.netloc.casefold() != origin.netloc.casefold()
                    or parsed.username
                    or parsed.password
                    or parsed.query
                    or parsed.fragment
                ):
                    raise ValueError(
                        "Nonlocal OAuth callbacks must use the configured HTTPS backend origin without query or fragment"
                    )
        return self

    def integration_state(self, name: str) -> str:
        values = {
            "google": [
                self.google_client_id,
                self.google_client_secret,
                self.google_redirect_uri,
                self.owner_allowed_email,
                self.token_encryption_key,
            ],
            "gmail": [
                self.google_client_id,
                self.google_client_secret,
                self.gmail_redirect_uri,
                self.token_encryption_key,
            ],
            "fcm": [self.fcm_credentials_file, self.fcm_project_id],
            "people": [self.people_search_provider, self.people_search_api_key],
            "usajobs": [self.usajobs_api_key, self.usajobs_user_agent],
        }
        return "CONFIGURED" if all(values[name]) else "NOT_CONFIGURED"


@lru_cache
def get_settings() -> Settings:
    return Settings()
