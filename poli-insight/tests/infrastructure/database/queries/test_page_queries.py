from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DatabaseSession, sessionmaker

from poli_insight.domain.enum import SessionStatus
from poli_insight.infrastructure.database.models import scenario as scenario_models
from poli_insight.infrastructure.database.models.session import SessionRow
from poli_insight.infrastructure.database.queries.page_queries import (
    SqlAlchemyPageQueries,
)


NOW = datetime(2026, 7, 30, 12, tzinfo=UTC)


class SqlAlchemyPageQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        # Importing scenario models resolves SessionRow's snapshot FK metadata.
        self.assertIsNotNone(scenario_models.ScenarioSnapshotRow)
        engine = create_engine("sqlite+pysqlite:///:memory:")
        SessionRow.__table__.create(engine)
        self.session_factory = sessionmaker(
            bind=engine,
            class_=DatabaseSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self.queries = SqlAlchemyPageQueries(self.session_factory)

    def test_public_catalog_enforces_status_discoverability_and_window(self) -> None:
        self._add_session(title="Open listed", status="open")
        self._add_session(
            title="Open unlisted",
            status="open",
            discoverability="unlisted",
        )
        self._add_session(title="Closed listed", status="closed")
        self._add_session(
            title="Expired listed",
            status="open",
            closes_at=NOW,
        )

        result = self.queries.list_open_public_sessions(at=NOW)

        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].title, "Open listed")

    def test_public_search_treats_like_wildcards_as_text(self) -> None:
        self._add_session(title="Budget 100% review", status="open")
        self._add_session(title="Budget review", status="open")

        result = self.queries.list_open_public_sessions(
            search="100%",
            at=NOW,
        )

        self.assertEqual(
            tuple(item.title for item in result.items),
            ("Budget 100% review",),
        )

    def test_dashboard_composes_independent_session_counts(self) -> None:
        self._add_session(title="Draft", status="draft")
        self._add_session(title="Open", status="open")
        self._add_session(title="Another open", status="open")

        dashboard = self.queries.get_admin_dashboard(at=NOW)

        self.assertEqual(dashboard.count(SessionStatus.DRAFT), 1)
        self.assertEqual(dashboard.count(SessionStatus.OPEN), 2)
        self.assertEqual(dashboard.count(SessionStatus.CLOSED), 0)

    def _add_session(
        self,
        *,
        title: str,
        status: str,
        discoverability: str = "listed",
        closes_at: datetime | None = None,
    ) -> None:
        opened_at = NOW - timedelta(days=1) if status in {"open", "closed"} else None
        closed_at = NOW - timedelta(hours=1) if status == "closed" else None
        row = SessionRow(
            session_id=uuid4(),
            scenario_snapshot_id=uuid4(),
            public_slug=f"session-{uuid4()}",
            title=title,
            description=None,
            admin_notes=None,
            status=status,
            discoverability=discoverability,
            enrollment_mode="open",
            access_code_mode="none",
            identity_policy="pseudonymous",
            stakeholder_selection_mode="self_select",
            opens_at=NOW - timedelta(days=1),
            closes_at=closes_at or NOW + timedelta(days=1),
            opened_at=opened_at,
            paused_at=None,
            closed_at=closed_at,
            canceled_at=None,
            archived_at=None,
            active_configuration_version_id=None,
            created_at=NOW - timedelta(days=2),
            created_by="test-admin",
            updated_at=NOW - timedelta(days=1),
            updated_by="test-admin",
        )
        with self.session_factory() as database_session:
            database_session.add(row)
            database_session.commit()


if __name__ == "__main__":
    unittest.main()
