from datetime import timedelta

from sqlalchemy import text

from app import clock
from tests.conftest import CA, STAFF, T0, started_request, submit

ACCT = CA["account_id"]


def _collect(client, purpose, account=ACCT):
    return client.post("/v1/collect", json={"account_id": account, "purpose": purpose, "event_type": "tick"})


def test_consent_purpose_defaults_to_not_collecting(client):
    r = _collect(client, "viewing_information")
    assert r.status_code == 409
    assert r.json() == {"accepted": False, "reason": "not_granted"}


def test_grant_then_withdraw_halts_collection(client):
    client.put(f"/v1/consent/{ACCT}/viewing_information", json={"granted": True, "source": "first_run"})
    assert _collect(client, "viewing_information").status_code == 202
    client.put(f"/v1/consent/{ACCT}/viewing_information", json={"granted": False})
    r = _collect(client, "viewing_information")
    assert r.status_code == 409 and r.json()["reason"] == "not_granted"


def test_program_halt_overrides_individual_consent(client):
    client.put(f"/v1/consent/{ACCT}/personalized_ads", json={"granted": True})
    r = client.post(
        "/v1/purposes/personalized_ads/halt", json={"reason": "SDK defect found in review"}, headers=STAFF
    )
    assert r.status_code == 200
    assert _collect(client, "personalized_ads").json()["reason"] == "purpose_halted"
    items = {c["purpose"]: c for c in client.get(f"/v1/consent/{ACCT}").json()}
    assert items["personalized_ads"]["granted"] is True
    assert items["personalized_ads"]["collecting"] is False
    client.post("/v1/purposes/personalized_ads/resume", headers=STAFF)
    assert _collect(client, "personalized_ads").status_code == 202


def test_halt_requires_staff(client):
    r = client.post("/v1/purposes/diagnostics/halt", json={"reason": "no auth here"})
    assert r.status_code == 401


def test_unknown_purpose_is_refused_not_allowed(client):
    assert _collect(client, "something_new").json()["reason"] == "unknown_purpose"
    assert client.put(f"/v1/consent/{ACCT}/something_new", json={"granted": True}).status_code == 404


def test_legitimate_interest_purpose_on_by_default_and_objectable(client):
    assert _collect(client, "diagnostics").status_code == 202
    client.put(f"/v1/consent/{ACCT}/diagnostics", json={"granted": False})
    assert _collect(client, "diagnostics").status_code == 409


def test_collection_log_is_pseudonymous(client, db):
    _collect(client, "diagnostics")
    rows = db.execute(text("SELECT account_ref, accepted, reason FROM collection_log")).all()
    assert rows and all(ACCT not in r.account_ref for r in rows)


def test_consent_changes_are_audited(client, db):
    client.put(f"/v1/consent/{ACCT}/voice_recordings", json={"granted": True})
    rows = db.execute(text("SELECT action, details FROM audit_events WHERE action = 'consent.changed'")).all()
    assert len(rows) == 1 and "voice_recordings" in rows[0].details


def test_staff_endpoints_require_key_and_named_actor(client):
    assert client.get("/v1/sla/dashboard").status_code == 401
    assert client.get("/v1/sla/dashboard", headers={"X-Staff-Key": "test-staff-key"}).status_code == 400
    assert client.get("/v1/sla/dashboard", headers=STAFF).status_code == 200


def test_sweep_closes_unverified_requests(client):
    stale = submit(client)
    clock.freeze(T0 + timedelta(days=15))
    fresh = submit(client)
    r = client.post("/v1/admin/sweep", headers=STAFF)
    assert r.json() == {"closed_unverified": [stale["request_id"]]}
    state = client.get(f"/v1/requests/{stale['request_id']}", headers=STAFF).json()
    assert state["denial_reason"] == "verification_not_completed"
    assert client.get(f"/v1/requests/{fresh['request_id']}", headers=STAFF).json()["status"] == "verifying"


def test_retention_redacts_contact_after_closure(client, db):
    created, req = started_request(client)
    for t in req["tasks"]:
        client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF)
    rid = created["request_id"]
    assert client.post("/v1/admin/retention", headers=STAFF).json() == {"redacted": []}
    clock.freeze(T0 + timedelta(days=31))
    assert client.post("/v1/admin/retention", headers=STAFF).json() == {"redacted": [rid]}
    row = db.execute(
        text("SELECT contact_email, redacted_at FROM dsr_requests WHERE id = :i"), {"i": rid}
    ).one()
    assert row.contact_email is None and row.redacted_at is not None
    staff_view = client.get(f"/v1/requests/{rid}", headers=STAFF).json()
    assert staff_view["contact_email_masked"] is None


def test_staff_view_masks_email(client):
    created = submit(client)
    view = client.get(f"/v1/requests/{created['request_id']}", headers=STAFF).json()
    assert view["contact_email_masked"] == "m***@example.com"


def test_collection_stats_prove_halt_took_effect(client):
    client.put(f"/v1/consent/{ACCT}/personalized_ads", json={"granted": True})
    _collect(client, "personalized_ads")
    client.post("/v1/purposes/personalized_ads/halt", json={"reason": "Vendor review"}, headers=STAFF)
    _collect(client, "personalized_ads")
    _collect(client, "personalized_ads")
    stats = {s["purpose"]: s for s in client.get("/v1/collection/stats", headers=STAFF).json()}
    assert stats["personalized_ads"] == {
        "purpose": "personalized_ads",
        "accepted": 1,
        "refused": {"purpose_halted": 2},
    }
