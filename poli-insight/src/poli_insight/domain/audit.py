from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from poli_insight.core.time import is_aware_datetime
from poli_insight.domain.enum import ActorType, AuditAction

JsonObject = Mapping[str, Any]
JsonPatch = tuple[Mapping[str, Any], ...]

class AuditRuleViolation(ValueError):
    """Raised when an operation violates audit event business rules."""
    pass

@dataclass(frozen=True, slots=True)
class AuditEvent:
    # Required identity and event facts
    audit_event_id: str
    occurred_at: datetime
    actor_type: ActorType
    action: AuditAction
    entity_type: str
    entity_id: str
    correlation_id: str
    event_hash: str

    # Optional context
    session_id: str | None = None
    actor_id: str | None = None
    actor_display_snapshot: str | None = None
    request_id: str | None = None
    reason_code: str | None = None
    reason_text: str | None = None

    # Secret-filtered state projections
    before_json: JsonObject | None = None
    after_json: JsonObject | None = None
    patch_json: JsonPatch | None = None

    # Event lineage and source information
    causation_event_id: str | None = None
    source_metadata_json: JsonObject | None = None
    previous_event_hash: str | None = None

    schema_version: int = 1

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_occurred_at()
        self._validate_schema_version()

    def _validate_identity(self) -> None:
        if not self.audit_event_id.strip():
            raise AuditRuleViolation(
                "Audit Event ID cannot be empty."
            )

        if not self.entity_type.strip():
            raise AuditRuleViolation(
                "Entity Type cannot be empty."
            )

        if not self.entity_id.strip():
            raise AuditRuleViolation(
                "Entity ID cannot be empty."
            )

        if not self.correlation_id.strip():
            raise AuditRuleViolation(
                "Correlation ID cannot be empty."
            )

        if not self.event_hash.strip():
            raise AuditRuleViolation(
                "Event Hash cannot be empty."
            )

    def _validate_schedule(self) -> None:
        if is_aware_datetime(self.occurred_at):
            raise AuditRuleViolation(
                "Occurred_at must include timezone information."
            )

    def _validate_schema_version(self) -> None:
        if self.schema_version < 1:
            raise AuditRuleViolation(
                "Schema Version cannot be less than 0."
            )