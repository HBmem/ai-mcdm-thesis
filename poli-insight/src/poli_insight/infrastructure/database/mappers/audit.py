from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from poli_insight.core.time import as_utc
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import canonical_json_bytes
from poli_insight.domain.enum import ActorType, AuditAction
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
        before_json=_optional_json_to_storage(event.before_json),
        after_json=_optional_json_to_storage(event.after_json),
        patch_json=_optional_patch_to_storage(event.patch_json),
        request_id=event.request_id,
        correlation_id=event.correlation_id,
        causation_event_id=event.causation_event_id,
        source_metadata_json=_optional_json_to_storage(
            event.source_metadata_json
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
        before_json=_optional_json_from_storage(row.before_json),
        after_json=_optional_json_from_storage(row.after_json),
        patch_json=_optional_patch_from_storage(row.patch_json),
        request_id=row.request_id,
        correlation_id=row.correlation_id,
        causation_event_id=(
            str(row.causation_event_id)
            if row.causation_event_id is not None
            else None
        ),
        source_metadata_json=_optional_json_from_storage(
            row.source_metadata_json
        ),
        previous_event_hash=row.previous_event_hash,
        event_hash=row.event_hash,
        schema_version=row.schema_version,
    )


def _optional_json_to_storage(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    return None if value is None else _json_to_storage(value)


def _json_to_storage(value: Mapping[str, Any]) -> dict[str, Any]:
    """Convert canonical domain values to database-native JSON values."""

    encoded = canonical_json_bytes(value).decode("utf-8")
    stored = json.loads(encoded)
    if not isinstance(stored, dict):
        raise TypeError("Audit JSON storage value must be an object.")
    return stored


def _optional_patch_to_storage(
    value: tuple[Mapping[str, Any], ...] | None,
) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    return [_json_to_storage(operation) for operation in value]


def _optional_json_from_storage(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    return None if value is None else _json_from_storage(value)


def _json_from_storage(value: Mapping[str, Any]) -> dict[str, Any]:
    """Restore tagged canonical values from persisted audit JSON."""

    decoded = _decode_storage_value(deepcopy(dict(value)))
    if not isinstance(decoded, dict):
        raise TypeError("Persisted audit JSON value must be an object.")
    return decoded


def _optional_patch_from_storage(
    value: Sequence[Mapping[str, Any]] | None,
) -> tuple[Mapping[str, Any], ...] | None:
    if value is None:
        return None
    return tuple(_json_from_storage(operation) for operation in value)


def _decode_storage_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_storage_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    type_name = value.get("__poli_insight_type__")
    if type_name is not None:
        if set(value) != {"__poli_insight_type__", "value"}:
            raise ValueError("Malformed tagged audit JSON value.")
        tagged_value = value["value"]
        if not isinstance(tagged_value, str):
            raise ValueError("Tagged audit JSON value must contain text.")
        if type_name == "decimal":
            return Decimal(tagged_value)
        if type_name == "uuid":
            return UUID(tagged_value)
        if type_name == "datetime":
            return datetime.fromisoformat(tagged_value)
        if type_name == "date":
            return date.fromisoformat(tagged_value)
        raise ValueError(f"Unsupported tagged audit JSON type {type_name!r}.")

    return {
        key: _decode_storage_value(item)
        for key, item in value.items()
    }
