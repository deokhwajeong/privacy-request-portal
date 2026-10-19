from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.deadlines import Regime, RequestType
from app.models import DenialReason


class RequestIn(BaseModel):
    regime: Regime
    request_type: RequestType
    email: EmailStr
    account_id: str = Field(min_length=3, max_length=40)
    channel: str = Field(default="web_form", pattern=r"^(web_form|tv_settings|support_agent|email)$")


class RequestCreated(BaseModel):
    request_id: str
    ticket: str = Field(description="Shown once. Required to verify and to check status.")
    status: str
    due_date: str
    next_step: str


class VerifyIn(BaseModel):
    ticket: str
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    account_attribute: str | None = Field(
        default=None, max_length=8, description="Last 4 of a registered device serial (high tier only)"
    )


class TicketIn(BaseModel):
    ticket: str


class VerifyOut(BaseModel):
    outcome: str
    status: str
    attempts_remaining: int


class PublicStatus(BaseModel):
    request_id: str
    status: str
    due_date: str
    extended: bool


class ExtendIn(BaseModel):
    reason: str = Field(min_length=10, max_length=300)


class DenyIn(BaseModel):
    reason: DenialReason
    detail: str = Field(min_length=5, max_length=300)


class ConfirmIn(BaseModel):
    confirmation_ref: str = Field(min_length=3, max_length=80)


class FailIn(BaseModel):
    detail: str = Field(min_length=3, max_length=300)


class ExemptIn(BaseModel):
    legal_basis: str = Field(min_length=10, max_length=300)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    system_key: str
    action: str
    status: str
    dispatched_at: datetime
    due_at: datetime
    resolved_at: datetime | None
    confirmation_ref: str | None
    detail: str | None
    attempts: int


class RequestOut(BaseModel):
    """Staff view. Contact email is masked; staff tooling never needs the full address."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    regime: str
    request_type: str
    status: str
    verification_tier: str
    contact_email_masked: str | None
    claimed_account_id: str
    received_at: datetime
    ack_sent_at: datetime | None
    due_at: datetime
    original_due_at: datetime
    deadline_basis: str
    extendable: bool
    extended_at: datetime | None
    extension_reason: str | None
    verified_at: datetime | None
    started_at: datetime | None
    closed_at: datetime | None
    denial_reason: str | None
    denial_detail: str | None
    redacted_at: datetime | None
    sla: str
    tasks: list[TaskOut]


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    at: datetime
    request_id: str | None
    actor: str
    action: str
    subject_ref: str | None
    details: dict
    prev_hash: str
    hash: str


class SystemIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9-]{3,40}$")
    name: str
    owner: str
    operated_by: str = Field(default="internal", pattern=r"^(internal|vendor)$")
    data_categories: list[str] = []
    supports: list[RequestType]
    confirmation_sla_days: int = Field(default=7, ge=1, le=30)


class SystemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    owner: str
    operated_by: str
    data_categories: list[str]
    supports: list[str]
    confirmation_sla_days: int
    active: bool


class ConsentIn(BaseModel):
    granted: bool
    source: str = Field(default="settings_menu", pattern=r"^(settings_menu|first_run|api)$")


class ConsentItem(BaseModel):
    purpose: str
    granted: bool
    source: str
    halted: bool
    collecting: bool


class CollectIn(BaseModel):
    account_id: str
    purpose: str
    event_type: str = Field(max_length=40)


class HaltIn(BaseModel):
    reason: str = Field(min_length=5, max_length=200)
