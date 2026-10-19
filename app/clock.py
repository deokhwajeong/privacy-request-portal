"""Single source of time so deadline logic is testable and the demo is reproducible."""

from __future__ import annotations

from datetime import UTC, datetime

_frozen: datetime | None = None


def now() -> datetime:
    """Current time as a naive UTC datetime (SQLite stores naive values)."""
    if _frozen is not None:
        return _frozen
    return datetime.now(UTC).replace(tzinfo=None)


def freeze(at: datetime) -> None:
    global _frozen
    _frozen = at.replace(tzinfo=None) if at.tzinfo else at


def unfreeze() -> None:
    global _frozen
    _frozen = None
