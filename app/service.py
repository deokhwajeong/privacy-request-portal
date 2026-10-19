"""Request workflow: intake, verification, fan-out, extension, denial, housekeeping.

Functions here own the unit of work: they mutate state, append audit events, and
leave the commit to the caller (the API layer commits once per request).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, clock, consent, verification
from app.config import get_settings
from app.deadlines import (
    Regime,
    RequestType,
    acknowledgement_due,
    end_of_day,
    extended_deadline,
    initial_deadline,
)
from app.models import (
    DenialReason,
    DownstreamSystem,
    DsrRequest,
    FulfillmentTask,
    Status,
    TaskStatus,
)
from app.notifier import outbox
from app.state_machine import InvalidTransition, transition
from app.verification import Outcome, Tier

ACTION_BY_TYPE = {
    RequestType.DELETION: "delete",
    RequestType.ACCESS: "export",
    RequestType.CORRECTION: "correct",
    RequestType.OPT_OUT: "suppress",
}
SYSTEM = "system"


class WorkflowError(Exception):
    """A request that is valid HTTP but not allowed by policy (maps to 409)."""


def _new_request_id(received: datetime) -> str:
    return f"DSR-{received:%y%m}-{secrets.token_hex(3).upper()}"


# --------------------------------------------------------------------------- intake


def submit(
    db: Session,
    *,
    regime: Regime,
    request_type: RequestType,
    contact_email: str,
    account_id: str,
    channel: str = "web_form",
) -> tuple[DsrRequest, str]:
    """Create a request and run the automatic intake steps. Returns (request, ticket)."""
    now = clock.now()
    received = now.date()
    deadline = initial_deadline(regime, request_type, received)
    ack = acknowledgement_due(regime, request_type, received)
    tier = verification.TIER_BY_TYPE[request_type]
    ticket = secrets.token_urlsafe(18)

    req = DsrRequest(
        id=_new_request_id(now),
        regime=regime,
        request_type=request_type,
        status=Status.RECEIVED,
        verification_tier=tier,
        subject_ref=audit.subject_ref(contact_email),
        contact_email=audit.normalize_email(contact_email),
        claimed_account_id=account_id.strip(),
        received_at=now,
        ack_due_at=end_of_day(ack) if ack else None,
        due_at=end_of_day(deadline.due),
        original_due_at=end_of_day(deadline.due),
        deadline_basis=deadline.basis,
        extendable=deadline.extendable,
        ticket_hash="",
    )
    req.ticket_hash = verification.hash_ticket(req.id, ticket)
    db.add(req)
    audit.record(
        db,
        "request.received",
        actor=f"requester:{channel}",
        request_id=req.id,
        subject=req.subject_ref,
        details={
            "regime": str(regime),
            "type": str(request_type),
            "tier": str(tier),
            "due": deadline.due.isoformat(),
            "basis": deadline.basis,
        },
    )

    outbox.send(req.contact_email, req.id, "acknowledgement", f"We received request {req.id}.")
    req.ack_sent_at = now
    audit.record(db, "notice.acknowledgement_sent", actor=SYSTEM, request_id=req.id, subject=req.subject_ref)

    account = verification.find_matching_account(db, req.claimed_account_id, contact_email)
    if tier is Tier.ACCOUNT_MATCH:
        if account:
            req.matched_account_id = account.account_id
            transition(db, req, Status.VERIFIED, actor=SYSTEM, details={"method": "account_match"})
        else:
            _deny(db, req, DenialReason.IDENTITY_NOT_VERIFIED, "Could not locate a matching account.", SYSTEM)
        return req, ticket

    transition(db, req, Status.VERIFYING, actor=SYSTEM, details={"tier": str(tier)})
    _, code = verification.issue_challenge(db, req, account, actor=SYSTEM)
    if code:
        outbox.send(
            account.email, req.id, "verification_code", "Your verification code is enclosed.", code=code
        )
    return req, ticket


def verify(db: Session, req: DsrRequest, code: str, extra_attribute: str | None) -> verification.VerifyResult:
    if req.status != Status.VERIFYING:
        raise WorkflowError(f"request is {req.status}, not awaiting verification")
    result = verification.check(db, req, code, extra_attribute, actor="requester")
    if result.outcome is Outcome.VERIFIED:
        req.matched_account_id = req.claimed_account_id
        transition(
            db, req, Status.VERIFIED, actor="requester", details={"method": str(req.verification_tier)}
        )
    elif result.outcome is Outcome.LOCKED:
        _deny(
            db,
            req,
            DenialReason.IDENTITY_NOT_VERIFIED,
            "Maximum verification attempts reached.",
            SYSTEM,
        )
    return result


def resend_code(db: Session, req: DsrRequest) -> None:
    if req.status != Status.VERIFYING:
        raise WorkflowError(f"request is {req.status}, not awaiting verification")
    if len(req.challenges) >= get_settings().max_challenges:
        raise WorkflowError("maximum number of verification codes issued; contact support")
    account = verification.find_matching_account(db, req.claimed_account_id, req.contact_email or "")
    _, code = verification.issue_challenge(db, req, account, actor="requester")
    if code and account:
        outbox.send(
            account.email, req.id, "verification_code", "Your verification code is enclosed.", code=code
        )


# --------------------------------------------------------------------------- fulfillment


def start(db: Session, req: DsrRequest, actor: str) -> list[FulfillmentTask]:
    """Begin fulfillment: fan out to every registered system that must act on this type."""
    if req.status not in (Status.VERIFIED, Status.EXTENDED) or req.tasks:
        raise WorkflowError(f"request {req.id} cannot be started from {req.status}")
    rtype = RequestType(req.request_type)
    transition(db, req, Status.IN_PROGRESS, actor=actor)

    if rtype is RequestType.OPT_OUT and req.matched_account_id:
        consent.apply_opt_out(db, req.matched_account_id, request_id=req.id, actor=actor)

    systems = (
        db.execute(select(DownstreamSystem).where(DownstreamSystem.active).order_by(DownstreamSystem.key))
        .scalars()
        .all()
    )
    now = clock.now()
    tasks: list[FulfillmentTask] = []
    for system in systems:
        if rtype.value not in system.supports:
            continue
        task = FulfillmentTask(
            request_id=req.id,
            system_key=system.key,
            action=ACTION_BY_TYPE[rtype],
            status=TaskStatus.PENDING,
            dispatched_at=now,
            due_at=min(now + timedelta(days=system.confirmation_sla_days), req.due_at),
        )
        db.add(task)
        req.tasks.append(task)
        tasks.append(task)
        audit.record(
            db,
            "fanout.dispatched",
            actor=actor,
            request_id=req.id,
            subject=req.subject_ref,
            details={"system": system.key, "action": task.action, "operated_by": system.operated_by},
        )
    db.flush()
    _maybe_complete(db, req)
    return tasks


def confirm_task(db: Session, task: FulfillmentTask, confirmation_ref: str, actor: str) -> None:
    if task.status != TaskStatus.PENDING:
        raise WorkflowError(f"task {task.id} is {task.status}; only pending tasks can be confirmed")
    task.status = TaskStatus.CONFIRMED
    task.confirmation_ref = confirmation_ref
    task.resolved_at = clock.now()
    audit.record(
        db,
        "fanout.confirmed",
        actor=actor,
        request_id=task.request_id,
        subject=task.request.subject_ref,
        details={"system": task.system_key, "action": task.action, "confirmation_ref": confirmation_ref},
    )
    _maybe_complete(db, task.request)


def fail_task(db: Session, task: FulfillmentTask, detail: str, actor: str) -> None:
    if task.status != TaskStatus.PENDING:
        raise WorkflowError(f"task {task.id} is {task.status}; only pending tasks can fail")
    task.status = TaskStatus.FAILED
    task.detail = detail
    audit.record(
        db,
        "fanout.failed",
        actor=actor,
        request_id=task.request_id,
        subject=task.request.subject_ref,
        details={"system": task.system_key, "error": detail[:120]},
    )


def retry_task(db: Session, task: FulfillmentTask, actor: str) -> None:
    if task.status != TaskStatus.FAILED:
        raise WorkflowError(f"task {task.id} is {task.status}; only failed tasks can be retried")
    task.status = TaskStatus.PENDING
    task.attempts += 1
    task.dispatched_at = clock.now()
    audit.record(
        db,
        "fanout.retried",
        actor=actor,
        request_id=task.request_id,
        subject=task.request.subject_ref,
        details={"system": task.system_key, "attempt": task.attempts},
    )


def exempt_task(db: Session, task: FulfillmentTask, legal_basis: str, actor: str) -> None:
    """Record that a system retains data under an exemption (e.g. legal obligation)."""
    if task.status not in (TaskStatus.PENDING, TaskStatus.FAILED):
        raise WorkflowError(f"task {task.id} is already {task.status}")
    task.status = TaskStatus.EXEMPT
    task.detail = legal_basis
    task.resolved_at = clock.now()
    audit.record(
        db,
        "fanout.exempted",
        actor=actor,
        request_id=task.request_id,
        subject=task.request.subject_ref,
        details={"system": task.system_key, "legal_basis": legal_basis[:160]},
    )
    _maybe_complete(db, task.request)


def _maybe_complete(db: Session, req: DsrRequest) -> None:
    if req.status not in (Status.IN_PROGRESS, Status.EXTENDED):
        return
    if any(t.status in (TaskStatus.PENDING, TaskStatus.FAILED) for t in req.tasks):
        return
    confirmed = sum(1 for t in req.tasks if t.status == TaskStatus.CONFIRMED)
    exempt = sum(1 for t in req.tasks if t.status == TaskStatus.EXEMPT)
    transition(
        db,
        req,
        Status.FULFILLED,
        actor=SYSTEM,
        details={"systems_confirmed": confirmed, "systems_exempt": exempt},
    )
    if req.contact_email:
        outbox.send(req.contact_email, req.id, "completion", f"Request {req.id} is complete.")
    audit.record(db, "notice.completion_sent", actor=SYSTEM, request_id=req.id, subject=req.subject_ref)


# --------------------------------------------------------------------------- extension and denial


def extend(db: Session, req: DsrRequest, reason: str, actor: str) -> None:
    if not req.extendable:
        raise WorkflowError(f"{req.deadline_basis}: no extension available for this request type")
    if clock.now() > req.due_at:
        # Both regimes require notice of the extension within the original period.
        raise WorkflowError("extension must be noticed before the original deadline")
    previous = req.due_at
    new_due = extended_deadline(Regime(req.regime), req.received_at.date(), req.original_due_at.date())
    try:
        transition(
            db,
            req,
            Status.EXTENDED,
            actor=actor,
            details={
                "previous_due": previous.date().isoformat(),
                "new_due": new_due.isoformat(),
                "reason": reason,
            },
        )
    except InvalidTransition as exc:
        raise WorkflowError(str(exc)) from exc
    req.due_at = end_of_day(new_due)
    req.extended_at = clock.now()
    req.extension_reason = reason
    if req.contact_email:
        outbox.send(
            req.contact_email, req.id, "extension_notice", f"Extended to {new_due.isoformat()}: {reason}"
        )
    audit.record(db, "notice.extension_sent", actor=SYSTEM, request_id=req.id, subject=req.subject_ref)


def deny(db: Session, req: DsrRequest, reason: DenialReason, detail: str, actor: str) -> None:
    try:
        _deny(db, req, reason, detail, actor)
    except InvalidTransition as exc:
        raise WorkflowError(str(exc)) from exc


def _deny(db: Session, req: DsrRequest, reason: DenialReason, detail: str, actor: str) -> None:
    transition(db, req, Status.DENIED, actor=actor, details={"reason": str(reason)})
    req.denial_reason = reason
    req.denial_detail = detail
    for task in req.tasks:
        if task.status in (TaskStatus.PENDING, TaskStatus.FAILED):
            task.status = TaskStatus.EXEMPT
            task.detail = "request denied before completion"
            task.resolved_at = clock.now()
    # GDPR Art. 12(4): when not taking action, inform the data subject of the reasons and of
    # the right to lodge a complaint with a supervisory authority and seek a judicial remedy.
    if req.contact_email:
        outbox.send(req.contact_email, req.id, "denial_notice", f"Request {req.id} closed: {reason}.")
    audit.record(
        db,
        "notice.denial_sent",
        actor=SYSTEM,
        request_id=req.id,
        subject=req.subject_ref,
        details={"reason": str(reason)},
    )


# --------------------------------------------------------------------------- housekeeping


def sweep(db: Session) -> dict:
    """Close requests whose identity verification was never completed."""
    window = timedelta(days=get_settings().verification_window_days)
    cutoff = clock.now() - window
    stale = (
        db.execute(
            select(DsrRequest).where(DsrRequest.status == Status.VERIFYING, DsrRequest.received_at < cutoff)
        )
        .scalars()
        .all()
    )
    for req in stale:
        _deny(
            db,
            req,
            DenialReason.VERIFICATION_NOT_COMPLETED,
            f"Verification not completed within {window.days} days.",
            "system:sweep",
        )
    return {"closed_unverified": [r.id for r in stale]}


def redact_closed_contacts(db: Session) -> dict:
    """Drop contact email from requests closed longer than the contact retention period.

    The remaining record (dates, type, outcome, basis for denial) is what record-keeping
    rules ask for (11 CCR 7101 sets a 24-month minimum for CCPA request records) and it
    carries no direct identifier.
    """
    cutoff = clock.now() - timedelta(days=get_settings().contact_retention_days)
    due = (
        db.execute(
            select(DsrRequest).where(
                DsrRequest.closed_at.is_not(None),
                DsrRequest.closed_at < cutoff,
                DsrRequest.contact_email.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    for req in due:
        req.contact_email = None
        req.redacted_at = clock.now()
        audit.record(db, "request.contact_redacted", actor="system:retention", request_id=req.id)
    return {"redacted": [r.id for r in due]}
