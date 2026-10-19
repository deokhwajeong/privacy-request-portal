"""Privacy operations endpoints: queue, case handling, downstream confirmations, audit."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, service, sla
from app.deps import db_session, get_request, get_task, staff_actor
from app.models import AuditEvent, DownstreamSystem, DsrRequest, FulfillmentTask
from app.schemas import (
    AuditOut,
    ConfirmIn,
    DenyIn,
    ExemptIn,
    ExtendIn,
    FailIn,
    RequestOut,
    SystemIn,
    SystemOut,
    TaskOut,
)

router = APIRouter(prefix="/v1", tags=["privacy operations"])


def mask_email(email: str | None) -> str | None:
    if not email:
        return None
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"


def to_out(req: DsrRequest) -> RequestOut:
    data = {c: getattr(req, c) for c in RequestOut.model_fields if hasattr(req, c)}
    data["contact_email_masked"] = mask_email(req.contact_email)
    data["sla"] = sla.classify(req)
    data["tasks"] = [TaskOut.model_validate(t) for t in req.tasks]
    return RequestOut(**data)


def _conflict(fn, *args) -> None:
    try:
        fn(*args)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))


@router.get("/requests", response_model=list[RequestOut])
def list_requests(
    status_: str | None = Query(default=None, alias="status"),
    regime: str | None = None,
    db: Session = Depends(db_session),
    _actor: str = Depends(staff_actor),
) -> list[RequestOut]:
    q = select(DsrRequest).order_by(DsrRequest.due_at)
    if status_:
        q = q.where(DsrRequest.status == status_)
    if regime:
        q = q.where(DsrRequest.regime == regime)
    return [to_out(r) for r in db.execute(q).scalars()]


@router.get("/requests/{request_id}", response_model=RequestOut)
def get_one(req: DsrRequest = Depends(get_request), _actor: str = Depends(staff_actor)) -> RequestOut:
    return to_out(req)


@router.get("/requests/{request_id}/audit", response_model=list[AuditOut])
def request_audit(
    req: DsrRequest = Depends(get_request),
    db: Session = Depends(db_session),
    _actor: str = Depends(staff_actor),
) -> list[AuditEvent]:
    q = select(AuditEvent).where(AuditEvent.request_id == req.id).order_by(AuditEvent.seq)
    return list(db.execute(q).scalars())


@router.post("/requests/{request_id}/start", response_model=RequestOut)
def start(
    req: DsrRequest = Depends(get_request),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> RequestOut:
    _conflict(service.start, db, req, actor)
    db.commit()
    return to_out(req)


@router.post("/requests/{request_id}/extend", response_model=RequestOut)
def extend(
    body: ExtendIn,
    req: DsrRequest = Depends(get_request),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> RequestOut:
    _conflict(service.extend, db, req, body.reason, actor)
    db.commit()
    return to_out(req)


@router.post("/requests/{request_id}/deny", response_model=RequestOut)
def deny(
    body: DenyIn,
    req: DsrRequest = Depends(get_request),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> RequestOut:
    _conflict(service.deny, db, req, body.reason, body.detail, actor)
    db.commit()
    return to_out(req)


# ---------------------------------------------------------------- downstream tasks
# In production each downstream system calls these with its own credential, so
# the actor is the system, not a person. The shared staff key stands in here.


@router.post("/tasks/{task_id}/confirm", response_model=TaskOut)
def confirm(
    body: ConfirmIn,
    task: FulfillmentTask = Depends(get_task),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> FulfillmentTask:
    _conflict(service.confirm_task, db, task, body.confirmation_ref, actor)
    db.commit()
    return task


@router.post("/tasks/{task_id}/fail", response_model=TaskOut)
def fail(
    body: FailIn,
    task: FulfillmentTask = Depends(get_task),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> FulfillmentTask:
    _conflict(service.fail_task, db, task, body.detail, actor)
    db.commit()
    return task


@router.post("/tasks/{task_id}/retry", response_model=TaskOut)
def retry(
    task: FulfillmentTask = Depends(get_task),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> FulfillmentTask:
    _conflict(service.retry_task, db, task, actor)
    db.commit()
    return task


@router.post("/tasks/{task_id}/exempt", response_model=TaskOut)
def exempt(
    body: ExemptIn,
    task: FulfillmentTask = Depends(get_task),
    db: Session = Depends(db_session),
    actor: str = Depends(staff_actor),
) -> FulfillmentTask:
    _conflict(service.exempt_task, db, task, body.legal_basis, actor)
    db.commit()
    return task


# ---------------------------------------------------------------- registry, SLA, audit, housekeeping


@router.get("/systems", response_model=list[SystemOut])
def list_systems(db: Session = Depends(db_session), _actor: str = Depends(staff_actor)):
    return list(db.execute(select(DownstreamSystem).order_by(DownstreamSystem.key)).scalars())


@router.post("/systems", response_model=SystemOut, status_code=status.HTTP_201_CREATED)
def register_system(body: SystemIn, db: Session = Depends(db_session), actor: str = Depends(staff_actor)):
    if db.get(DownstreamSystem, body.key):
        raise HTTPException(status.HTTP_409_CONFLICT, "system already registered")
    system = DownstreamSystem(**{**body.model_dump(), "supports": [str(s) for s in body.supports]})
    db.add(system)
    audit.record(
        db, "system.registered", actor=actor, details={"system": body.key, "supports": system.supports}
    )
    db.commit()
    return system


@router.get("/sla/dashboard")
def sla_dashboard(db: Session = Depends(db_session), _actor: str = Depends(staff_actor)) -> dict:
    return sla.dashboard(db)


@router.get("/audit/verify")
def audit_verify(db: Session = Depends(db_session), _actor: str = Depends(staff_actor)) -> dict:
    report = audit.verify_chain(db)
    return report.__dict__


@router.post("/admin/sweep")
def admin_sweep(db: Session = Depends(db_session), _actor: str = Depends(staff_actor)) -> dict:
    result = service.sweep(db)
    db.commit()
    return result


@router.post("/admin/retention")
def admin_retention(db: Session = Depends(db_session), _actor: str = Depends(staff_actor)) -> dict:
    result = service.redact_closed_contacts(db)
    db.commit()
    return result
