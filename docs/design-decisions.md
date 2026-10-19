# Design Decisions

| # | Decision | Why | Trade-off |
|---|---|---|---|
| 1 | Deadline clock starts at receipt and keeps running during verification | 11 CCR 7021(b) says the 45 days begins on receipt regardless of verification time. Applying the same rule to GDPR is the conservative choice | Requests with slow verifiers lose usable time |
| 2 | Month arithmetic clamps to month end (31 Jan + 1 month = 28 Feb) | Matches Regulation 1182/71 Art. 3(2)(c) on periods in months | None found |
| 3 | GDPR extension = earlier of (original due + 2 months) and (receipt + 3 months) | The two readings differ when the original due date was clamped; earlier is safe | May lose 1 to 3 days in rare cases. **Confirm with counsel** |
| 4 | Dates in UTC, end of day | Simple and testable | Real deployments should pin a reference timezone per regime |
| 5 | Business days skip weekends only | Holiday calendars are jurisdiction specific | Deadlines come out earlier than strictly needed, never later |
| 6 | Risk-based verification tiers (opt-out: account match; correction: code; access and deletion: code + extra attribute) | Wrongful disclosure and irreversible deletion are the highest harms; opt-outs only reduce processing and need not be verifiable (11 CCR 7026(d)) | Extra attribute adds friction for legitimate users |
| 7 | Code sent to the email on file, not the email typed | Proves control of the account's address | Users who lost access to that email need a manual path (not built) |
| 8 | Identical intake response on account mismatch, with a challenge that is never delivered | Prevents using the portal to learn who has an account | Legit users with a typo learn only by timeout; support script covers it |
| 9 | Ticket per request, hashed; status checked by POST | Lets requesters act without accounts; keeps tokens out of URLs and logs | Lost ticket means contacting support |
| 10 | One extension per request, noticed before the original due date | Both regimes allow a single extension with notice in the first period | |
| 11 | Fan-out to every registered system that supports the type; request completes only when every task is confirmed or exempt | Deletion is only as complete as the least reliable system; per-system evidence is what audits ask for | Registry must be kept in sync with the data map |
| 12 | Exemptions recorded per system with legal basis, not per request | Usually one system retains data (e.g. warranty records) while the rest delete | |
| 13 | Audit log is append-only and hash-chained, with keyed subject references | Tamper evidence without storing who the person is; keyed hash resists dictionary attacks on emails | Rotating the key breaks linkage to old entries (acceptable, sometimes desired) |
| 14 | Audit details refuse fields named like personal data | Makes accidental PII logging fail in tests instead of in an audit | Free-text staff reasons are still allowed and need review |
| 15 | Contact email redacted 30 days after closure; record kept | Record-keeping needs dates, type, outcome, basis (11 CCR 7101 sets 24 months for CCPA); it does not need the address | Follow-up questions after 30 days need the requester to identify again |
| 16 | Consent purposes default off; unknown purposes refused; gate fails closed | Silence is not consent; collection outside the register is a defect | A gate outage stops collection |
| 17 | Program-wide halt per purpose, independent of individual choices | The fastest control when a spec defect or vendor issue is found | Needs an owner on call |
| 18 | SQLite and synchronous SQLAlchemy | Reference implementation; easy to run and inspect | Concurrent audit appends need row locking or a sequence on a server database |
| 19 | GDPR "opt_out" maps to Art. 21 objection | Keeps one request type across regimes for the portal UI | Art. 21 has its own nuances (absolute for direct marketing) that counsel should map per purpose |

## Figures I am not certain of

These are cited in code, but should be confirmed against current text before relying on them:

- The exact subsection numbering in the CCPA regulations (7021, 7026, 7060 to 7062, 7101) after the 2023 amendments.
- Whether a GDPR controller may pause the one-month clock while waiting for identity information. EDPB guidance on the right of access discusses this; this implementation does not pause.
- Request-limit rules (e.g. CCPA access more than twice in 12 months) are modeled only as a denial reason code, not enforced.

## Not built (deliberately)

Per-system credentials for confirmations, SSO and roles, external anchoring of the audit chain head, holiday calendars, request record purge after the retention period, authorized-agent flows, data export packaging, and alembic migrations.
