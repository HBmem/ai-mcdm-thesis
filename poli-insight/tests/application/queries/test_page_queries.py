from __future__ import annotations

import unittest
from dataclasses import fields
from datetime import UTC, datetime

from poli_insight.application.queries.page_queries import (
    AdminDashboardSnapshot,
    PageResult,
    ParticipantAccessSummary,
    ScenarioLibraryMetrics,
    SessionCatalogMetrics,
)
from poli_insight.domain.enum import SessionStatus


class PageResultTests(unittest.TestCase):
    def test_calculates_page_count(self) -> None:
        result = PageResult(
            items=("one", "two"),
            page=2,
            page_size=2,
            total=5,
        )

        self.assertEqual(result.page_count, 3)

    def test_rejects_invalid_paging(self) -> None:
        with self.assertRaises(ValueError):
            PageResult(items=(), page=0, page_size=10, total=0)


class AdminDashboardSnapshotTests(unittest.TestCase):
    def test_fills_missing_status_counts_and_copies_input(self) -> None:
        source = {SessionStatus.OPEN: 2}
        snapshot = AdminDashboardSnapshot(
            generated_at=datetime(2026, 7, 30, tzinfo=UTC),
            session_status_counts=source,
        )
        source[SessionStatus.OPEN] = 99

        self.assertEqual(snapshot.count(SessionStatus.OPEN), 2)
        self.assertEqual(snapshot.count(SessionStatus.CLOSED), 0)


class ScenarioLibraryMetricsTests(unittest.TestCase):
    def test_rejects_negative_counts(self) -> None:
        with self.assertRaises(ValueError):
            ScenarioLibraryMetrics(
                definition_count=1,
                snapshot_count=1,
                ready_count=1,
                attention_count=-1,
            )


class SessionCatalogMetricsTests(unittest.TestCase):
    def test_rejects_negative_counts(self) -> None:
        with self.assertRaises(ValueError):
            SessionCatalogMetrics(
                total_count=1,
                open_count=0,
                attention_count=-1,
            )


class CredentialProjectionTests(unittest.TestCase):
    def test_participant_access_summary_cannot_expose_token_material(self) -> None:
        field_names = {field.name for field in fields(ParticipantAccessSummary)}

        self.assertNotIn("token", field_names)
        self.assertNotIn("access_token", field_names)
        self.assertNotIn("token_digest", field_names)


if __name__ == "__main__":
    unittest.main()
