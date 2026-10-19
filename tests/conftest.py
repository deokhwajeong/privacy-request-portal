from __future__ import annotations

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import clock
from app.config import Settings, override_settings
from app.db import create_all, init_engine, new_session
from app.main import app
from app.notifier import outbox
from app.seed import seed

STAFF = {"X-Staff-Key": "test-staff-key", "X-Actor": "analyst.kim"}
T0 = datetime(2026, 3, 2, 9, 0)  # a Monday

# Fictional seeded accounts (see app/seed.py).
EU = {"email": "mara.lindqvist@example.com", "account_id": "ACC-10021", "last4": "4471"}
CA = {"email": "ava.holloway@example.com", "account_id": "ACC-10025", "last4": "7713"}


@pytest.fixture(autouse=True)
def env(tmp_path):
    override_settings(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'test.db'}",
            staff_api_key="test-staff-key",
            pseudonym_key="test-pseudonym-key",
            seed_reference_data=True,
        )
    )
    init_engine()
    create_all()
    with new_session() as db:
        seed(db)
    clock.freeze(T0)
    outbox.clear()
    yield
    clock.unfreeze()
    override_settings(None)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    with new_session() as s:
        yield s


def submit(client, who=EU, regime="gdpr", rtype="deletion"):
    r = client.post(
        "/v1/requests",
        json={
            "regime": regime,
            "request_type": rtype,
            "email": who["email"],
            "account_id": who["account_id"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def verify(client, created, who=EU, code=None, attr="__default__"):
    code = code or outbox.last_code(created["request_id"])
    body = {"ticket": created["ticket"], "code": code}
    body["account_attribute"] = who["last4"] if attr == "__default__" else attr
    return client.post(f"/v1/requests/{created['request_id']}/verify", json=body)


def verified_request(client, who=EU, regime="gdpr", rtype="deletion"):
    created = submit(client, who, regime, rtype)
    if rtype != "opt_out":
        r = verify(client, created, who)
        assert r.json()["outcome"] == "verified", r.text
    return created


def started_request(client, **kw):
    created = verified_request(client, **kw)
    r = client.post(f"/v1/requests/{created['request_id']}/start", headers=STAFF)
    assert r.status_code == 200, r.text
    return created, r.json()
