from __future__ import annotations

from uuid import uuid4, UUID

def new_id() -> UUID:
    """Return a new application-generated UUID."""
    return uuid4()

def parse_id(value: str | UUID) -> UUID:
    """Convert external input into a validated UUID."""
    if isinstance(value, UUID):
        return value

    try:
        return UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid UUID: {value!r}") from exc