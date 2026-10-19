# Audit-Readiness Checklist

Mapped to generic ISMS-style control areas (the kind found in ISO/IEC 27001 Annex A or SOC 2 criteria) without quoting any one standard's numbering. For each item, the evidence column says where an auditor finds proof in this reference implementation or in the operating records it assumes.

| Area | Control | How it is met here | Evidence | Status |
|---|---|---|---|---|
| Access control | Staff actions require authentication | `X-Staff-Key` on all operations endpoints (SSO + roles in production) | `app/deps.py`, 401 tests | Ref impl |
| Access control | Every staff action is attributable to a named person | `X-Actor` mandatory; stored as `actor` on audit events | audit rows, 400 test | Ref impl |
| Access control | Least privilege on personal data | Staff view masks email; audit log holds no email | `mask_email`, audit tests | Ref impl |
| Access control | Downstream systems authenticate separately | Shared key stands in; per-system credentials required in production | Design decisions | Gap (documented) |
| Identity verification | Assurance proportional to risk | Tiered: account match / code / code + attribute | `app/verification.py` | Ref impl |
| Identity verification | Brute force protection | 5 attempts total, 15 min code TTL, 3 codes max | config, lockout tests | Ref impl |
| Identity verification | No account enumeration | Identical intake response; undelivered challenge on mismatch | mismatch test | Ref impl |
| Logging | Security-relevant events logged | Intake, verification, transitions, fan-out, consent, halts, redaction | `audit_events` | Ref impl |
| Logging | Logs protected from alteration | Append-only triggers + ORM guard + hash chain | trigger and tamper tests | Ref impl |
| Logging | Log integrity checked periodically | `GET /v1/audit/verify`; weekly check in runbook | ops log of chain heads | Process |
| Logging | Logs minimize personal data | Keyed subject reference; forbidden-field guard | `audit.record` | Ref impl |
| Logging | External anchoring of log head | Not implemented | | Gap (documented) |
| Retention | Contact data removed when no longer needed | Redacted 30 days after closure (configurable) | `request.contact_redacted` events | Ref impl |
| Retention | Request records kept for required period | Record without direct identifiers retained (CCPA minimum 24 months, 11 CCR 7101) | schema | Ref impl; purge job not built |
| Retention | Verification secrets not stored in clear | Codes and tickets keyed-hashed | schema, test | Ref impl |
| Cryptography | Keys managed outside code | Env vars; secrets manager and rotation in production | config | Process |
| Change management | Changes reviewed and tested | CI: lint, tests, demo build; branch protection assumed | `.github/workflows/ci.yml` | Ref impl |
| Change management | Collection changes go through spec control | Consent spec versioning; `spec_version` on records | spec template | Process |
| Supplier management | Vendors bound by contract and SLA | Vendor systems flagged `operated_by: vendor` with confirmation SLA | system registry | Process |
| Supplier management | Vendor deletion evidenced | Per-task `confirmation_ref` | tasks table | Ref impl |
| Incident management | Collection outside spec can be stopped fast | Program halt per purpose | halt tests, stats | Ref impl |
| Incident management | Integrity failure triggers incident | Escalation table in operating procedure | DSR procedure | Process |
| Compliance | Deadlines computed from cited rules | `app/deadlines.py` with statute references | deadline tests | Ref impl |
| Compliance | Extensions noticed in time and only once | Enforced in workflow | state machine tests | Ref impl |
| Compliance | Denials carry reasons and notice | Reason codes + denial notice | tests | Ref impl |
| Compliance | Performance monitored | SLA dashboard; monthly metrics | `/v1/sla/dashboard` | Ref impl |
| Data inventory | Systems holding personal data are registered | Downstream registry drives fan-out; unregistered = missed | `/v1/systems` | Process (registry must track data map) |

## Evidence pack for an audit window

1. Export of requests closed in the window with dates, type, outcome, basis (no contact data).
2. Audit chain verification output at window start and end, plus weekly heads.
3. Per-system confirmation latency and any exemptions with legal basis.
4. Extension and denial list with notice timestamps.
5. Consent spec versions in force and acceptance test results.
6. Collection stats for any halted purpose before and after the halt.
7. Access review of staff accounts with operations rights.
