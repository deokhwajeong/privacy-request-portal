"""Persistence model.

Data minimization notes:
- Verification codes and requester tickets are stored only as hashes.
- The audit log never stores email addresses or free text from the requester; the
  data subject is referenced by a keyed hash (subject_ref).
- contact_email on a request is the only direct identifier and is redacted by the
  retention job once the request has been closed for the configured period.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Status(StrEnum):
    RECEIVED = "received"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    IN_PROGRESS = "in_progress"
    EXTENDED = "extended"
    FULFILLED = "fulfilled"
    DENIED = "denied"


class DenialReason(StrEnum):
    IDENTITY_NOT_VERIFIED = "identity_not_verified"
    VERIFICATION_NOT_COMPLETED = "verification_not_completed"
    LEGAL_EXEMPTION = "legal_exemption"
    MANIFESTLY_UNFOUNDED_OR_EXCESSIVE = "manifestly_unfounded_or_excessive"
    REQUEST_LIMIT_EXCEEDED = "request_limit_exceeded"
    WITHDRAWN_BY_REQUESTER = "withdrawn_by_requester"


class TaskStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    EXEMPT = "exempt"


class Account(Base):
    """Stand-in for the customer identity system that verification matches against."""

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    region: Mapped[str] = mapped_column(String(8))
    device_serial_last4: Mapped[str] = mapped_column(String(4))


class DsrRequest(Base):
    __tablename__ = "dsr_requests"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    regime: Mapped[str] = mapped_column(String(8), index=True)
    request_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), index=True)
    verification_tier: Mapped[str] = mapped_column(String(16))

    subject_ref: Mapped[str] = mapped_column(String(64), index=True)
    contact_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    claimed_account_id: Mapped[str] = mapped_column(String(40))
    matched_account_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ticket_hash: Mapped[str] = mapped_column(String(64))

    received_at: Mapped[datetime] = mapped_column(DateTime)
    ack_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ack_due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    original_due_at: Mapped[datetime] = mapped_column(DateTime)
    deadline_basis: Mapped[str] = mapped_column(String(120))
    extendable: Mapped[bool] = mapped_column(Boolean)
    extended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    extension_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)

    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    denial_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)
    denial_detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    challenges: Mapped[list[VerificationChallenge]] = relationship(
        back_populates="request", order_by="VerificationChallenge.id"
    )
    tasks: Mapped[list[FulfillmentTask]] = relationship(
        back_populates="request", order_by="FulfillmentTask.id"
    )

    @property
    def is_closed(self) -> bool:
        return self.status in (Status.FULFILLED, Status.DENIED)


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("dsr_requests.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    request: Mapped[DsrRequest] = relationship(back_populates="challenges")


class DownstreamSystem(Base):
    """A system of record that must act on verified requests (registered in the data map)."""

    __tablename__ = "downstream_systems"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    owner: Mapped[str] = mapped_column(String(120))
    operated_by: Mapped[str] = mapped_column(String(16), default="internal")  # internal | vendor
    data_categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    supports: Mapped[list[str]] = mapped_column(JSON, default=list)  # request types it must act on
    confirmation_sla_days: Mapped[int] = mapped_column(Integer, default=7)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class FulfillmentTask(Base):
    __tablename__ = "fulfillment_tasks"
    __table_args__ = (UniqueConstraint("request_id", "system_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(ForeignKey("dsr_requests.id"), index=True)
    system_key: Mapped[str] = mapped_column(ForeignKey("downstream_systems.key"))
    action: Mapped[str] = mapped_column(String(16))  # delete | export | correct | suppress
    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.PENDING)
    dispatched_at: Mapped[datetime] = mapped_column(DateTime)
    due_at: Mapped[datetime] = mapped_column(DateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmation_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)

    request: Mapped[DsrRequest] = relationship(back_populates="tasks")


class AuditEvent(Base):
    """Append-only, hash-chained audit log. Enforced by ORM guards and SQLite triggers."""

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    request_id: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(64))
    subject_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


for _op in ("UPDATE", "DELETE"):
    event.listen(
        AuditEvent.__table__,
        "after_create",
        DDL(
            f"CREATE TRIGGER IF NOT EXISTS audit_events_no_{_op.lower()} "
            f"BEFORE {_op} ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;"
        ).execute_if(dialect="sqlite"),
    )


class Purpose(Base):
    """A data-collection purpose from the consent and collection specification."""

    __tablename__ = "purposes"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    lawful_basis: Mapped[str] = mapped_column(String(32))  # consent | legitimate_interest | contract
    default_granted: Mapped[bool] = mapped_column(Boolean)
    halted: Mapped[bool] = mapped_column(Boolean, default=False)
    halt_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ConsentRecord(Base):
    __tablename__ = "consent_records"
    __table_args__ = (UniqueConstraint("account_id", "purpose_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(40), index=True)
    purpose_key: Mapped[str] = mapped_column(ForeignKey("purposes.key"))
    granted: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(40))  # settings_menu | first_run | dsr_opt_out | api
    spec_version: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class CollectionLog(Base):
    """Counts collection attempts and refusals. Stores no payload."""

    __tablename__ = "collection_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime)
    account_ref: Mapped[str] = mapped_column(String(64))
    purpose_key: Mapped[str] = mapped_column(String(40))
    accepted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
