from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import DsrRequest, FulfillmentTask


def db_session() -> Session:  # pragma: no cover - thin wrapper for clearer signatures
    yield from get_session()


def staff_actor(
    x_staff_key: str = Header(default=""),
    x_actor: str = Header(default="", max_length=80),
) -> str:
    """Staff endpoints require the shared key plus a named actor for the audit trail.

    Production replaces this with SSO and role-based access (intake analyst, privacy
    lead, system owner). The named actor requirement stays: no anonymous staff actions.
    """
    if not hmac.compare_digest(x_staff_key, get_settings().staff_api_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "staff credentials required")
    if not x_actor.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Actor header required for audit attribution")
    return f"staff:{x_actor.strip()}"


def get_request(request_id: str, db: Session = Depends(db_session)) -> DsrRequest:
    req = db.get(DsrRequest, request_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "request not found")
    return req


def get_task(task_id: int, db: Session = Depends(db_session)) -> FulfillmentTask:
    task = db.get(FulfillmentTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "task not found")
    return task
