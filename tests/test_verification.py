from datetime import timedelta

from app import clock
from app.notifier import outbox
from tests.conftest import CA, EU, STAFF, T0, submit, verify


def _req(client, rid):
    return client.get(f"/v1/requests/{rid}", headers=STAFF).json()


def test_wrong_code_counts_down_without_revealing_factor(client):
    created = submit(client)
    r = verify(
        client, created, code="123456" if outbox.last_code(created["request_id"]) != "123456" else "654321"
    )
    body = r.json()
    assert body == {"outcome": "failed", "status": "verifying", "attempts_remaining": 4}
    assert "factor" not in r.text


def test_lockout_after_max_attempts_denies(client):
    created = submit(client)
    real = outbox.last_code(created["request_id"])
    wrong = "111111" if real != "111111" else "222222"
    for _ in range(4):
        assert verify(client, created, code=wrong).json()["outcome"] == "failed"
    assert verify(client, created, code=wrong).json()["outcome"] == "locked"
    # Even the right code is useless after lockout.
    assert verify(client, created, code=real).status_code == 409
    req = _req(client, created["request_id"])
    assert req["denial_reason"] == "identity_not_verified"
    assert "denial_notice" in outbox.kinds(created["request_id"])


def test_high_tier_requires_account_attribute(client):
    created = submit(client, rtype="deletion")
    assert verify(client, created, attr=None).json()["outcome"] == "failed"
    assert verify(client, created, attr="0000").json()["outcome"] == "failed"
    assert verify(client, created).json()["outcome"] == "verified"


def test_access_is_high_tier(client):
    created = submit(client, rtype="access")
    assert _req(client, created["request_id"])["verification_tier"] == "high"
    assert verify(client, created, attr=None).json()["outcome"] == "failed"


def test_standard_tier_correction_needs_code_only(client):
    created = submit(client, CA, "ccpa", "correction")
    assert _req(client, created["request_id"])["verification_tier"] == "standard"
    assert verify(client, created, who=CA, attr=None).json()["outcome"] == "verified"


def test_expired_code_then_resend(client):
    created = submit(client)
    rid = created["request_id"]
    clock.freeze(T0 + timedelta(minutes=16))
    assert verify(client, created).json()["outcome"] == "expired"
    r = client.post(f"/v1/requests/{rid}/resend-code", json={"ticket": created["ticket"]})
    assert r.status_code == 202
    assert verify(client, created).json()["outcome"] == "verified"


def test_resend_supersedes_previous_code(client):
    created = submit(client)
    rid = created["request_id"]
    old = outbox.last_code(rid)
    client.post(f"/v1/requests/{rid}/resend-code", json={"ticket": created["ticket"]})
    new = outbox.last_code(rid)
    if old != new:
        assert verify(client, created, code=old).json()["outcome"] in ("failed", "expired")
    assert verify(client, created, code=new).json()["outcome"] == "verified"


def test_resend_limit(client):
    created = submit(client)
    rid = created["request_id"]
    for _ in range(2):
        assert (
            client.post(f"/v1/requests/{rid}/resend-code", json={"ticket": created["ticket"]}).status_code
            == 202
        )
    r = client.post(f"/v1/requests/{rid}/resend-code", json={"ticket": created["ticket"]})
    assert r.status_code == 409


def test_account_mismatch_is_indistinguishable_and_never_verifies(client):
    stranger = {"email": "not.on.file@example.org", "account_id": EU["account_id"], "last4": EU["last4"]}
    created = submit(client, stranger)
    legit = submit(client, EU)
    assert created.keys() == legit.keys()
    assert created["status"] == legit["status"] == "verifying"
    assert created["next_step"] == legit["next_step"]
    assert outbox.last_code(created["request_id"]) is None  # nothing was sent
    for code in ("000000", "123456", "999999"):
        assert verify(client, created, code=code).json()["outcome"] == "failed"
    events = client.get(f"/v1/requests/{created['request_id']}/audit", headers=STAFF).json()
    issued = next(e for e in events if e["action"] == "verification.challenge_issued")
    assert issued["details"]["delivered"] is False


def test_wrong_ticket_looks_like_unknown_request(client):
    created = submit(client)
    rid = created["request_id"]
    r = client.post(f"/v1/requests/{rid}/verify", json={"ticket": "nope", "code": "123456"})
    assert r.status_code == 404
    assert (
        client.post("/v1/requests/DSR-0000-XXXXXX/verify", json={"ticket": "x", "code": "123456"}).status_code
        == 404
    )


def test_verify_when_not_verifying_conflicts(client):
    created = submit(client)
    verify(client, created)
    assert verify(client, created).status_code == 409


def test_malformed_code_rejected_by_schema(client):
    created = submit(client)
    r = client.post(
        f"/v1/requests/{created['request_id']}/verify", json={"ticket": created["ticket"], "code": "12ab"}
    )
    assert r.status_code == 422


def test_public_status_requires_ticket(client):
    created = submit(client)
    rid = created["request_id"]
    ok = client.post(f"/v1/requests/{rid}/status", json={"ticket": created["ticket"]})
    assert ok.status_code == 200 and ok.json()["status"] == "verifying"
    assert client.post(f"/v1/requests/{rid}/status", json={"ticket": "guess"}).status_code == 404


def test_failed_attempts_record_factor_for_investigators_only(client):
    created = submit(client)
    verify(client, created, attr="0000")
    events = client.get(f"/v1/requests/{created['request_id']}/audit", headers=STAFF).json()
    failed = next(e for e in events if e["action"] == "verification.failed")
    assert failed["details"]["failed_factors"] == ["account_attribute"]
