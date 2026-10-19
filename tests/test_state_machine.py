from datetime import timedelta

import pytest

from app import clock
from app.models import Status
from app.state_machine import TRANSITIONS, can_transition
from tests.conftest import CA, EU, STAFF, T0, started_request, submit, verified_request, verify

ALL = list(Status)


@pytest.mark.parametrize("src", ALL)
@pytest.mark.parametrize("dst", ALL)
def test_transition_table_is_closed(src, dst):
    assert can_transition(src, dst) == (dst in TRANSITIONS[src])


def test_terminal_states_have_no_exits():
    assert not TRANSITIONS[Status.FULFILLED]
    assert not TRANSITIONS[Status.DENIED]


def _status(client, rid):
    return client.get(f"/v1/requests/{rid}", headers=STAFF).json()


def _confirm_all(client, rid):
    for t in _status(client, rid)["tasks"]:
        if t["status"] == "pending":
            r = client.post(
                f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"ok-{t['id']}"}, headers=STAFF
            )
            assert r.status_code == 200, r.text


def test_received_to_verifying(client):
    created = submit(client)
    assert created["status"] == "verifying"


def test_received_to_verified_for_opt_out(client):
    created = submit(client, CA, "ccpa", "opt_out")
    assert created["status"] == "verified"


def test_received_to_denied_when_opt_out_account_not_found(client):
    who = {**CA, "account_id": "ACC-99999"}
    created = submit(client, who, "ccpa", "opt_out")
    req = _status(client, created["request_id"])
    assert req["status"] == "denied"
    assert req["denial_reason"] == "identity_not_verified"


def test_verifying_to_verified(client):
    created = submit(client)
    r = verify(client, created)
    assert r.json() == {"outcome": "verified", "status": "verified", "attempts_remaining": 5}


def test_verifying_to_denied_after_lockout(client):
    created = submit(client)
    for _ in range(5):
        r = verify(client, created, code="000000")
    assert r.json()["outcome"] == "locked"
    assert _status(client, created["request_id"])["status"] == "denied"


def test_verified_to_in_progress(client):
    _, req = started_request(client)
    assert req["status"] == "in_progress"
    assert req["started_at"]


def test_in_progress_to_fulfilled_only_when_all_systems_confirm(client):
    created, req = started_request(client)
    rid = created["request_id"]
    first = req["tasks"][0]
    client.post(f"/v1/tasks/{first['id']}/confirm", json={"confirmation_ref": "x-1"}, headers=STAFF)
    assert _status(client, rid)["status"] == "in_progress"
    _confirm_all(client, rid)
    assert _status(client, rid)["status"] == "fulfilled"


def test_verified_to_extended_then_in_progress_then_fulfilled(client):
    created = verified_request(client)
    rid = created["request_id"]
    r = client.post(
        f"/v1/requests/{rid}/extend", json={"reason": "Data held in archived backups"}, headers=STAFF
    )
    assert r.json()["status"] == "extended"
    r = client.post(f"/v1/requests/{rid}/start", headers=STAFF)
    assert r.json()["status"] == "in_progress"
    assert r.json()["extended_at"]
    _confirm_all(client, rid)
    assert _status(client, rid)["status"] == "fulfilled"


def test_in_progress_to_extended_to_fulfilled(client):
    created, _ = started_request(client, who=CA, regime="ccpa")
    rid = created["request_id"]
    r = client.post(
        f"/v1/requests/{rid}/extend", json={"reason": "Vendor backlog on support desk"}, headers=STAFF
    )
    body = r.json()
    assert body["status"] == "extended"
    assert body["due_at"].startswith("2026-05-31")  # 2 Mar + 45 = 16 Apr; + 45 = 31 May
    _confirm_all(client, rid)
    assert _status(client, rid)["status"] == "fulfilled"


@pytest.mark.parametrize("stage", ["verified", "in_progress", "extended"])
def test_deny_with_reason_from_open_states(client, stage):
    if stage == "verified":
        rid = verified_request(client)["request_id"]
    else:
        rid = started_request(client)[0]["request_id"]
        if stage == "extended":
            client.post(
                f"/v1/requests/{rid}/extend", json={"reason": "Complex multi-system search"}, headers=STAFF
            )
    r = client.post(
        f"/v1/requests/{rid}/deny",
        json={"reason": "legal_exemption", "detail": "Retention required by tax law"},
        headers=STAFF,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "denied"
    assert r.json()["denial_reason"] == "legal_exemption"
    assert all(t["status"] in ("exempt", "confirmed") for t in r.json()["tasks"])


def test_terminal_request_rejects_further_actions(client):
    created, _ = started_request(client)
    rid = created["request_id"]
    _confirm_all(client, rid)
    assert client.post(f"/v1/requests/{rid}/start", headers=STAFF).status_code == 409
    r = client.post(
        f"/v1/requests/{rid}/deny",
        json={"reason": "legal_exemption", "detail": "too late now"},
        headers=STAFF,
    )
    assert r.status_code == 409
    r = client.post(f"/v1/requests/{rid}/extend", json={"reason": "too late to extend"}, headers=STAFF)
    assert r.status_code == 409


def test_cannot_start_unverified_request(client):
    created = submit(client)
    assert client.post(f"/v1/requests/{created['request_id']}/start", headers=STAFF).status_code == 409


def test_extension_only_once(client):
    rid = verified_request(client)["request_id"]
    client.post(f"/v1/requests/{rid}/extend", json={"reason": "first extension, complex"}, headers=STAFF)
    client.post(f"/v1/requests/{rid}/start", headers=STAFF)
    r = client.post(f"/v1/requests/{rid}/extend", json={"reason": "second extension attempt"}, headers=STAFF)
    assert r.status_code == 409
    assert "already been extended" in r.json()["detail"]


def test_ccpa_opt_out_cannot_be_extended(client):
    rid = submit(client, CA, "ccpa", "opt_out")["request_id"]
    r = client.post(f"/v1/requests/{rid}/extend", json={"reason": "would like more time"}, headers=STAFF)
    assert r.status_code == 409
    assert "7026" in r.json()["detail"]


def test_extension_must_be_noticed_before_original_deadline(client):
    rid = verified_request(client)["request_id"]
    clock.freeze(T0 + timedelta(days=40))
    r = client.post(f"/v1/requests/{rid}/extend", json={"reason": "noticed too late"}, headers=STAFF)
    assert r.status_code == 409


def test_status_changes_are_audited_in_order(client):
    created, _ = started_request(client, who=EU)
    rid = created["request_id"]
    _confirm_all(client, rid)
    events = client.get(f"/v1/requests/{rid}/audit", headers=STAFF).json()
    path = [
        (e["details"]["from"], e["details"]["to"]) for e in events if e["action"] == "request.status_changed"
    ]
    assert path == [
        ("received", "verifying"),
        ("verifying", "verified"),
        ("verified", "in_progress"),
        ("in_progress", "fulfilled"),
    ]
