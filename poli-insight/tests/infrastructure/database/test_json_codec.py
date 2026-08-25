from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from poli_insight.infrastructure.database.json_codec import (
    json_from_storage,
    json_to_storage,
)


def test_canonical_database_json_round_trips_nested_typed_values() -> None:
    value = {
        "weights": [Decimal("0.166666666666666667")],
        "identifier": UUID("12345678-1234-5678-1234-567812345678"),
        "created_at": datetime(2026, 8, 23, 12, 30, tzinfo=UTC),
        "effective_date": date(2026, 8, 23),
    }

    stored = json_to_storage(value)

    assert stored["weights"] == [
        {
            "__poli_insight_type__": "decimal",
            "value": "0.166666666666666667",
        }
    ]
    assert json_from_storage(stored) == value


def test_database_json_decoder_rejects_malformed_type_tags() -> None:
    with pytest.raises(ValueError, match="Malformed tagged"):
        json_from_storage(
            {
                "value": {
                    "__poli_insight_type__": "decimal",
                    "value": "1",
                    "unexpected": True,
                }
            }
        )
