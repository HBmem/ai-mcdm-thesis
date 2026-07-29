"""Canonical JSON serialization and SHA-256 content hashing.

The functions in this module produce stable hashes for persisted documents such
as scenario manifests, session configurations, submissions, and artifacts.
Canonicalization removes insignificant JSON formatting and dictionary insertion
order while preserving list order and value types.

``Decimal``, ``UUID``, ``date``, and ``datetime`` are not native JSON values, so
they are represented by tagged JSON objects. The tag key is reserved and may
not appear in caller-provided mappings.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final
from uuid import UUID


_TYPE_TAG: Final = "__poli_insight_type__"
_VALUE_TAG: Final = "value"


def canonical_json_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 JSON representation of ``value``.

    Mapping keys are sorted, whitespace is omitted, Unicode is encoded directly
    as UTF-8, and nonfinite numeric values are rejected. Only JSON-compatible
    values plus ``Decimal``, ``UUID``, ``date``, and timezone-aware ``datetime``
    values are accepted.

    ``datetime`` values are normalized to UTC so two values representing the
    same instant produce the same bytes. Naive datetimes are rejected because
    their actual instant is ambiguous.

    Raises:
        TypeError: If a mapping key or value has an unsupported type.
        ValueError: If a number is nonfinite, a datetime is naive, a reserved
            key is used, or the input contains a circular container reference.
    """

    canonical_value = _to_canonical_value(value, path="$", ancestors=set())
    serialized = json.dumps(
        canonical_value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return serialized.encode("utf-8")


def sha256_digest(bytes_value: bytes | bytearray | memoryview) -> str:
    """Return the lowercase hexadecimal SHA-256 digest of bytes-like input.

    Text is intentionally not accepted. Callers hashing text must choose an
    encoding explicitly, while callers hashing structured data should normally
    use :func:`hash_json`.

    Raises:
        TypeError: If ``bytes_value`` is not bytes-like.
    """

    if not isinstance(bytes_value, (bytes, bytearray, memoryview)):
        raise TypeError("sha256_digest() requires a bytes-like value")

    return hashlib.sha256(bytes_value).hexdigest()


def hash_json(value: object) -> str:
    """Return the SHA-256 digest of a value's canonical JSON representation."""

    return sha256_digest(canonical_json_bytes(value))


def _to_canonical_value(
    value: object,
    *,
    path: str,
    ancestors: set[int],
) -> object:
    """Convert supported Python values to an unambiguous JSON value tree."""

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite float at {path} is not valid JSON")
        return value

    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError(f"Nonfinite Decimal at {path} is not valid JSON")
        return _tagged_value("decimal", str(value))

    if isinstance(value, UUID):
        return _tagged_value("uuid", str(value))

    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"Naive datetime at {path} has no defined instant")
        utc_value = value.astimezone(UTC)
        return _tagged_value(
            "datetime",
            utc_value.isoformat().replace("+00:00", "Z"),
        )

    if isinstance(value, date):
        return _tagged_value("date", value.isoformat())

    if isinstance(value, Mapping):
        return _canonical_mapping(value, path=path, ancestors=ancestors)

    if isinstance(value, list):
        return _canonical_list(value, path=path, ancestors=ancestors)

    raise TypeError(
        f"Unsupported value type at {path}: "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _canonical_mapping(
    value: Mapping[object, object],
    *,
    path: str,
    ancestors: set[int],
) -> dict[str, object]:
    container_id = id(value)
    _enter_container(container_id, path=path, ancestors=ancestors)

    try:
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(
                    f"Mapping key at {path} must be str, got "
                    f"{type(key).__module__}.{type(key).__qualname__}"
                )
            if key == _TYPE_TAG:
                raise ValueError(
                    f"Mapping at {path} uses reserved key {_TYPE_TAG!r}"
                )
            result[key] = _to_canonical_value(
                item,
                path=f"{path}.{key}",
                ancestors=ancestors,
            )
        return result
    finally:
        ancestors.remove(container_id)


def _canonical_list(
    value: list[object],
    *,
    path: str,
    ancestors: set[int],
) -> list[object]:
    container_id = id(value)
    _enter_container(container_id, path=path, ancestors=ancestors)

    try:
        return [
            _to_canonical_value(
                item,
                path=f"{path}[{index}]",
                ancestors=ancestors,
            )
            for index, item in enumerate(value)
        ]
    finally:
        ancestors.remove(container_id)


def _enter_container(
    container_id: int,
    *,
    path: str,
    ancestors: set[int],
) -> None:
    if container_id in ancestors:
        raise ValueError(f"Circular container reference detected at {path}")
    ancestors.add(container_id)


def _tagged_value(type_name: str, value: str) -> dict[str, str]:
    return {_TYPE_TAG: type_name, _VALUE_TAG: value}
