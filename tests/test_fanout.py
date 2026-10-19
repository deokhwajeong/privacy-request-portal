from tests.conftest import CA, STAFF, started_request


def _req(client, rid):
    return client.get(f"/v1/requests/{rid}", headers=STAFF).json()


def test_deletion_fans_out_to_every_system_that_holds_data(client):
    _, req = started_request(client)
    systems = {t["system_key"] for t in req["tasks"]}
    assert systems == {
        "account-core",
        "viewing-activity",
        "ad-decisioning",
        "analytics-warehouse",
        "support-desk",
        "measurement-partner",
    }
    assert {t["action"] for t in req["tasks"]} == {"delete"}


def test_access_fans_out_as_export_and_skips_systems_not_in_scope(client):
    _, req = started_request(client, rtype="access")
    assert "measurement-partner" not in {t["system_key"] for t in req["tasks"]}
    assert {t["action"] for t in req["tasks"]} == {"export"}


def test_task_due_never_exceeds_request_due(client):
    _, req = started_request(client)
    for t in req["tasks"]:
        assert t["due_at"] <= req["due_at"]


def test_per_system_confirmation_is_recorded(client):
    created, req = started_request(client)
    t = req["tasks"][0]
    r = client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": "DEL-778"}, headers=STAFF)
    assert r.json()["status"] == "confirmed"
    assert r.json()["confirmation_ref"] == "DEL-778"
    events = client.get(f"/v1/requests/{created['request_id']}/audit", headers=STAFF).json()
    conf = [e for e in events if e["action"] == "fanout.confirmed"]
    assert conf[0]["details"] == {
        "system": t["system_key"],
        "action": "delete",
        "confirmation_ref": "DEL-778",
    }


def test_confirm_twice_conflicts(client):
    _, req = started_request(client)
    tid = req["tasks"][0]["id"]
    client.post(f"/v1/tasks/{tid}/confirm", json={"confirmation_ref": "a-1"}, headers=STAFF)
    assert (
        client.post(f"/v1/tasks/{tid}/confirm", json={"confirmation_ref": "a-2"}, headers=STAFF).status_code
        == 409
    )


def test_failure_blocks_completion_until_retried_and_confirmed(client):
    created, req = started_request(client)
    rid = created["request_id"]
    failing, *rest = req["tasks"]
    client.post(f"/v1/tasks/{failing['id']}/fail", json={"detail": "partner API 503"}, headers=STAFF)
    for t in rest:
        client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF)
    state = _req(client, rid)
    assert state["status"] == "in_progress"
    assert state["sla"] == "at_risk"  # failed downstream task escalates
    # Failed tasks must be retried before confirmation.
    assert (
        client.post(
            f"/v1/tasks/{failing['id']}/confirm", json={"confirmation_ref": "x-early"}, headers=STAFF
        ).status_code
        == 409
    )
    r = client.post(f"/v1/tasks/{failing['id']}/retry", headers=STAFF)
    assert r.json()["attempts"] == 2
    client.post(f"/v1/tasks/{failing['id']}/confirm", json={"confirmation_ref": "c-retry"}, headers=STAFF)
    assert _req(client, rid)["status"] == "fulfilled"


def test_exemption_with_legal_basis_counts_as_resolved(client):
    created, req = started_request(client)
    rid = created["request_id"]
    for t in req["tasks"]:
        if t["system_key"] == "support-desk":
            client.post(
                f"/v1/tasks/{t['id']}/exempt",
                json={"legal_basis": "GDPR Art. 17(3)(b): warranty records under legal obligation"},
                headers=STAFF,
            )
        else:
            client.post(
                f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF
            )
    state = _req(client, rid)
    assert state["status"] == "fulfilled"
    events = client.get(f"/v1/requests/{rid}/audit", headers=STAFF).json()
    done = [e for e in events if e["details"].get("to") == "fulfilled"][0]
    assert done["details"]["systems_exempt"] == 1


def test_opt_out_suppresses_downstream_and_flips_consent(client):
    created, req = started_request(client, who=CA, regime="ccpa", rtype="opt_out")
    assert {t["system_key"] for t in req["tasks"]} == {"ad-decisioning", "measurement-partner"}
    assert {t["action"] for t in req["tasks"]} == {"suppress"}
    consent = {c["purpose"]: c for c in client.get(f"/v1/consent/{CA['account_id']}").json()}
    assert consent["sale_share"]["granted"] is False
    assert consent["sale_share"]["source"] == "dsr_opt_out"
    r = client.post(
        "/v1/collect", json={"account_id": CA["account_id"], "purpose": "sale_share", "event_type": "x"}
    )
    assert r.status_code == 409


def test_register_new_system_and_include_in_fanout(client):
    r = client.post(
        "/v1/systems",
        json={
            "key": "email-marketing",
            "name": "Email marketing platform",
            "owner": "Lifecycle Marketing",
            "operated_by": "vendor",
            "data_categories": ["contact"],
            "supports": ["deletion", "opt_out"],
        },
        headers=STAFF,
    )
    assert r.status_code == 201
    _, req = started_request(client)
    assert "email-marketing" in {t["system_key"] for t in req["tasks"]}
