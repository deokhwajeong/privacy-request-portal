"""Consent choices and the collection gate.

Device and app clients call /v1/consent and /v1/collect within an authenticated
session (omitted in this reference). Program-wide halts are staff actions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import consent
from app.deps import db_session, staff_actor
from app.models import CollectionLog, Purpose
from app.schemas import CollectIn, ConsentIn, ConsentItem, HaltIn

router = APIRouter(prefix="/v1", tags=["consent and collection"])


def _purpose(db: Session, key: str) -> Purpose:
    p = db.get(Purpose, key)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown purpose {key!r}")
    return p


def _item(db: Session, account_id: str, p: Purpose) -> ConsentItem:
    granted, source = consent.effective(db, account_id, p)
    return ConsentItem(
        purpose=p.key, granted=granted, source=source, halted=p.halted, collecting=granted and not p.halted
    )


@router.get("/purposes")
def list_purposes(db: Session = Depends(db_session)) -> list[dict]:
    return [
        {
            "key": p.key,
            "description": p.description,
            "lawful_basis": p.lawful_basis,
            "default_granted": p.default_granted,
            "halted": p.halted,
            "halt_reason": p.halt_reason,
        }
        for p in db.execute(select(Purpose).order_by(Purpose.key)).scalars()
    ]


@router.get("/consent/{account_id}", response_model=list[ConsentItem])
def get_consent(account_id: str, db: Session = Depends(db_session)) -> list[ConsentItem]:
    return [_item(db, account_id, p) for p in db.execute(select(Purpose).order_by(Purpose.key)).scalars()]


@router.put("/consent/{account_id}/{purpose_key}", response_model=ConsentItem)
def set_consent(
    account_id: str, purpose_key: str, body: ConsentIn, db: Session = Depends(db_session)
) -> ConsentItem:
    p = _purpose(db, purpose_key)
    consent.set_choice(db, account_id, p, body.granted, source=body.source, actor="account")
    db.commit()
    return _item(db, account_id, p)


@router.post("/collect")
def collect(body: CollectIn, db: Session = Depends(db_session)):
    """Clients call this before sending any event. 202 = send; 409 = do not collect."""
    decision = consent.gate(db, body.account_id, body.purpose)
    db.commit()
    code = status.HTTP_202_ACCEPTED if decision.accepted else status.HTTP_409_CONFLICT
    return JSONResponse({"accepted": decision.accepted, "reason": decision.reason}, status_code=code)


@router.post("/purposes/{purpose_key}/halt")
def halt(
    purpose_key: str, body: HaltIn, db: Session = Depends(db_session), actor: str = Depends(staff_actor)
):
    p = _purpose(db, purpose_key)
    consent.halt(db, p, body.reason, actor)
    db.commit()
    return {"purpose": p.key, "halted": True}


@router.post("/purposes/{purpose_key}/resume")
def resume(purpose_key: str, db: Session = Depends(db_session), actor: str = Depends(staff_actor)):
    p = _purpose(db, purpose_key)
    consent.resume(db, p, actor)
    db.commit()
    return {"purpose": p.key, "halted": False}


@router.get("/collection/stats")
def collection_stats(db: Session = Depends(db_session), _actor: str = Depends(staff_actor)) -> list[dict]:
    """Accepted and refused collection attempts per purpose: the evidence that a halt took effect."""
    rows = db.execute(
        select(CollectionLog.purpose_key, CollectionLog.reason, func.count())
        .group_by(CollectionLog.purpose_key, CollectionLog.reason)
        .order_by(CollectionLog.purpose_key)
    ).all()
    out: dict[str, dict] = {}
    for purpose, reason, n in rows:
        out.setdefault(purpose, {"purpose": purpose, "accepted": 0, "refused": {}})
        if reason == "granted":
            out[purpose]["accepted"] += n
        else:
            out[purpose]["refused"][reason] = n
    return list(out.values())
