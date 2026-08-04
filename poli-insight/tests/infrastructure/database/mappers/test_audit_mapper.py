from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import ActorType, AuditAction
from poli_insight.infrastructure.database.mappers.audit import (
    audit_event_to_domain,
    audit_event_to_row,
)


class AuditMapperTests(unittest.TestCase):
    def test_canonical_values_round_trip_through_native_json(self) -> None:
        occurred_at = datetime(2026, 8, 1, 15, 30, tzinfo=UTC)
        identifier = UUID("4a11ac84-43c3-4c8e-9713-3b20ec05e93f")
        projection = {
            "scheduled_at": occurred_at,
            "decision_date": date(2026, 8, 15),
            "threshold": Decimal("0.10"),
            "identifier": identifier,
            "nested": [occurred_at, {"threshold": Decimal("2.5")}],
        }
        event = AuditEvent(
            audit_event_id="9c7abfcf-d61d-4cce-b40d-12f61ac09184",
            occurred_at=occurred_at,
            actor_type=ActorType.USER,
            actor_id="admin",
            action=AuditAction.CREATED,
            entity_type="session",
            entity_id="session-1",
            correlation_id="audit-round-trip",
            after_json=projection,
            patch_json=(
                {
                    "op": "replace",
                    "path": "/scheduled_at",
                    "value": occurred_at,
                },
            ),
            source_metadata_json={"effective_date": date(2026, 8, 1)},
            event_hash="a" * 64,
        )

        row = audit_event_to_row(event)
        json.dumps(row.after_json)
        json.dumps(row.patch_json)
        restored = audit_event_to_domain(row)

        self.assertEqual(restored.after_json, projection)
        self.assertEqual(restored.patch_json, event.patch_json)
        self.assertEqual(
            hash_json(restored.after_json),
            hash_json(event.after_json),
        )


if __name__ == "__main__":
    unittest.main()
