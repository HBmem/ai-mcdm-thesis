from __future__ import annotations

from poli_insight.core.time import as_utc
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.enum import AuditAction, ActorType
from poli_insight.infrastructure.database.models.audit import AuditEventRow

def audit_event_to_row(event: AuditEvent) -> AuditEventRow:
    return AuditEventRow(
        audit_event_id=event.audit_event_id,
        occurred_at=event.occurred_at,
        session_id=event.session_id,
        actor_type=event.actor_type.value,
        actor_id=event.actor_id,
        actor_display_snapshot=event.actor_display_snapshot,
        action=event.action.value,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        reason_code=event.reason_code,
        reason_text=event.reason_text,
        before_json=(
            dict(event.before_json)
            if event.before_json is not None
            else None
        ),
        after_json=(
            dict(event.after_json)
            if event.after_json is not None
            else None
        ),
        patch_json=(
            [dict(operation) for operation in event.patch_json]
            if event.patch_json is not None
            else None
        ),
        request_id=event.request_id,
        correlation_id=event.correlation_id,
        causation_event_id=event.causation_event_id,
        source_metadata_json=(
            dict(event.source_metadata_json)
            if event.source_metadata_json is not None
            else None
        ),
        previous_event_hash=event.previous_event_hash,
        event_hash=event.event_hash,
        schema_version=event.schema_version,
    )


def audit_event_to_domain(row: AuditEventRow) -> AuditEvent:
    occurred_at = as_utc(row.occurred_at)
    if occurred_at is None:
        raise ValueError("Persisted audit event is missing occurred_at.")

    return AuditEvent(
        audit_event_id=str(row.audit_event_id),
        occurred_at=occurred_at,
        session_id=(
            str(row.session_id)
            if row.session_id is not None
            else None
        ),
        actor_type=ActorType(row.actor_type),
        actor_id=row.actor_id,
        actor_display_snapshot=row.actor_display_snapshot,
        action=AuditAction(row.action),
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        reason_code=row.reason_code,
        reason_text=row.reason_text,
        before_json=row.before_json,
        after_json=row.after_json,
        patch_json=(
            tuple(row.patch_json)
            if row.patch_json is not None
            else None
        ),
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        causation_event_id=(
            str(row.causation_event_id)
            if row.causation_event_id is not None
            else None
        ),
        source_metadata_json=row.source_metadata_json,
        previous_event_hash=row.previous_event_hash,
        event_hash=row.event_hash,
        schema_version=row.schema_version,
    )
