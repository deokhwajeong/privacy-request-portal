"""Runtime settings, read from environment variables with safe local defaults.

Secrets here are development placeholders. A real deployment injects them from a
secrets manager and rotates the pseudonymization key under a documented procedure
(rotating it breaks linkage of old audit entries, which is acceptable and sometimes desired).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("PRP_DATABASE_URL", "sqlite:///./prp.db"))
    staff_api_key: str = field(default_factory=lambda: os.getenv("PRP_STAFF_API_KEY", "dev-staff-key"))
    pseudonym_key: str = field(
        default_factory=lambda: os.getenv("PRP_PSEUDONYM_KEY", "dev-only-pseudonym-key-change-me")
    )
    seed_reference_data: bool = field(default_factory=lambda: os.getenv("PRP_SEED", "1") == "1")

    # Verification controls (see docs/design-decisions.md, "Risk-based verification").
    code_ttl_minutes: int = field(default_factory=lambda: _env_int("PRP_CODE_TTL_MINUTES", 15))
    max_code_attempts: int = field(default_factory=lambda: _env_int("PRP_MAX_CODE_ATTEMPTS", 5))
    max_challenges: int = field(default_factory=lambda: _env_int("PRP_MAX_CHALLENGES", 3))
    verification_window_days: int = field(
        default_factory=lambda: _env_int("PRP_VERIFICATION_WINDOW_DAYS", 14)
    )

    # Minimization: contact email is redacted from closed requests after this many days.
    # The request record itself (no direct identifiers) is kept for the record-keeping period.
    contact_retention_days: int = field(default_factory=lambda: _env_int("PRP_CONTACT_RETENTION_DAYS", 30))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def override_settings(settings: Settings | None) -> None:
    """Used by tests and the demo builder."""
    global _settings
    _settings = settings
