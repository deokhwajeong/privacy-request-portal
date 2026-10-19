from datetime import timedelta

from app import clock
from tests.conftest import CA, EU, STAFF, T0, started_request, submit, verified_request


def _sla(client, rid):
    return client.get(f"/v1/requests/{rid}", headers=STAFF).json()["sla"]


def test_on_time_then_at_risk_then_breached(client):
    rid = verified_request(client)["request_id"]  # GDPR: received 2 Mar, due 2 Apr
    assert _sla(client, rid) == "on_time"
    clock.freeze(T0 + timedelta(days=24))  # 26 Mar: 7 days left, threshold ceil(31 * .25) = 8
    assert _sla(client, rid) == "at_risk"
    clock.freeze(T0 + timedelta(days=31, hours=15))  # 3 Apr 00:00
    assert _sla(client, rid) == "breached"


def test_extension_moves_request_back_on_time(client):
    rid = verified_request(client)["request_id"]
    clock.freeze(T0 + timedelta(days=25))
    assert _sla(client, rid) == "at_risk"
    client.post(f"/v1/requests/{rid}/extend", json={"reason": "Complex: 6 systems, 2 vendors"}, headers=STAFF)
    assert _sla(client, rid) == "on_time"


def test_closed_requests_are_met_or_missed(client):
    created, req = started_request(client)
    for t in req["tasks"]:
        client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF)
    assert _sla(client, created["request_id"]) == "met"

    created, req = started_request(client, who=CA, regime="ccpa")
    clock.freeze(T0 + timedelta(days=50))
    for t in req["tasks"]:
        client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF)
    assert _sla(client, created["request_id"]) == "missed"


def test_overdue_downstream_task_flags_at_risk(client):
    created, _ = started_request(client)  # account-core confirmation SLA is 3 days
    clock.freeze(T0 + timedelta(days=4))
    body = client.get("/v1/sla/dashboard", headers=STAFF).json()
    row = next(r for r in body["queue"] if r["id"] == created["request_id"])
    assert row["sla"] == "at_risk"
    assert "account-core" in row["blocked_systems"]


def test_dashboard_aggregates_by_regime(client):
    created, req = started_request(client)
    for t in req["tasks"]:
        client.post(f"/v1/tasks/{t['id']}/confirm", json={"confirmation_ref": f"c-{t['id']}"}, headers=STAFF)
    submit(client, CA, "ccpa", "access")
    submit(client, CA, "ccpa", "opt_out")
    submit(client, EU, "gdpr", "correction")
    body = client.get("/v1/sla/dashboard", headers=STAFF).json()
    assert body["by_regime"]["gdpr"]["total"] == 2
    assert body["by_regime"]["gdpr"]["fulfilled"] == 1
    assert body["by_regime"]["gdpr"]["on_time_rate"] == 1.0
    assert body["by_regime"]["ccpa"]["total"] == 2
    assert body["by_regime"]["ccpa"]["by_type"] == {"access": 1, "opt_out": 1}
    assert sum(body["open_sla"].values()) == len(body["queue"]) == 3
    assert body["status_counts"]["fulfilled"] == 1
