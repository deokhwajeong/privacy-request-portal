"""Outbound requester notices.

The reference implementation keeps an in-memory outbox instead of sending mail.
Tests and the demo builder read verification codes from here; the API never
returns them. Swap Outbox for a mail provider adapter in a real deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app import clock


@dataclass
class Message:
    at: datetime
    to: str
    request_id: str
    kind: str  # acknowledgement | verification_code | extension_notice | denial_notice | completion
    body: str
    code: str | None = field(default=None, repr=False)


class Outbox:
    def __init__(self) -> None:
        self.messages: list[Message] = []

    def send(self, to: str, request_id: str, kind: str, body: str, code: str | None = None) -> None:
        self.messages.append(Message(clock.now(), to, request_id, kind, body, code))

    def last_code(self, request_id: str) -> str | None:
        for m in reversed(self.messages):
            if m.request_id == request_id and m.kind == "verification_code":
                return m.code
        return None

    def kinds(self, request_id: str) -> list[str]:
        return [m.kind for m in self.messages if m.request_id == request_id]

    def clear(self) -> None:
        self.messages.clear()


outbox = Outbox()
