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
        action=event.action.value,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        correlation_id=event.correlation_id,
        event_hash=event.event_hash,
        source_metadata_json=(
            dict(event.source_metadata_json)
            if event.source_metadata_json is not None
            else None
        ),
        # TODO: Add remaining fields...
    )


def audit_event_to_domain(row: AuditEventRow) -> AuditEvent:
    return AuditEvent(
        audit_event_id=row.audit_event_id,
        occurred_at=as_utc(row.occurred_at),
        session_id=row.session_id,
        actor_type=ActorType(row.actor_type),
        action=AuditAction(row.action),
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        correlation_id=row.correlation_id,
        event_hash=row.event_hash,
        source_metadata_json=row.source_metadata_json,
        # TODO: Add remaining fields...
    )