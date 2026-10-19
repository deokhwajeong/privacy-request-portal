"""SLA classification and dashboard aggregates.

Open requests:
  breached  now is past the (possibly extended) statutory due date
  at_risk   inside the final quarter of the window (min 3 days), or a downstream task failed or is overdue
  on_time   otherwise
Closed requests:
  met       closed on or before the due date in force at closure
  missed    closed after it
"""

from __future__ import annotations

import math
from datetime import datetime
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import clock
from app.models import DsrRequest, FulfillmentTask, Status, TaskStatus


def at_risk_threshold_days(req: DsrRequest) -> int:
    window = (req.due_at.date() - req.received_at.date()).days
    return max(3, math.ceil(window * 0.25))


def blocked_tasks(req: DsrRequest, now: datetime) -> list[FulfillmentTask]:
    return [
        t
        for t in req.tasks
        if t.status == TaskStatus.FAILED or (t.status == TaskStatus.PENDING and t.due_at < now)
    ]


def classify(req: DsrRequest, now: datetime | None = None) -> str:
    now = now or clock.now()
    if req.is_closed:
        assert req.closed_at is not None
        return "met" if req.closed_at <= req.due_at else "missed"
    if now > req.due_at:
        return "breached"
    remaining = (req.due_at.date() - now.date()).days
    if remaining <= at_risk_threshold_days(req) or blocked_tasks(req, now):
        return "at_risk"
    return "on_time"


def days_remaining(req: DsrRequest, now: datetime | None = None) -> int:
    now = now or clock.now()
    return (req.due_at.date() - now.date()).days


def request_row(req: DsrRequest, now: datetime) -> dict:
    return {
        "id": req.id,
        "regime": req.regime,
        "type": req.request_type,
        "status": req.status,
        "sla": classify(req, now),
        "received_at": req.received_at.isoformat(timespec="minutes"),
        "due_date": req.due_at.date().isoformat(),
        "days_remaining": None if req.is_closed else days_remaining(req, now),
        "extended": req.extended_at is not None,
        "tasks_total": len(req.tasks),
        "tasks_open": sum(1 for t in req.tasks if t.status in (TaskStatus.PENDING, TaskStatus.FAILED)),
        "blocked_systems": [t.system_key for t in blocked_tasks(req, now)],
        "closed_at": req.closed_at.isoformat(timespec="minutes") if req.closed_at else None,
        "denial_reason": req.denial_reason,
    }


def dashboard(db: Session) -> dict:
    now = clock.now()
    reqs = db.execute(select(DsrRequest).order_by(DsrRequest.due_at)).scalars().all()
    rows = [request_row(r, now) for r in reqs]
    open_rows = [r for r in rows if r["days_remaining"] is not None]

    by_regime: dict[str, dict] = {}
    for regime in sorted({r.regime for r in reqs}):
        group = [r for r in reqs if r.regime == regime]
        closed = [r for r in group if r.is_closed]
        durations = [(r.closed_at - r.received_at).total_seconds() / 86400 for r in closed if r.closed_at]
        met = sum(1 for r in closed if classify(r, now) == "met")
        by_type: dict[str, int] = {}
        for r in group:
            by_type[r.request_type] = by_type.get(r.request_type, 0) + 1
        by_regime[regime] = {
            "total": len(group),
            "open": len(group) - len(closed),
            "fulfilled": sum(1 for r in group if r.status == Status.FULFILLED),
            "denied": sum(1 for r in group if r.status == Status.DENIED),
            "extended": sum(1 for r in group if r.extended_at is not None),
            "on_time_rate": round(met / len(closed), 3) if closed else None,
            "median_days_to_close": round(median(durations), 1) if durations else None,
            "max_days_to_close": round(max(durations), 1) if durations else None,
            "breached_open": sum(1 for r in group if not r.is_closed and classify(r, now) == "breached"),
            "by_type": by_type,
        }

    sla_counts = {k: 0 for k in ("on_time", "at_risk", "breached")}
    for r in open_rows:
        sla_counts[r["sla"]] += 1
    status_counts: dict[str, int] = {}
    for r in rows:
        status_counts[r["status"]] = status_counts.get(r["status"], 0) + 1

    return {
        "as_of": now.isoformat(timespec="minutes"),
        "open_sla": sla_counts,
        "status_counts": status_counts,
        "by_regime": by_regime,
        "queue": open_rows,
        "closed": [r for r in rows if r["days_remaining"] is None],
    }
