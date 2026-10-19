# DSR Operating Procedure

Scope: requests to access, delete, correct, or opt out (CCPA) / object (GDPR Art. 21) from consumers in GDPR and CCPA jurisdictions. Statutory figures below are cited for orientation; counsel confirms the current text before go-live and at each annual review.

## Roles

| Role | Responsibilities |
|---|---|
| Privacy program lead (owner) | Owns the procedure, SLAs, metrics, and escalation; approves extensions and denials on legal grounds |
| Intake analyst | Triages queue daily, starts fulfillment after verification, chases downstream confirmations, drafts notices |
| Privacy counsel (regional, internal or outside firm) | Interprets exemptions, approves denial wording, advises on novel requests |
| System owner (per downstream system) | Executes delete/export/correct/suppress in their system and confirms with an evidence reference |
| Vendor / IT services partner | Same as system owner for vendor-operated systems, under contract SLA |
| Security / identity team | Owns verification controls, fraud review, and lockout policy |
| Customer support | Routes requests received by phone or chat into the portal; never fulfills directly |

## RACI

| Activity | Program lead | Intake analyst | Counsel | System owner | Vendor | Security |
|---|---|---|---|---|---|---|
| Intake and acknowledgement | A | R | | | | |
| Identity verification policy | A | C | C | | | R |
| Verification exceptions (manual) | A | R | C | | | C |
| Start fulfillment / fan-out | A | R | | I | I | |
| Execute and confirm in system | I | C | | R/A | R | |
| Exemption decision (retain data) | A | C | R | C | | |
| Extension decision and notice | A | R | C | | | |
| Denial decision and notice | A | R | R | | | |
| SLA reporting | R/A | C | I | I | I | |
| Audit log integrity check | A | | | | | R |
| Annual procedure review | R/A | C | R | C | C | C |

R responsible, A accountable, C consulted, I informed.

## Deadlines

| Regime | Request | Respond within | Extension | Acknowledge | Source |
|---|---|---|---|---|---|
| GDPR | Access, erasure, rectification, objection | 1 month from receipt | +2 months, notice with reasons inside first month | No fixed rule | Art. 12(3) |
| CCPA | Know, delete, correct | 45 calendar days from receipt | +45 days once, notice inside first 45 | 10 business days | Civ. Code 1798.130(a)(2); 11 CCR 7021 |
| CCPA | Opt-out of sale/sharing | 15 business days | None | n/a | 11 CCR 7026(f) |

Clock rules used by the portal: start on the date of receipt, keep running during verification, month arithmetic clamps to month end. See [Design decisions](design-decisions.md).

## Internal SLAs

| Step | Target | Measured by |
|---|---|---|
| Acknowledgement | Automatic at intake | `notice.acknowledgement_sent` event |
| Start fulfillment after verification | 2 business days | `verified_at` to `started_at` |
| Downstream confirmation | Per system registry (3 to 10 days) | task `due_at` |
| Close | 75% of statutory window | SLA status turns `at_risk` in final 25% |
| Extension decision | Before final 25% of the window | `extended_at` |

## Daily runbook

1. Open the SLA dashboard. Work `breached`, then `at_risk`, then oldest `verified`.
2. Start verified requests. Fan-out is automatic for every registered system that supports the request type.
3. For each blocked system (failed or past confirmation SLA): retry, then contact owner; vendors via the contract channel.
4. Run the verification sweep (automated nightly) and the contact retention job (automated nightly).
5. Weekly: confirm `/v1/audit/verify` returns `ok: true` and record the chain head in the ops log.

## Escalation

| Trigger | Escalate to | Within |
|---|---|---|
| Request enters `at_risk` | System owner manager (if blocked) or program lead | Same day |
| Downstream failure repeats after one retry | System owner manager + program lead | 1 business day |
| Vendor misses confirmation SLA | Vendor manager, then contract escalation path | 2 business days |
| Extension needed | Program lead approves; counsel consulted if novel | Before final 25% |
| Request will breach | Program lead + counsel; decide on partial response and notice | Immediately |
| Audit chain verification fails | Security incident process | Immediately |
| Suspected fraudulent request pattern | Security | Same day |

## Denials

Allowed reason codes: `identity_not_verified`, `verification_not_completed`, `legal_exemption`, `manifestly_unfounded_or_excessive`, `request_limit_exceeded`, `withdrawn_by_requester`. Every denial sends a notice with the reason. Under GDPR the notice also states the right to complain to a supervisory authority and to seek a judicial remedy (Art. 12(4)). Counsel approves wording for `legal_exemption` and `manifestly_unfounded_or_excessive`.

## Metrics reported monthly

On-time closure rate by regime and type; median and max days to close; extensions and reasons; denials by reason; downstream confirmation latency by system; verification failure and lockout rate; opt-outs processed.
