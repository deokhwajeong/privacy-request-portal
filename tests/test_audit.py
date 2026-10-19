import hashlib

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from app import audit
from app.db import get_engine
from app.models import AuditEvent
from tests.conftest import CA, EU, STAFF, started_request


def _run_full_flow(client):
    created, req = started_request(client)
    for t in req["tasks"]:
        client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF)
    started_request(client, who=CA, regime="ccpa", rtype="opt_out")
    return created["request_id"]


def test_chain_verifies_after_activity(client):
    _run_full_flow(client)
    report = client.get("/v1/audit/verify", headers=STAFF).json()
    assert report["ok"] is True
    assert report["events"] > 15


def test_audit_log_contains_no_email_addresses(client, db):
    _run_full_flow(client)
    rows = db.execute(text("SELECT * FROM audit_events")).all()
    dump = " ".join(str(v) for row in rows for v in row)
    for who in (EU, CA):
        assert who["email"] not in dump
        assert who["email"].split("@")[0] not in dump
    assert "@" not in dump


def test_subject_ref_is_keyed_not_plain_hash(client):
    plain = hashlib.sha256(EU["email"].encode()).hexdigest()
    assert audit.subject_ref(EU["email"]) != plain
    assert audit.subject_ref(EU["email"]) == audit.subject_ref("  Mara.Lindqvist@Example.com ")


def test_events_for_one_request_share_a_subject_ref(client):
    rid = _run_full_flow(client)
    events = client.get(f"/v1/requests/{rid}/audit", headers=STAFF).json()
    assert len({e["subject_ref"] for e in events}) == 1


def test_database_trigger_blocks_update_and_delete(client):
    _run_full_flow(client)
    with get_engine().begin() as conn:
        with pytest.raises(DatabaseError, match="append-only"):
            conn.execute(text("UPDATE audit_events SET actor = 'mallory' WHERE seq = 1"))
    with get_engine().begin() as conn:
        with pytest.raises(DatabaseError, match="append-only"):
            conn.execute(text("DELETE FROM audit_events WHERE seq = 1"))


def test_orm_guard_blocks_update(client, db):
    _run_full_flow(client)
    ev = db.execute(select(AuditEvent).limit(1)).scalar_one()
    ev.actor = "mallory"
    with pytest.raises(PermissionError):
        db.flush()


def test_tampering_is_detected_when_trigger_is_bypassed(client):
    _run_full_flow(client)
    with get_engine().begin() as conn:
        conn.execute(text("DROP TRIGGER audit_events_no_update"))
        conn.execute(text('UPDATE audit_events SET details = \'{"to": "fulfilled"}\' WHERE seq = 5'))
    report = client.get("/v1/audit/verify", headers=STAFF).json()
    assert report["ok"] is False
    assert report["first_bad_seq"] == 5


def test_removed_event_is_detected(client):
    _run_full_flow(client)
    with get_engine().begin() as conn:
        conn.execute(text("DROP TRIGGER audit_events_no_delete"))
        conn.execute(text("DELETE FROM audit_events WHERE seq = 3"))
    report = client.get("/v1/audit/verify", headers=STAFF).json()
    assert report["ok"] is False
    assert report["first_bad_seq"] == 4


def test_personal_data_fields_refused_in_details(db):
    with pytest.raises(ValueError, match="personal data"):
        audit.record(db, "oops", actor="dev", details={"email": "someone@example.com"})


def test_verification_code_never_stored_in_clear(client, db):
    from app.notifier import outbox

    created, _ = started_request(client)
    code = outbox.last_code(created["request_id"])
    rows = db.execute(text("SELECT * FROM verification_challenges")).all()
    assert rows
    assert all(code not in [str(v) for v in row] for row in rows)
    assert all(len(row.code_hash) == 64 for row in rows)
    dump = " ".join(str(v) for row in db.execute(text("SELECT * FROM dsr_requests")).all() for v in row)
    assert created["ticket"] not in dump
