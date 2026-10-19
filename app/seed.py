"""Fictional reference data: downstream systems, collection purposes, and test accounts.

Every name, address, and identifier here is invented. Emails use reserved
example domains (RFC 2606).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Account, DownstreamSystem, Purpose

SYSTEMS = [
    # key, name, owner, operated_by, categories, supports, confirmation SLA days
    ("account-core", "Account and profile service", "Identity Platform", "internal",
     ["identifiers", "profile", "contact"], ["access", "deletion", "correction"], 3),
    ("viewing-activity", "Viewing activity store", "Media Data Eng", "internal",
     ["usage", "device_events"], ["access", "deletion"], 5),
    ("ad-decisioning", "Ad decisioning platform", "Ads Engineering", "internal",
     ["advertising_ids", "inferences"], ["access", "deletion", "opt_out"], 5),
    ("analytics-warehouse", "Analytics warehouse", "Data Platform", "internal",
     ["usage", "inferences"], ["access", "deletion"], 7),
    ("support-desk", "Customer support desk", "Customer Care (IT services partner)", "vendor",
     ["contact", "support_history"], ["access", "deletion", "correction"], 7),
    ("measurement-partner", "Third-party audience measurement", "Partner Ops", "vendor",
     ["advertising_ids", "usage"], ["deletion", "opt_out"], 10),
]  # fmt: skip

PURPOSES = [
    ("viewing_information", "Content recognition and viewing history for recommendations", "consent", False),
    ("personalized_ads", "Interest-based advertising", "consent", False),
    # CCPA uses an opt-out model for sale/sharing; where GDPR applies this purpose would be consent-based.
    ("sale_share", "Sale or sharing of personal information (CCPA)", "opt_out_model", True),
    ("voice_recordings", "Voice command audio retained for quality review", "consent", False),
    ("diagnostics", "Crash and performance diagnostics", "legitimate_interest", True),
]

ACCOUNTS = [
    ("ACC-10021", "mara.lindqvist@example.com", "SE", "4471"),
    ("ACC-10022", "jonas.pereira@example.net", "PT", "9022"),
    ("ACC-10023", "ines.vogel@example.com", "DE", "1308"),
    ("ACC-10024", "theo.marchand@example.org", "FR", "5560"),
    ("ACC-10025", "ava.holloway@example.com", "US-CA", "7713"),
    ("ACC-10026", "rafael.ortiz@example.net", "US-CA", "2045"),
    ("ACC-10027", "noor.haddad@example.com", "US-CA", "3389"),
    ("ACC-10028", "kenji.arai@example.org", "US-CA", "6150"),
    ("ACC-10029", "elena.rossi@example.com", "IT", "8804"),
    ("ACC-10030", "sam.okafor@example.net", "US-CA", "1192"),
    ("ACC-10031", "lucia.brandt@example.com", "AT", "6627"),
    ("ACC-10032", "dev.patel@example.org", "US-CA", "4038"),
    ("ACC-10033", "hana.novak@example.com", "CZ", "7251"),
    ("ACC-10034", "owen.byrne@example.net", "IE", "3914"),
    ("ACC-10035", "maya.chen@example.com", "US-CA", "5086"),
    ("ACC-10036", "felix.adeyemi@example.org", "NL", "2967"),
]


def seed(db: Session) -> None:
    if db.get(DownstreamSystem, SYSTEMS[0][0]) is None:
        for key, name, owner, op, cats, supports, sla in SYSTEMS:
            db.add(
                DownstreamSystem(
                    key=key,
                    name=name,
                    owner=owner,
                    operated_by=op,
                    data_categories=cats,
                    supports=supports,
                    confirmation_sla_days=sla,
                )
            )
    if db.get(Purpose, PURPOSES[0][0]) is None:
        for key, desc, basis, default in PURPOSES:
            db.add(Purpose(key=key, description=desc, lawful_basis=basis, default_granted=default))
    if db.get(Account, ACCOUNTS[0][0]) is None:
        for acct_id, email, region, last4 in ACCOUNTS:
            db.add(Account(account_id=acct_id, email=email, region=region, device_serial_last4=last4))
    db.commit()
