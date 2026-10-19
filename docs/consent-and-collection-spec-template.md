# Consent and Data-Collection Specification (Template)

Use one spec per product surface (device OS, companion app, web). Engineering builds against it; legal signs off on it; audit tests against it. Version every change. The `spec_version` field on each consent record points back to the version the user saw.

| Field | Value |
|---|---|
| Spec ID / version | `CDS-<surface>-<n>` / `1.2` |
| Product surface | e.g. connected TV platform, settings app |
| Markets in scope | e.g. EEA + UK, California, other US states |
| Spec owner (accountable) | Privacy program lead |
| Approvers | Privacy counsel per region, security, product owner |
| Effective date | |
| Supersedes | |

## 1. Purpose register

One row per purpose. A purpose that is not in this table must not be collected; the gate refuses unknown purposes.

| Purpose key | Plain-language description shown to user | Data elements | Lawful basis (GDPR) | CCPA category / sale or share? | Default | Retention | Recipients (internal, vendor, third party) |
|---|---|---|---|---|---|---|---|
| `viewing_information` | "Recognize what is on screen to recommend content" | content fingerprints, timestamps, device ID | Consent (Art. 6(1)(a)) | Internet activity; shared for ads? Y/N | Off | 12 months | recommendation service |
| `personalized_ads` | | ad ID, inferred interests | Consent | Inferences; share = Y | Off | | ad platform, measurement partner |
| `sale_share` | "Sell or share my personal information" | ad ID, usage | n/a in EEA (consent purposes cover it) | sale/share opt-out | On (CA) | | partners listed in notice |
| `voice_recordings` | | audio clips, transcripts | Consent | Audio info | Off | 90 days | speech vendor |
| `diagnostics` | | crash logs, firmware version | Legitimate interest (LIA ref) | Not sold or shared | On | 30 days | internal only |

Rules:
- Consent-based purposes default to **off**. Silence or dismissal is not consent.
- Each purpose maps to exactly one toggle. No bundling of unrelated purposes behind one switch.
- A legitimate-interest purpose still gets an objection control and a written balancing test.

## 2. User controls

| Control | Location | Behavior | Must take effect within |
|---|---|---|---|
| Per-purpose toggle | Settings > Privacy | Writes consent record; gate refuses next event | Next collection call (no client cache longer than session) |
| Withdraw all | Settings > Privacy | Sets every consent purpose to off | Same |
| Opt-out of sale/share | Settings, web form, Global Privacy Control signal | Sets `sale_share` off; opens DSR of type `opt_out` for downstream suppression | Gate: immediately. Downstream: 15 business days (11 CCR 7026(f)) |
| First-run notice | Out-of-box setup | Shows each consent purpose unticked, with "Skip" equal in prominence to "Agree" | n/a |
| Halt (program level) | Privacy ops console | Stops a purpose for everyone, regardless of individual choices | Immediately |

## 3. Collection gate contract

| Item | Requirement |
|---|---|
| Call | `POST /v1/collect {account_id, purpose, event_type}` before sending any event |
| Allow | `202 {accepted: true}` only when purpose exists, is not halted, and effective choice is granted |
| Refuse | `409` with reason `not_granted`, `purpose_halted`, or `unknown_purpose`; client drops the event, does not queue it |
| Failure mode | Gate unreachable means do not collect (fail closed) |
| Evidence | Gate logs accepted/refused counts per purpose with a keyed account reference, no payload |
| Client caching | Decision may be cached for the session only; any toggle change invalidates it |

## 4. Change control

| Change | Requires |
|---|---|
| New purpose or new data element | Spec version bump, counsel approval per region, DPIA screen, notice update before collection starts |
| New recipient or vendor | Vendor assessment, DPA, notice update |
| Default changed from off to on | Not allowed for consent purposes |
| Retention extended | Counsel approval, record update |
| Defect found (collecting outside spec) | Halt the purpose first, then investigate; incident ticket within 24h |

## 5. Acceptance tests (attach results to the spec version)

| # | Test | Expected |
|---|---|---|
| 1 | Fresh device, skip all prompts, trigger each consent purpose | Gate refuses all; no outbound traffic for those purposes |
| 2 | Grant, then withdraw `viewing_information` | Events accepted, then refused from next call |
| 3 | Halt `voice_recordings` with user consent granted | Refused with `purpose_halted` |
| 4 | Unknown purpose key | Refused with `unknown_purpose` |
| 5 | Opt-out via settings | `sale_share` off; DSR opened; suppression tasks dispatched |
| 6 | Gate unavailable | Client collects nothing |
| 7 | Network capture vs purpose register | Every observed endpoint maps to a listed purpose and recipient |

## 6. Open items log

| # | Question | Owner | Due | Resolution |
|---|---|---|---|---|
| | | | | |
