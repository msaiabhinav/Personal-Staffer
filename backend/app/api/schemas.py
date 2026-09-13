from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Revision(Input):
    expected_revision: int = Field(ge=0)


class SaveInput(Revision):
    saved: bool


class DismissInput(Revision):
    dismissed: bool


class ApplyInput(Revision):
    applied_at: datetime | None = None

    @field_validator("applied_at")
    @classmethod
    def aware(cls, value):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("Timestamp must include a timezone")
        return value


Status = Literal["APPLIED", "ASSESSMENT", "INTERVIEWING", "OFFER", "REJECTED", "WITHDRAWN", "POSITION_CLOSED"]


class StatusInput(Revision):
    status: Status
    reason: str = Field(min_length=1, max_length=10000)
    effective_at: datetime | None = None
    _aware = field_validator("effective_at")(ApplyInput.aware.__func__)


class CorrectionInput(Revision):
    event_id: UUID
    reason: str = Field(min_length=1, max_length=10000)
    action: Literal["UNDO_APPLIED", "REVERT_EVENT"]


class ManualApplicationInput(Input):
    title: str = Field(min_length=1, max_length=1000)
    company: str = Field(min_length=1, max_length=1000)
    applied_at: datetime | None = None
    application_url: str | None = Field(default=None, max_length=4000)
    source_url: str | None = Field(default=None, max_length=4000)
    description: str | None = Field(default=None, max_length=250000)
    notes: str = Field(default="", max_length=50000)
    _aware = field_validator("applied_at")(ApplyInput.aware.__func__)

    @field_validator("application_url", "source_url")
    @classmethod
    def safe_url(cls, value):
        if value is None:
            return value
        split = urlsplit(value)
        if split.scheme not in ("https", "http") or not split.hostname or split.username or split.password:
            raise ValueError("Use an HTTP(S) job URL without embedded credentials")
        return value


class ApplicationPatch(Revision):
    notes: str | None = Field(default=None, max_length=50000)
    applied_at: datetime | None = None
    _aware = field_validator("applied_at")(ApplyInput.aware.__func__)


class ProfilePatch(Revision):
    role_families: list[str] | None = None
    skills: list[str] | None = None
    aliases: dict[str, list[str]] | None = None
    work_arrangements: list[Literal["REMOTE", "HYBRID", "ONSITE"]] | None = None


class WatchlistInput(Input):
    employer_group_id: UUID | None = None
    company_name: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def one_identity(self):
        if (self.employer_group_id is None) == (self.company_name is None):
            raise ValueError("Supply a registered employer group OR a company name for resolution")
        if self.company_name is not None:
            self.company_name = self.company_name.strip()
            if not self.company_name:
                raise ValueError("A company name is required")
        return self


class ReadInput(Input):
    read: bool = True


class DeleteNotificationsInput(Input):
    read_only: bool = False


class SyncOperation(Input):
    operation_id: str = Field(min_length=8, max_length=128)
    command: Literal["save", "apply", "correction", "notes", "status", "dismiss"]
    target_id: UUID
    payload: dict


class SyncOperations(Input):
    operations: list[SyncOperation] = Field(min_length=1, max_length=50)


class EmployerEvidenceInput(Input):
    entity_id: UUID
    status: Literal["CONFIRMED", "UNKNOWN", "CONFLICTING", "NO_LONGER_CONFIRMED"]
    legal_name_as_found: str = Field(min_length=1, max_length=255)
    source_reference: str = Field(min_length=1, max_length=4000)
    snapshot: str = Field(min_length=20, max_length=250000)
    checked_at: datetime
    verification_method: Literal["REVIEWED_OFFICIAL_SOURCE", "OFFICIAL_DATA_IMPORT"]
    synthetic: bool = False
    _aware = field_validator("checked_at")(ApplyInput.aware.__func__)


class AdminSearchInput(Input):
    source_registry_id: UUID
    query: str = Field(default="", max_length=1000)


class EmployerEntityInput(Input):
    employer_group_id: UUID
    legal_name: str = Field(min_length=1, max_length=255)
    jurisdiction: str | None = Field(default=None, max_length=255)
    source_reference: str = Field(min_length=1, max_length=4000)
    quoted_text: str = Field(min_length=20, max_length=250000)


class WatchlistResolveInput(Revision):
    employer_group_id: UUID
    source_reference: str = Field(min_length=1, max_length=4000)
    quoted_text: str = Field(min_length=20, max_length=250000)
