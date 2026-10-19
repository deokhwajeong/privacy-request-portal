"""Risk-based identity verification.

The degree of assurance scales with the harm a wrong match would cause:

| Tier          | Request types      | Factors                                                     |
|---------------|--------------------|-------------------------------------------------------------|
| account_match | opt_out            | contact email matches the account on file; no code          |
| standard      | correction         | one-time code sent to the email on file + account match     |
| high          | access, deletion   | code + account match + one more account attribute           |

Rationale: an opt-out can only reduce processing, so it should not be gated behind
friction (11 CCR 7026(d): a request to opt-out need not be a verifiable request).
Access discloses personal data to whoever passes, and deletion is irreversible,
so both get the highest tier (11 CCR 7060 to 7062 scale the required degree of
certainty with sensitivity and risk of harm; GDPR Art. 12(6) permits requesting
additional information where there are reasonable doubts about identity).

Anti-enumeration: intake responds identically whether or not the account matches.
When it does not match, a challenge is still created but its code is never sent,
so the requester cannot tell which input was wrong and attempts are counted the same.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app import audit, clock
from app.config import get_settings
from app.deadlines import RequestType
from app.models import Account, DsrRequest, VerificationChallenge


class Tier(StrEnum):
    ACCOUNT_MATCH = "account_match"
    STANDARD = "standard"
    HIGH = "high"


TIER_BY_TYPE: dict[RequestType, Tier] = {
    RequestType.OPT_OUT: Tier.ACCOUNT_MATCH,
    RequestType.CORRECTION: Tier.STANDARD,
    RequestType.ACCESS: Tier.HIGH,
    RequestType.DELETION: Tier.HIGH,
}


class Outcome(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    EXPIRED = "expired"
    LOCKED = "locked"


@dataclass
class VerifyResult:
    outcome: Outcome
    attempts_remaining: int


def _keyed(request_id: str, secret: str) -> str:
    key = get_settings().pseudonym_key.encode()
    return hmac.new(key, f"{request_id}:{secret}".encode(), hashlib.sha256).hexdigest()


def hash_ticket(request_id: str, ticket: str) -> str:
    return _keyed(request_id, "ticket:" + ticket)


def ticket_matches(req: DsrRequest, ticket: str) -> bool:
    return hmac.compare_digest(req.ticket_hash, hash_ticket(req.id, ticket))


def find_matching_account(db: Session, claimed_account_id: str, contact_email: str) -> Account | None:
    acct = db.get(Account, claimed_account_id)
    if acct and audit.normalize_email(acct.email) == audit.normalize_email(contact_email):
        return acct
    return None


def issue_challenge(
    db: Session, req: DsrRequest, account: Account | None, *, actor: str
) -> tuple[VerificationChallenge, str | None]:
    """Create a challenge. Returns the plaintext code only when it should be delivered."""
    s = get_settings()
    now = clock.now()
    for ch in req.challenges:
        if ch.consumed_at is None and ch.expires_at > now:
            ch.expires_at = now  # supersede any live challenge
    code = f"{secrets.randbelow(10**6):06d}"
    ch = VerificationChallenge(
        request_id=req.id,
        code_hash=_keyed(req.id, code),
        issued_at=now,
        expires_at=now + timedelta(minutes=s.code_ttl_minutes),
        attempts=0,
    )
    db.add(ch)
    req.challenges.append(ch)
    delivered = account is not None
    audit.record(
        db,
        "verification.challenge_issued",
        actor=actor,
        request_id=req.id,
        subject=req.subject_ref,
        details={
            "tier": req.verification_tier,
            "challenge_no": len(req.challenges),
            "delivered": delivered,
            **({} if delivered else {"withheld_because": "account_match_failed"}),
        },
    )
    return ch, (code if delivered else None)


def check(
    db: Session,
    req: DsrRequest,
    code: str,
    extra_attribute: str | None,
    *,
    actor: str,
) -> VerifyResult:
    """Evaluate one verification attempt. Does not change request status itself."""
    s = get_settings()
    now = clock.now()
    ch = req.challenges[-1] if req.challenges else None
    total_attempts = sum(c.attempts for c in req.challenges)
    if ch is None or ch.consumed_at is not None:
        return VerifyResult(Outcome.FAILED, max(0, s.max_code_attempts - total_attempts))
    if ch.expires_at <= now:
        audit.record(
            db, "verification.expired", actor=actor, request_id=req.id, subject=req.subject_ref, details={}
        )
        return VerifyResult(Outcome.EXPIRED, max(0, s.max_code_attempts - total_attempts))

    failed_factors: list[str] = []
    if not hmac.compare_digest(ch.code_hash, _keyed(req.id, code.strip())):
        failed_factors.append("code")
    if req.verification_tier == Tier.HIGH:
        acct = db.get(Account, req.claimed_account_id)
        if not (acct and extra_attribute and hmac.compare_digest(acct.device_serial_last4, extra_attribute)):
            failed_factors.append("account_attribute")

    if not failed_factors:
        ch.consumed_at = now
        audit.record(
            db,
            "verification.passed",
            actor=actor,
            request_id=req.id,
            subject=req.subject_ref,
            details={"tier": req.verification_tier, "factors": _factors_for(req.verification_tier)},
        )
        return VerifyResult(Outcome.VERIFIED, s.max_code_attempts - total_attempts)

    ch.attempts += 1
    total_attempts += 1
    remaining = max(0, s.max_code_attempts - total_attempts)
    # Which factor failed is recorded for investigators but never returned to the requester.
    audit.record(
        db,
        "verification.failed",
        actor=actor,
        request_id=req.id,
        subject=req.subject_ref,
        details={"attempt": total_attempts, "failed_factors": failed_factors, "remaining": remaining},
    )
    return VerifyResult(Outcome.LOCKED if remaining == 0 else Outcome.FAILED, remaining)


def _factors_for(tier: str) -> list[str]:
    if tier == Tier.HIGH:
        return ["email_code", "account_match", "account_attribute"]
    if tier == Tier.STANDARD:
        return ["email_code", "account_match"]
    return ["account_match"]
