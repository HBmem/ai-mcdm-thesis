from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.models.enum import ActorType, EntityType

@dataclass
class AuditEvent:
    audit_id: str
    session_id: str | None
    actor_type: ActorType
    actor_id: str | None
    action: str
    entity_id: str
    entity_type: EntityType
    before_json: str | None
    after_json: str | None
    reason: str | None
    created_at: datetime