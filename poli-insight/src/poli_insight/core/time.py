from __future__ import annotations

from datetime import datetime, UTC

def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)

def as_utc(value: datetime | None) -> datetime | None:
    """Convert an aware datetime to UTC.

    Naive datetimes are rejected because their original timezone
    cannot be determined safely.
    """
    if value is None:
        return None

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include timezone information.")

    return value.astimezone(UTC)

def is_aware_datetime( value: datetime | None) -> bool:
    if value is not None and value.tzinfo is None:
        return False

    return True
