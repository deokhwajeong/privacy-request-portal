"""Requester-facing endpoints. No staff credentials; the ticket authenticates the requester."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import service, verification
from app.deps import db_session, get_request
from app.models import DsrRequest, Status
from app.schemas import PublicStatus, RequestCreated, RequestIn, TicketIn, VerifyIn, VerifyOut

router = APIRouter(prefix="/v1/requests", tags=["requester"])

NEXT_STEP = {
    Status.VERIFYING: "If the details match an account, a 6-digit code was sent to the email on file.",
    Status.VERIFIED: "Identity confirmed. Your request is queued for fulfillment.",
    Status.DENIED: "We could not process this request. A notice with the reason was sent.",
}


def _require_ticket(req: DsrRequest, ticket: str) -> None:
    # Same 404 as an unknown id, so ids cannot be probed without the ticket.
    if not verification.ticket_matches(req, ticket):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")


@router.post("", response_model=RequestCreated, status_code=status.HTTP_201_CREATED)
def submit_request(body: RequestIn, db: Session = Depends(db_session)) -> RequestCreated:
    req, ticket = service.submit(
        db,
        regime=body.regime,
        request_type=body.request_type,
        contact_email=body.email,
        account_id=body.account_id,
        channel=body.channel,
    )
    db.commit()
    # A denied opt-out returns the same shape; the reason goes out by notice, not in the response.
    return RequestCreated(
        request_id=req.id,
        ticket=ticket,
        status=req.status,
        due_date=req.due_at.date().isoformat(),
        next_step=NEXT_STEP.get(Status(req.status), ""),
    )


@router.post("/{request_id}/verify", response_model=VerifyOut)
def verify_identity(
    body: VerifyIn, req: DsrRequest = Depends(get_request), db: Session = Depends(db_session)
) -> VerifyOut:
    _require_ticket(req, body.ticket)
    try:
        result = service.verify(db, req, body.code, body.account_attribute)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    db.commit()
    return VerifyOut(outcome=result.outcome, status=req.status, attempts_remaining=result.attempts_remaining)


@router.post("/{request_id}/resend-code", status_code=status.HTTP_202_ACCEPTED)
def resend_code(body: TicketIn, req: DsrRequest = Depends(get_request), db: Session = Depends(db_session)):
    _require_ticket(req, body.ticket)
    try:
        service.resend_code(db, req)
    except service.WorkflowError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    db.commit()
    return {"status": req.status, "next_step": NEXT_STEP[Status.VERIFYING]}


@router.post("/{request_id}/status", response_model=PublicStatus)
def request_status(body: TicketIn, req: DsrRequest = Depends(get_request)) -> PublicStatus:
    # POST so the ticket never lands in URLs, proxies, or access logs.
    _require_ticket(req, body.ticket)
    return PublicStatus(
        request_id=req.id,
        status=req.status,
        due_date=req.due_at.date().isoformat(),
        extended=req.extended_at is not None,
    )
