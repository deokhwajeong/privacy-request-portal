# Vendor and Law-Firm Coordination Plan

How a privacy program runs delivery across internal engineering, an IT services partner, and outside counsel in more than one jurisdiction. Written for a launch (new regime or new product surface) and for steady state.

## Parties

| Party | Brings | Owns | Does not own |
|---|---|---|---|
| Program lead (internal) | Plan, priorities, decisions log | Scope, schedule, final requirements, sign-off package | Legal interpretation |
| Outside counsel, EU firm | GDPR interpretation, member-state nuances | Written opinions, notice and consent wording review | Engineering design |
| Outside counsel, US firm | CCPA/CPRA and regs, other state laws | Opinions, notice review, denial wording | Engineering design |
| Local counsel (added per market) | Local law (e.g. data localization or local-entity rules) | Market-specific requirements memo | Global design |
| Internal engineering | Platform, device, backend | Implementation of spec and portal integration | Requirements |
| IT services partner | Portal build or support desk operation | Delivery under SOW, confirmation SLAs | Requirements, legal decisions |

## Turning legal advice into buildable requirements

| Step | Output | Owner | Gate |
|---|---|---|---|
| 1. Question list | Numbered questions, each tied to a feature or data flow | Program lead | |
| 2. Counsel opinion | Short written answer per question, with citation and confidence | Counsel | |
| 3. Requirement | "Shall" statement, testable, linked to question ID | Program lead | Counsel confirms the requirement matches the opinion |
| 4. Spec | Consent spec / DSR procedure updated | Program lead | Engineering confirms feasibility |
| 5. Build and test | Acceptance tests mapped to requirement IDs | Engineering, partner | Test evidence attached |
| 6. Sign-off | Traceability matrix: question > opinion > requirement > test | Program lead | Counsel and security sign |

Rule: no requirement without a question ID, no question closed without a written answer. Disagreements between jurisdictions resolve to the stricter control unless counsel documents why not.

## Cadence

| Meeting | Who | Frequency | Output |
|---|---|---|---|
| Counsel working session | Program lead, both firms | Weekly during design, monthly after | Updated question log |
| Engineering stand-up (privacy track) | Program lead, eng leads, partner PM | 2x weekly during build | Risks, blockers |
| Vendor SLA review | Program lead, partner account lead | Monthly | Confirmation latency, misses, corrective actions |
| Steering | Program lead, legal head, product and security leads | Monthly | Decisions, risk acceptance |
| Regulatory change scan | Counsel to program lead | Quarterly | Change memo, impact list |

## Vendor obligations (contract checklist)

| Item | Requirement |
|---|---|
| DPA / service provider terms | Processing only on instructions; CCPA service provider/contractor terms; GDPR Art. 28 terms |
| DSR support | Act on delete/export/correct/suppress within registry SLA; return evidence reference |
| Sub-processors | Prior notice and right to object |
| Security | Controls aligned to the program's ISMS baseline; audit right or third-party report |
| Breach notice | Notify within contractually set hours |
| Retention and return | Delete or return at end of contract with certificate |
| Change notice | Notify before changing data flows that touch the purpose register |

## Budget and scope control for outside counsel

| Practice | Why |
|---|---|
| Fixed question list per phase with estimate | Avoids open-ended research billing |
| Reuse prior opinions across markets, ask only for deltas | Most questions repeat |
| One internal point of contact | Prevents duplicate questions from different teams |
| Opinions written to the question ID | Makes them reusable in audit |

## Adding a new regime

1. Local counsel memo on rights, deadlines, verification, and any localization or registration duties.
2. Map to existing request types; add a regime to `app/deadlines.py` only with cited figures.
3. Update consent spec purposes and defaults for the market.
4. Register any new downstream systems.
5. Run acceptance tests; update the audit evidence pack.
