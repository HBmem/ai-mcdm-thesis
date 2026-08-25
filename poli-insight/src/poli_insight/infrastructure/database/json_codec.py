"""Canonical domain JSON encoding for database JSON columns."""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from poli_insight.domain.content_hash import canonical_json_bytes


def json_to_storage(value: Mapping[str, Any]) -> dict[str, Any]:
    """Convert canonical domain values to database-native JSON values."""

    encoded = canonical_json_bytes(value).decode("utf-8")
    stored = json.loads(encoded)
    if not isinstance(stored, dict):
        raise TypeError("Database JSON storage value must be an object.")
    return stored


def json_from_storage(value: Mapping[str, Any]) -> dict[str, Any]:
    """Restore tagged canonical values from a persisted JSON object."""

    decoded = _decode_storage_value(deepcopy(dict(value)))
    if not isinstance(decoded, dict):
        raise TypeError("Persisted database JSON value must be an object.")
    return decoded


def _decode_storage_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_storage_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    type_name = value.get("__poli_insight_type__")
    if type_name is not None:
        if set(value) != {"__poli_insight_type__", "value"}:
            raise ValueError("Malformed tagged database JSON value.")
        tagged_value = value["value"]
        if not isinstance(tagged_value, str):
            raise ValueError("Tagged database JSON value must contain text.")
        if type_name == "decimal":
            return Decimal(tagged_value)
        if type_name == "uuid":
            return UUID(tagged_value)
        if type_name == "datetime":
            return datetime.fromisoformat(tagged_value)
        if type_name == "date":
            return date.fromisoformat(tagged_value)
        raise ValueError(f"Unsupported tagged database JSON type {type_name!r}.")

    return {
        key: _decode_storage_value(item)
        for key, item in value.items()
    }
