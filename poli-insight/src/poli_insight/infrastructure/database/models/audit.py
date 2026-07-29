from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from poli_insight.infrastructure.database.base import Base


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    audit_event_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    session_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    entity_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    correlation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    event_hash: Mapped[str] = mapped_column(
        String(256),
        nullable=False,
    )
    before_json: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )
    event_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    source_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )

    # TODO: Add remaining fields