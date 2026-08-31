"""One clock, so tests can freeze time and every timestamp is timezone-aware."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    return datetime.now(UTC)


def isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def as_aware(value: datetime | None) -> datetime | None:
    """Normalise a value read back from the database.

    PostgreSQL round-trips ``timestamptz`` as timezone-aware, SQLite does not.
    Anything that does arithmetic on a stored timestamp goes through here so the
    two engines behave identically.
    """
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
