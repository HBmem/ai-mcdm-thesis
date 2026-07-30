from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from poli_insight.domain.enum import ActorType, AuditAction
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


def _enum_sql_values(enum_type: type[StrEnum]) -> str:
    """Return trusted enum values formatted for a SQL CHECK constraint."""

    return ", ".join(f"'{member.value}'" for member in enum_type)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            f"actor_type IN ({_enum_sql_values(ActorType)})",
            name="ck_audit_events_actor_type_allowed",
        ),
        CheckConstraint(
            f"action IN ({_enum_sql_values(AuditAction)})",
            name="ck_audit_events_action_allowed",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_audit_events_schema_version_positive",
        ),
        CheckConstraint(
            "length(event_hash) = 64",
            name="ck_audit_events_event_hash_length",
        ),
        CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_audit_events_previous_hash_length",
        ),
        CheckConstraint(
            "length(trim(entity_type)) > 0",
            name="ck_audit_events_entity_type_nonempty",
        ),
        CheckConstraint(
            "length(trim(entity_id)) > 0",
            name="ck_audit_events_entity_id_nonempty",
        ),
        CheckConstraint(
            "length(trim(correlation_id)) > 0",
            name="ck_audit_events_correlation_id_nonempty",
        ),
        Index(
            "ix_audit_events_session_occurred",
            "session_id",
            "occurred_at",
        ),
        Index("ix_audit_events_correlation_id", "correlation_id"),
        Index(
            "ix_audit_events_entity",
            "entity_type",
            "entity_id",
            "occurred_at",
        ),
        Index(
            "ix_audit_events_action_occurred",
            "action",
            "occurred_at",
        ),
        Index("ix_audit_events_causation_event_id", "causation_event_id"),
    )

    audit_event_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    session_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )

    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    actor_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    actor_display_snapshot: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
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

    reason_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    reason_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    before_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    after_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    patch_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )

    request_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    correlation_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    causation_event_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "audit_events.audit_event_id",
            name="fk_audit_events_causation_event_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    source_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )

    previous_event_hash: Mapped[str | None] = mapped_column(
        String(64),
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
        server_default="1",
    )
