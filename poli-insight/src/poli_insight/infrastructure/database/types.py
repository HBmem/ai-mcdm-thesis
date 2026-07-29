from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import CHAR, DateTime
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

class UUIDString(TypeDecorator[UUID]):
    """Store UUID objects as portable 36-character strings."""

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(
        self,
        value: UUID | str | None,
        dialect: Dialect,
    ) -> str | None:
        if value is None:
            return None

        if not isinstance(value, UUID):
            value = UUID(str(value))

        return str(value)

    def process_result_value(
        self,
        value: str | UUID | None,
        dialect: Dialect,
    ) -> UUID | None:
        if value is None:
            return None

        if isinstance(value, UUID):
            return value

        return UUID(value)

class UTCDateTime(TypeDecorator[datetime]):
    """Store aware timestamps in UTC and return aware UTC values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Database timestamps must include timezone information."
            )

        return value.astimezone(UTC)

    def process_result_value(
        self,
        value: datetime | None,
        dialect: Dialect,
    ) -> datetime | None:
        if value is None:
            return None

        # SQLite can return a naive value even though the application
        # normalized it to UTC before storage.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)

        return value.astimezone(UTC)