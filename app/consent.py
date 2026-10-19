"""Consent state and the collection gate.

Collection is allowed only when all of these hold:
1. the purpose exists in the specification (unknown purpose = refuse),
2. the purpose is not halted program-wide (kill switch for a spec or vendor issue),
3. the account's effective choice for the purpose is "granted".

Effective choice = the account's explicit record if present, else the purpose default.
Consent-based purposes default to not granted, so silence never means yes.
Refusals are counted (no payload stored) so a halt is provable from the log.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, clock
from app.models import CollectionLog, ConsentRecord, Purpose

SPEC_VERSION = "1.2"
SALE_SHARE = "sale_share"


@dataclass
class GateDecision:
    accepted: bool
    reason: str


def effective(db: Session, account_id: str, purpose: Purpose) -> tuple[bool, str]:
    rec = db.execute(
        select(ConsentRecord).where(
            ConsentRecord.account_id == account_id, ConsentRecord.purpose_key == purpose.key
        )
    ).scalar_one_or_none()
    if rec is not None:
        return rec.granted, rec.source
    return purpose.default_granted, "default"


def set_choice(
    db: Session,
    account_id: str,
    purpose: Purpose,
    granted: bool,
    *,
    source: str,
    actor: str,
    request_id: str | None = None,
) -> ConsentRecord:
    rec = db.execute(
        select(ConsentRecord).where(
            ConsentRecord.account_id == account_id, ConsentRecord.purpose_key == purpose.key
        )
    ).scalar_one_or_none()
    now = clock.now()
    if rec is None:
        rec = ConsentRecord(account_id=account_id, purpose_key=purpose.key)
        db.add(rec)
    rec.granted = granted
    rec.source = source
    rec.spec_version = SPEC_VERSION
    rec.updated_at = now
    audit.record(
        db,
        "consent.changed",
        actor=actor,
        request_id=request_id,
        subject=audit.subject_ref("account:" + account_id),
        details={"purpose": purpose.key, "granted": granted, "source": source, "spec_version": SPEC_VERSION},
    )
    return rec


def apply_opt_out(db: Session, account_id: str, *, request_id: str, actor: str) -> None:
    purpose = db.get(Purpose, SALE_SHARE)
    if purpose is not None:
        set_choice(db, account_id, purpose, False, source="dsr_opt_out", actor=actor, request_id=request_id)


def gate(db: Session, account_id: str, purpose_key: str) -> GateDecision:
    purpose = db.get(Purpose, purpose_key)
    if purpose is None:
        decision = GateDecision(False, "unknown_purpose")
    elif purpose.halted:
        decision = GateDecision(False, "purpose_halted")
    else:
        granted, _ = effective(db, account_id, purpose)
        decision = GateDecision(granted, "granted" if granted else "not_granted")
    db.add(
        CollectionLog(
            at=clock.now(),
            account_ref=audit.subject_ref("account:" + account_id),
            purpose_key=purpose_key[:40],
            accepted=decision.accepted,
            reason=decision.reason,
        )
    )
    return decision


def halt(db: Session, purpose: Purpose, reason: str, actor: str) -> None:
    purpose.halted = True
    purpose.halt_reason = reason
    audit.record(db, "collection.halted", actor=actor, details={"purpose": purpose.key, "reason": reason})


def resume(db: Session, purpose: Purpose, actor: str) -> None:
    purpose.halted = False
    purpose.halt_reason = None
    audit.record(db, "collection.resumed", actor=actor, details={"purpose": purpose.key})
