"""Build the static demo from real service output.

Runs the FastAPI app in-process against a throwaway SQLite file, replays a
schedule of synthetic requests through the public and staff APIs with a
controlled clock, then writes the API responses to data.js next to the static
page. Nothing in the page is hand-entered: every number, status, deadline, and
audit hash comes from the service.

    python demo/build.py --out demo/dist
"""

from __future__ import annotations

import argparse
import itertools
import json
import shutil
import sys
import tempfile
import warnings
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
warnings.filterwarnings("ignore", message=".*httpx.*")
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app import clock, service  # noqa: E402
from app.config import Settings, override_settings  # noqa: E402
from app.db import create_all, init_engine, new_session  # noqa: E402
from app.main import app  # noqa: E402
from app.notifier import outbox  # noqa: E402
from app.seed import ACCOUNTS, seed  # noqa: E402

AS_OF = datetime(2026, 10, 15, 16, 0)
STAFF_KEY = "demo-staff-key"
ACCT = {a[0]: {"email": a[1], "last4": a[3]} for a in ACCOUNTS}

Step = tuple[datetime, str, Callable[[], None]]


def dt(month: int, day: int, hour: int = 10, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute)


class Demo:
    def __init__(self, client: TestClient) -> None:
        self.c = client
        self.cases: dict[str, dict] = {}
        self.steps: list[Step] = []

    # ----------------------------------------------------------------- helpers
    def staff(self, actor: str) -> dict:
        return {"X-Staff-Key": STAFF_KEY, "X-Actor": actor}

    def at(self, when: datetime, label: str, fn: Callable[[], None]) -> None:
        self.steps.append((when, label, fn))

    def _ok(self, r, label: str) -> dict:
        if r.status_code >= 300:
            raise RuntimeError(f"{label}: {r.status_code} {r.text}")
        return r.json()

    def submit(
        self, case: str, regime: str, rtype: str, account: str, email: str | None = None, channel="web_form"
    ):
        def go() -> None:
            body = {
                "regime": regime,
                "request_type": rtype,
                "email": email or ACCT[account]["email"],
                "account_id": account,
                "channel": channel,
            }
            out = self._ok(self.c.post("/v1/requests", json=body), f"{case} submit")
            self.cases[case] = {**out, "account": account}

        return go

    def verify(self, case: str, code: str | None = None, attr: str | None = "__real__"):
        def go() -> None:
            info = self.cases[case]
            real = outbox.last_code(info["request_id"])
            body = {
                "ticket": info["ticket"],
                "code": code or real or "000000",
                "account_attribute": ACCT[info["account"]]["last4"] if attr == "__real__" else attr,
            }
            r = self.c.post(f"/v1/requests/{info['request_id']}/verify", json=body)
            self._ok(r, f"{case} verify")

        return go

    def resend(self, case: str):
        def go() -> None:
            info = self.cases[case]
            r = self.c.post(f"/v1/requests/{info['request_id']}/resend-code", json={"ticket": info["ticket"]})
            self._ok(r, f"{case} resend")

        return go

    def start(self, case: str, actor: str):
        def go() -> None:
            rid = self.cases[case]["request_id"]
            out = self._ok(
                self.c.post(f"/v1/requests/{rid}/start", headers=self.staff(actor)), f"{case} start"
            )
            self.cases[case]["tasks"] = {t["system_key"]: t["id"] for t in out["tasks"]}

        return go

    def task(self, case: str, system: str, op: str, actor: str, **body):
        def go() -> None:
            tid = self.cases[case]["tasks"][system]
            r = self.c.post(f"/v1/tasks/{tid}/{op}", json=body or None, headers=self.staff(actor))
            self._ok(r, f"{case} {system} {op}")

        return go

    def confirm(self, case: str, system: str, ref: str):
        return self.task(case, system, "confirm", f"system:{system}", confirmation_ref=ref)

    def extend(self, case: str, reason: str, actor: str):
        def go() -> None:
            rid = self.cases[case]["request_id"]
            r = self.c.post(f"/v1/requests/{rid}/extend", json={"reason": reason}, headers=self.staff(actor))
            self._ok(r, f"{case} extend")

        return go

    def admin(self, path: str):
        def go() -> None:
            self._ok(self.c.post(f"/v1/admin/{path}", headers=self.staff("scheduler")), path)

        return go

    def raw(self, method: str, path: str, actor: str | None = None, **body):
        def go() -> None:
            headers = self.staff(actor) if actor else None
            r = self.c.request(method, path, json=body or None, headers=headers)
            if r.status_code >= 400 and r.status_code != 409:
                raise RuntimeError(f"{path}: {r.status_code} {r.text}")

        return go

    def run(self) -> None:
        for when, _label, fn in sorted(self.steps, key=lambda s: s[0]):
            assert when <= AS_OF, _label
            clock.freeze(when)
            fn()
        clock.freeze(AS_OF)


def schedule(d: Demo) -> None:
    lead, analyst, counsel = "privacy.lead", "analyst.rivera", "counsel.eu"

    # ---- GDPR ---------------------------------------------------------------
    # G1 deletion, fulfilled on time with one documented exemption.
    d.at(dt(9, 10, 8, 12), "G1", d.submit("G1", "gdpr", "deletion", "ACC-10021", channel="tv_settings"))
    d.at(dt(9, 10, 8, 19), "G1v", d.verify("G1"))
    d.at(dt(9, 11, 9, 5), "G1s", d.start("G1", analyst))
    for i, (sys_, day) in enumerate(
        [("account-core", 12), ("viewing-activity", 15), ("ad-decisioning", 15), ("analytics-warehouse", 18)]
    ):
        d.at(dt(9, day, 11, i), f"G1c{i}", d.confirm("G1", sys_, f"DEL-{4100 + i}"))
    d.at(dt(9, 17, 14), "G1m", d.confirm("G1", "measurement-partner", "MP-88213"))
    d.at(
        dt(9, 19, 10),
        "G1x",
        d.task(
            "G1",
            "support-desk",
            "exempt",
            counsel,
            legal_basis="GDPR Art. 17(3)(b): warranty claim records held under legal obligation, access restricted",
        ),
    )

    # G2 access, in progress with a few days left: at risk.
    d.at(dt(9, 20, 17, 40), "G2", d.submit("G2", "gdpr", "access", "ACC-10022"))
    d.at(dt(9, 21, 7, 50), "G2r", d.resend("G2"))
    d.at(dt(9, 21, 7, 55), "G2v", d.verify("G2"))
    d.at(dt(9, 22, 9, 30), "G2s", d.start("G2", analyst))
    d.at(dt(9, 23, 10), "G2c1", d.confirm("G2", "account-core", "EXP-2201"))
    d.at(dt(9, 26, 15), "G2c2", d.confirm("G2", "viewing-activity", "EXP-2202"))
    d.at(dt(10, 2, 12), "G2c3", d.confirm("G2", "ad-decisioning", "EXP-2203"))

    # G3 deletion, recently started, on time.
    d.at(dt(10, 9, 20, 3), "G3", d.submit("G3", "gdpr", "deletion", "ACC-10023"))
    d.at(dt(10, 9, 20, 9), "G3v", d.verify("G3"))
    d.at(dt(10, 12, 9, 15), "G3s", d.start("G3", analyst))
    d.at(dt(10, 13, 10), "G3c1", d.confirm("G3", "account-core", "DEL-4188"))
    d.at(dt(10, 14, 16), "G3c2", d.confirm("G3", "viewing-activity", "DEL-4189"))

    # G4 deletion, extended after a downstream failure; failure still open so flagged at risk.
    d.at(dt(8, 14, 13), "G4", d.submit("G4", "gdpr", "deletion", "ACC-10024"))
    d.at(dt(8, 14, 13, 9), "G4v", d.verify("G4"))
    d.at(dt(8, 15, 9), "G4s", d.start("G4", analyst))
    d.at(dt(8, 18, 11), "G4c1", d.confirm("G4", "account-core", "DEL-3920"))
    d.at(dt(8, 21, 11), "G4c2", d.confirm("G4", "viewing-activity", "DEL-3921"))
    d.at(
        dt(8, 22, 3),
        "G4f",
        d.task(
            "G4", "analytics-warehouse", "fail", "system:analytics-warehouse", detail="Partition lock timeout"
        ),
    )
    d.at(dt(8, 22, 9), "G4r", d.task("G4", "analytics-warehouse", "retry", analyst))
    d.at(dt(8, 27, 9), "G4c3", d.confirm("G4", "analytics-warehouse", "DEL-3930"))
    d.at(dt(8, 29, 10), "G4c4", d.confirm("G4", "support-desk", "SD-55102"))
    d.at(
        dt(9, 8, 16),
        "G4e",
        d.extend("G4", "Ad platform deletion requires backfill across archived partitions", lead),
    )
    d.at(
        dt(9, 30, 2),
        "G4f2",
        d.task("G4", "ad-decisioning", "fail", "system:ad-decisioning", detail="Archive restore job failed"),
    )
    d.at(dt(10, 1, 9), "G4m", d.confirm("G4", "measurement-partner", "MP-87001"))

    # G5 correction awaiting the requester's code.
    d.at(dt(10, 13, 21, 30), "G5", d.submit("G5", "gdpr", "correction", "ACC-10029"))

    # G6 objection (Art. 21) to sale/share style processing, fulfilled.
    d.at(dt(10, 1, 12), "G6", d.submit("G6", "gdpr", "opt_out", "ACC-10031", channel="tv_settings"))
    d.at(dt(10, 1, 12, 5), "G6s", d.start("G6", analyst))
    d.at(dt(10, 2, 9), "G6c1", d.confirm("G6", "ad-decisioning", "SUP-0091"))
    d.at(dt(10, 6, 9), "G6c2", d.confirm("G6", "measurement-partner", "MP-SUP-311"))

    # G7 access, verification attempts exhausted: denied.
    d.at(dt(9, 1, 22), "G7", d.submit("G7", "gdpr", "access", "ACC-10033"))
    for i in range(5):
        d.at(
            dt(9, 1, 22, 3 + i),
            f"G7f{i}",
            d.verify("G7", code=f"{111111 * (i + 1) % 1000000:06d}", attr="0000"),
        )

    # G8 deletion, vendor tasks still open past the deadline: breached.
    d.at(dt(9, 12, 10), "G8", d.submit("G8", "gdpr", "deletion", "ACC-10034", channel="support_agent"))
    d.at(dt(9, 12, 10, 8), "G8v", d.verify("G8"))
    d.at(dt(9, 16, 9), "G8s", d.start("G8", analyst))
    for i, sys_ in enumerate(["account-core", "viewing-activity", "ad-decisioning", "analytics-warehouse"]):
        d.at(dt(9, 18 + i, 10), f"G8c{i}", d.confirm("G8", sys_, f"DEL-{4300 + i}"))

    # G9 access, closed late (missed): kept in the stats, not hidden.
    d.at(dt(7, 20, 9), "G9", d.submit("G9", "gdpr", "access", "ACC-10036"))
    d.at(dt(7, 20, 9, 10), "G9v", d.verify("G9"))
    d.at(dt(7, 21, 9), "G9s", d.start("G9", analyst))
    for i, sys_ in enumerate(["account-core", "viewing-activity", "ad-decisioning", "analytics-warehouse"]):
        d.at(dt(7, 23 + i, 10), f"G9c{i}", d.confirm("G9", sys_, f"EXP-{1900 + i}"))
    d.at(dt(8, 24, 15), "G9c4", d.confirm("G9", "support-desk", "SD-54990"))

    # ---- CCPA ---------------------------------------------------------------
    # C1 deletion, partner confirmation outstanding with 3 days left: at risk.
    d.at(dt(9, 3, 18), "C1", d.submit("C1", "ccpa", "deletion", "ACC-10025"))
    d.at(dt(9, 3, 18, 6), "C1v", d.verify("C1"))
    d.at(dt(9, 4, 10), "C1s", d.start("C1", analyst))
    for i, sys_ in enumerate(
        ["account-core", "viewing-activity", "ad-decisioning", "analytics-warehouse", "support-desk"]
    ):
        d.at(dt(9, 7 + i * 2, 10), f"C1c{i}", d.confirm("C1", sys_, f"DEL-{5100 + i}"))

    # C2 opt-out of sale/sharing, partner still to confirm, on time.
    d.at(dt(10, 6, 19), "C2", d.submit("C2", "ccpa", "opt_out", "ACC-10026", channel="tv_settings"))
    d.at(dt(10, 7, 9), "C2s", d.start("C2", analyst))
    d.at(dt(10, 7, 14), "C2c1", d.confirm("C2", "ad-decisioning", "SUP-0102"))

    # C3 opt-out, fulfilled in three days.
    d.at(dt(9, 15, 8), "C3", d.submit("C3", "ccpa", "opt_out", "ACC-10027"))
    d.at(dt(9, 15, 9), "C3s", d.start("C3", analyst))
    d.at(dt(9, 16, 10), "C3c1", d.confirm("C3", "ad-decisioning", "SUP-0077"))
    d.at(dt(9, 18, 10), "C3c2", d.confirm("C3", "measurement-partner", "MP-SUP-290"))

    # C4 access, extended with notice before day 45, in progress.
    d.at(dt(8, 25, 11), "C4", d.submit("C4", "ccpa", "access", "ACC-10028"))
    d.at(dt(8, 25, 11, 6), "C4v", d.verify("C4"))
    d.at(dt(8, 26, 9), "C4s", d.start("C4", analyst))
    d.at(dt(8, 28, 9), "C4c1", d.confirm("C4", "account-core", "EXP-3101"))
    d.at(dt(9, 2, 9), "C4c2", d.confirm("C4", "viewing-activity", "EXP-3102"))
    d.at(
        dt(10, 1, 15),
        "C4e",
        d.extend("C4", "Support desk vendor export spans legacy ticketing archive", lead),
    )
    d.at(dt(10, 3, 9), "C4c3", d.confirm("C4", "ad-decisioning", "EXP-3103"))
    d.at(dt(10, 8, 9), "C4c4", d.confirm("C4", "analytics-warehouse", "EXP-3104"))

    # C5 deletion, fulfilled on time.
    d.at(dt(7, 28, 10), "C5", d.submit("C5", "ccpa", "deletion", "ACC-10030"))
    d.at(dt(7, 28, 10, 12), "C5v", d.verify("C5"))
    d.at(dt(7, 29, 9), "C5s", d.start("C5", analyst))
    for i, sys_ in enumerate(
        [
            "account-core",
            "viewing-activity",
            "ad-decisioning",
            "analytics-warehouse",
            "support-desk",
            "measurement-partner",
        ]
    ):
        d.at(dt(8, 1 + i * 3, 10), f"C5c{i}", d.confirm("C5", sys_, f"DEL-{2800 + i}"))

    # C6 correction, verified, waiting to be picked up.
    d.at(dt(10, 14, 9), "C6", d.submit("C6", "ccpa", "correction", "ACC-10032"))
    d.at(dt(10, 14, 9, 4), "C6v", d.verify("C6", attr=None))

    # C7 deletion where the email does not match the account: code never sent, closed by the sweep.
    d.at(
        dt(8, 20, 23),
        "C7",
        d.submit("C7", "ccpa", "deletion", "ACC-10035", email="someone.else@example.net"),
    )
    d.at(dt(9, 4, 2), "sweep1", d.admin("sweep"))

    # C8 deletion just received this morning.
    d.at(dt(10, 15, 8, 40), "C8", d.submit("C8", "ccpa", "deletion", "ACC-10035"))

    # ---- Consent and collection ---------------------------------------------
    a = "ACC-10025"
    d.at(
        dt(9, 1, 8),
        "k1",
        d.raw("PUT", f"/v1/consent/{a}/viewing_information", granted=True, source="first_run"),
    )
    d.at(
        dt(9, 1, 8, 1),
        "k2",
        d.raw("PUT", f"/v1/consent/{a}/voice_recordings", granted=True, source="first_run"),
    )
    for i in range(6):
        d.at(
            dt(9, 2 + i, 20),
            f"k3{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="viewing_information", event_type="acr"),
        )
        d.at(
            dt(9, 2 + i, 20, 5),
            f"k4{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="voice_recordings", event_type="utt"),
        )
        d.at(
            dt(9, 2 + i, 21),
            f"k5{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="personalized_ads", event_type="imp"),
        )
        d.at(
            dt(9, 2 + i, 21, 5),
            f"k6{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="diagnostics", event_type="crash"),
        )
    d.at(
        dt(9, 8, 9),
        "k7",
        d.raw("PUT", f"/v1/consent/{a}/viewing_information", granted=False, source="settings_menu"),
    )
    d.at(
        dt(9, 9, 11),
        "k8",
        d.raw(
            "POST",
            "/v1/purposes/voice_recordings/halt",
            actor=lead,
            reason="Review vendor retention terms before resuming",
        ),
    )
    for i in range(4):
        d.at(
            dt(9, 10 + i, 20),
            f"k9{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="viewing_information", event_type="acr"),
        )
        d.at(
            dt(9, 10 + i, 20, 5),
            f"k10{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="voice_recordings", event_type="utt"),
        )
        d.at(
            dt(9, 10 + i, 21, 5),
            f"k11{i}",
            d.raw("POST", "/v1/collect", account_id=a, purpose="diagnostics", event_type="crash"),
        )

    # ---- Housekeeping ---------------------------------------------------------
    d.at(dt(10, 15, 2), "retention", d.admin("retention"))
    d.at(dt(10, 15, 2, 5), "sweep2", d.admin("sweep"))


def collect_output(d: Demo) -> dict:
    s = d.staff("demo.export")
    get = lambda p: d._ok(d.c.get(p, headers=s), p)  # noqa: E731
    dashboard = get("/v1/sla/dashboard")
    ids = [r["id"] for r in dashboard["queue"] + dashboard["closed"]]
    details = {rid: get(f"/v1/requests/{rid}") for rid in ids}
    audits = {rid: get(f"/v1/requests/{rid}/audit") for rid in ids}
    return {
        "generated_from": "privacy-request-portal service, synthetic data",
        "as_of": AS_OF.isoformat(timespec="minutes"),
        "dashboard": dashboard,
        "requests": details,
        "audit": audits,
        "audit_verify": get("/v1/audit/verify"),
        "systems": get("/v1/systems"),
        "purposes": d._ok(d.c.get("/v1/purposes"), "purposes"),
        "collection": get("/v1/collection/stats"),
        "cases": {k: v["request_id"] for k, v in sorted(d.cases.items())},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "demo" / "dist"))
    args = ap.parse_args()
    out = Path(args.out)

    counter = itertools.count(1)
    service._new_request_id = lambda received: f"DSR-{received:%y%m}-{next(counter):04d}"

    with tempfile.TemporaryDirectory() as tmp:
        override_settings(
            Settings(
                database_url=f"sqlite:///{tmp}/demo.db",
                staff_api_key=STAFF_KEY,
                pseudonym_key="demo-pseudonym-key",
                seed_reference_data=True,
            )
        )
        init_engine()
        create_all()
        with new_session() as db:
            seed(db)
        with TestClient(app) as client:
            demo = Demo(client)
            schedule(demo)
            demo.run()
            data = collect_output(demo)
        clock.unfreeze()

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ROOT / "demo" / "src", out)
    payload = json.dumps(data, indent=1, sort_keys=True)
    (out / "data.js").write_text(f"window.PRP_DATA = {payload};\n", encoding="utf-8")
    n = len(data["requests"])
    print(f"built {out} with {n} requests, {data['audit_verify']['events']} audit events")


if __name__ == "__main__":
    main()
