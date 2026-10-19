"""Append-only, hash-chained audit log.

Each event stores sha256(prev_hash + canonical JSON of the event). Altering or
removing any past row breaks every hash after it, which /v1/audit/verify detects.
Updates and deletes are blocked at two layers: an ORM guard here and database
triggers (see models.py). In production the chain head would also be anchored
periodically to external write-once storage so a full rewrite is detectable.

What goes in: request id, actor, action, reason codes, system keys, status names.
What never goes in: email addresses, names, codes, tickets, free text from requesters.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app import clock
from app.config import get_settings
from app.models import AuditEvent

GENESIS = "0" * 64

# Keys whose values could carry personal data. Refused outright rather than silently dropped,
# so a developer finds out in tests, not in an audit.
_FORBIDDEN_DETAIL_KEYS = {"email", "contact_email", "name", "code", "ticket", "address", "phone"}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def subject_ref(identifier: str) -> str:
    """Keyed hash (HMAC-SHA256) of a normalized identifier.

    A plain hash of an email is reversible by dictionary attack; a keyed hash is not,
    without the key. This lets the log link all events for one person without storing who.
    """
    key = get_settings().pseudonym_key.encode()
    return hmac.new(key, normalize_email(identifier).encode(), hashlib.sha256).hexdigest()


def _canonical(e: AuditEvent) -> bytes:
    body = {
        "seq": e.seq,
        "at": e.at.isoformat(timespec="seconds"),
        "request_id": e.request_id,
        "actor": e.actor,
        "action": e.action,
        "subject_ref": e.subject_ref,
        "details": e.details or {},
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def compute_hash(prev_hash: str, e: AuditEvent) -> str:
    return hashlib.sha256(prev_hash.encode() + _canonical(e)).hexdigest()


def record(
    db: Session,
    action: str,
    *,
    actor: str,
    request_id: str | None = None,
    subject: str | None = None,
    details: dict | None = None,
    at: datetime | None = None,
) -> AuditEvent:
    """Append one event. Caller commits as part of the same unit of work as the change."""
    details = details or {}
    leaked = _FORBIDDEN_DETAIL_KEYS.intersection(details)
    if leaked:
        raise ValueError(f"audit details must not contain personal data fields: {sorted(leaked)}")

    db.flush()
    last = db.execute(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(1)).scalar_one_or_none()
    prev_hash = last.hash if last else GENESIS
    ev = AuditEvent(
        seq=(last.seq + 1) if last else 1,
        at=(at or clock.now()).replace(microsecond=0),
        request_id=request_id,
        actor=actor,
        action=action,
        subject_ref=subject,
        details=details,
        prev_hash=prev_hash,
    )
    ev.hash = compute_hash(prev_hash, ev)
    db.add(ev)
    db.flush()
    return ev


@dataclass
class ChainReport:
    ok: bool
    events: int
    head: str
    first_bad_seq: int | None = None
    problem: str | None = None


def verify_chain(db: Session) -> ChainReport:
    prev = GENESIS
    count = 0
    expected_seq = 1
    for ev in db.execute(select(AuditEvent).order_by(AuditEvent.seq)).scalars():
        count += 1
        if ev.seq != expected_seq:
            return ChainReport(False, count, prev, ev.seq, "sequence gap (event removed)")
        if ev.prev_hash != prev:
            return ChainReport(False, count, prev, ev.seq, "prev_hash does not match previous event")
        if compute_hash(prev, ev) != ev.hash:
            return ChainReport(False, count, prev, ev.seq, "event content does not match its hash")
        prev = ev.hash
        expected_seq += 1
    return ChainReport(True, count, prev)


def _block_mutation(_mapper, _conn, target: AuditEvent) -> None:
    raise PermissionError(f"audit event {target.seq} is append-only")


event.listen(AuditEvent, "before_update", _block_mutation)
event.listen(AuditEvent, "before_delete", _block_mutation)
