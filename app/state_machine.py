"""Request lifecycle. Every status change goes through transition(), which audits it.

    received -> verifying -> verified -> in_progress -> fulfilled
         \\           \\           \\            \\
          +-> verified  +-> denied   +-> extended  +-> extended -> in_progress | fulfilled | denied
          |  (no verification         +-> denied    +-> denied
          |   required: opt-out)
          +-> denied

fulfilled and denied are terminal. A request is extended at most once.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app import audit, clock
from app.models import DsrRequest, Status

TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.RECEIVED: frozenset({Status.VERIFYING, Status.VERIFIED, Status.DENIED}),
    Status.VERIFYING: frozenset({Status.VERIFIED, Status.DENIED}),
    Status.VERIFIED: frozenset({Status.IN_PROGRESS, Status.EXTENDED, Status.DENIED}),
    Status.IN_PROGRESS: frozenset({Status.FULFILLED, Status.EXTENDED, Status.DENIED}),
    Status.EXTENDED: frozenset({Status.IN_PROGRESS, Status.FULFILLED, Status.DENIED}),
    Status.FULFILLED: frozenset(),
    Status.DENIED: frozenset(),
}

TERMINAL = frozenset({Status.FULFILLED, Status.DENIED})


class InvalidTransition(Exception):
    def __init__(self, current: str, target: str, why: str | None = None) -> None:
        self.current, self.target = current, target
        super().__init__(why or f"cannot move request from {current} to {target}")


def can_transition(current: str, target: str) -> bool:
    return Status(target) in TRANSITIONS[Status(current)]


def transition(
    db: Session, req: DsrRequest, target: Status, *, actor: str, details: dict | None = None
) -> None:
    if not can_transition(req.status, target):
        raise InvalidTransition(req.status, target)
    if target is Status.EXTENDED and req.extended_at is not None:
        raise InvalidTransition(req.status, target, "request has already been extended once")
    previous = req.status
    req.status = target
    now = clock.now()
    if target is Status.VERIFIED:
        req.verified_at = now
    elif target is Status.IN_PROGRESS and req.started_at is None:
        req.started_at = now
    elif target in TERMINAL:
        req.closed_at = now
    audit.record(
        db,
        "request.status_changed",
        actor=actor,
        request_id=req.id,
        subject=req.subject_ref,
        details={"from": previous, "to": str(target), **(details or {})},
    )
