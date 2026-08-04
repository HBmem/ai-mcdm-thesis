"""Shared construction for secret-filtered operational audit events."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import ActorType, AuditAction


def operational_audit_event(
    *,
    event_id: str,
    occurred_at: datetime,
    session_id: str,
    actor_id: str,
    actor_type: ActorType,
    action: AuditAction,
    entity_type: str,
    entity_id: str,
    correlation_id: str,
    use_case: str,
    before_json: Mapping[str, Any] | None = None,
    after_json: Mapping[str, Any] | None = None,
    reason_text: str | None = None,
) -> AuditEvent:
    source = {"schema_version": 1, "use_case": use_case}
    manifest = {
        "audit_event_id": event_id,
        "occurred_at": occurred_at,
        "session_id": session_id,
        "actor_type": actor_type.value,
        "actor_id": actor_id,
        "action": action.value,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "correlation_id": correlation_id,
        "reason_text": reason_text,
        "before_json": before_json,
        "after_json": after_json,
        "source_metadata_json": source,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=occurred_at,
        session_id=session_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        correlation_id=correlation_id,
        reason_text=reason_text,
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source,
        event_hash=hash_json(manifest),
    )
