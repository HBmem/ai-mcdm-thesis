from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DatabaseSession, sessionmaker

from poli_insight.domain.enum import (
    ResponseFormat,
    ScenarioSnapshotStatus,
    SessionStatus,
)
from poli_insight.infrastructure.database.models import scenario as scenario_models
from poli_insight.infrastructure.database.models.scenario import (
    ScenarioAlternativeRow,
    ScenarioCriterionRow,
    ScenarioDefinitionRow,
    ScenarioMatrixValueRow,
    ScenarioScaleRow,
    ScenarioScaleValueRow,
    ScenarioSnapshotFileRow,
    ScenarioSnapshotRow,
)
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
        ScenarioDefinitionRow.__table__.create(engine)
        ScenarioSnapshotRow.__table__.create(engine)
        ScenarioSnapshotFileRow.__table__.create(engine)
        SessionRow.__table__.create(engine)
        self.session_factory = sessionmaker(
            bind=engine,
            class_=DatabaseSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self.queries = SqlAlchemyPageQueries(self.session_factory)
        definition_id = uuid4()
        self.snapshot_id = uuid4()
        with self.session_factory() as database_session:
            database_session.add(
                ScenarioDefinitionRow(
                    scenario_definition_id=definition_id,
                    scenario_key="public-budget",
                    title="Public budget",
                    domain="Public policy",
                    description="Choose a public budget.",
                    status="active",
                    created_at=NOW,
                    created_by="test-admin",
                    updated_at=NOW,
                    updated_by="test-admin",
                )
            )
            database_session.add(
                ScenarioSnapshotRow(
                    scenario_snapshot_id=self.snapshot_id,
                    scenario_definition_id=definition_id,
                    declared_version="1.0",
                    scenario_type="standard",
                    schema_version=1,
                    status="ready",
                    title="Public budget",
                    domain="Public policy",
                    summary="Evaluate the available budget options.",
                    policy_question="Which budget option should be selected?",
                    manifest_json={"schema_version": 1},
                    manifest_schema_version=1,
                    root_hash="a" * 64,
                    materialized_input_hash="b" * 64,
                    source_uri="urn:test:public-budget",
                    importer_version="test-importer/1",
                    import_environment_json={},
                    created_at=NOW,
                    created_by="test-admin",
                    ready_at=NOW,
                )
            )
            scenario_source = b'{"tags": ["budget", "community"]}'
            database_session.add(
                ScenarioSnapshotFileRow(
                    snapshot_file_id=uuid4(),
                    scenario_snapshot_id=self.snapshot_id,
                    logical_path="scenario.json",
                    file_role="scenario_config",
                    media_type="application/json",
                    byte_size=len(scenario_source),
                    content_hash="c" * 64,
                    inline_bytes=scenario_source,
                    immutable_object_uri=None,
                )
            )
            database_session.commit()

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

    def test_public_catalog_includes_details_from_imported_scenario(self) -> None:
        self._add_session(title="Open listed", status="open")

        result = self.queries.list_open_public_sessions(at=NOW)

        summary = result.items[0]
        self.assertEqual(summary.domain, "Public policy")
        self.assertEqual(summary.tags, ("budget", "community"))
        self.assertEqual(
            summary.policy_question,
            "Which budget option should be selected?",
        )

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
            scenario_snapshot_id=self.snapshot_id,
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


class SqlAlchemyScenarioLibraryQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        for table in (
            ScenarioDefinitionRow.__table__,
            ScenarioSnapshotRow.__table__,
            ScenarioSnapshotFileRow.__table__,
            ScenarioCriterionRow.__table__,
            ScenarioAlternativeRow.__table__,
            ScenarioScaleRow.__table__,
            ScenarioScaleValueRow.__table__,
            ScenarioMatrixValueRow.__table__,
        ):
            table.create(engine)
        self.session_factory = sessionmaker(
            bind=engine,
            class_=DatabaseSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self.queries = SqlAlchemyPageQueries(self.session_factory)
        self.ready_snapshot_id = self._add_library_rows()

    def test_catalog_metrics_filters_and_escapes_search_wildcards(self) -> None:
        metrics = self.queries.get_scenario_library_metrics()
        result = self.queries.list_scenario_snapshots(
            search="100%",
            status=ScenarioSnapshotStatus.READY,
            domain="Public policy",
        )

        self.assertEqual(metrics.definition_count, 1)
        self.assertEqual(metrics.snapshot_count, 2)
        self.assertEqual(metrics.ready_count, 1)
        self.assertEqual(metrics.attention_count, 1)
        self.assertEqual(self.queries.list_scenario_domains(), ("Public policy",))
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].title, "Budget 100% review")
        self.assertEqual(result.items[0].alternative_count, 1)
        self.assertEqual(result.items[0].criterion_count, 1)

    def test_detail_returns_preview_data_without_source_bytes(self) -> None:
        detail = self.queries.get_scenario_snapshot_detail(
            str(self.ready_snapshot_id)
        )

        self.assertIsNotNone(detail)
        assert detail is not None
        self.assertEqual(detail.matrix_value_count, 1)
        self.assertEqual(detail.alternatives[0].name, "Option A")
        self.assertEqual(detail.criteria[0].name, "Cost")
        self.assertEqual(detail.scales[0].value_count, 1)
        self.assertEqual(detail.files[0].logical_path, "scenario.json")
        self.assertFalse(hasattr(detail.files[0], "inline_bytes"))
        self.assertIs(detail.default_response_format, ResponseFormat.PAIRWISE)
        self.assertEqual(detail.default_scale_key, "pairwise_seven_point_v1")
        self.assertEqual(
            tuple(
                (item.group_key, item.allocation_units)
                for item in detail.stakeholder_group_defaults
            ),
            (("residents", 2500), ("officials", 7500)),
        )

    def _add_library_rows(self):
        definition_id = uuid4()
        ready_snapshot_id = uuid4()
        invalid_snapshot_id = uuid4()
        criterion_id = uuid4()
        alternative_id = uuid4()
        scale_id = uuid4()
        with self.session_factory() as database_session:
            database_session.add(
                ScenarioDefinitionRow(
                    scenario_definition_id=definition_id,
                    scenario_key="budget-review",
                    title="Budget review",
                    domain="Public policy",
                    description="Choose a budget option.",
                    status="active",
                    created_at=NOW,
                    created_by="admin",
                    updated_at=NOW,
                    updated_by="admin",
                )
            )
            database_session.add_all(
                (
                    self._snapshot(
                        snapshot_id=ready_snapshot_id,
                        definition_id=definition_id,
                        title="Budget 100% review",
                        status="ready",
                        root_hash="a" * 64,
                        ready_at=NOW,
                    ),
                    self._snapshot(
                        snapshot_id=invalid_snapshot_id,
                        definition_id=definition_id,
                        title="Earlier budget review",
                        status="invalid",
                        root_hash="b" * 64,
                        ready_at=None,
                    ),
                )
            )
            database_session.add_all(
                (
                    ScenarioSnapshotFileRow(
                        snapshot_file_id=uuid4(),
                        scenario_snapshot_id=ready_snapshot_id,
                        logical_path="scenario.json",
                        file_role="scenario_config",
                        media_type="application/json",
                        byte_size=381,
                        content_hash="c" * 64,
                        inline_bytes=(
                            b'{"preference_collection": {'
                            b'"default_method": "pairwise_comparison", '
                            b'"default_scale_id": "pairwise_seven_point_v1"}, '
                            b'"stakeholder_groups": ['
                            b'{"id": "residents", "label": "Residents", '
                            b'"description": "Community members", '
                            b'"default_group_voting_power": 1},'
                            b'{"id": "officials", "label": "Officials", '
                            b'"description": "Public officials", '
                            b'"default_group_voting_power": 3}]}'
                        ),
                        immutable_object_uri=None,
                    ),
                    ScenarioCriterionRow(
                        criterion_id=criterion_id,
                        scenario_snapshot_id=ready_snapshot_id,
                        criterion_key="cost",
                        name="Cost",
                        description=None,
                        direction="cost",
                        data_type="numeric",
                        unit="USD",
                        parent_criterion_id=None,
                        required=True,
                        display_order=0,
                        source_column="cost",
                        metadata_json={},
                    ),
                    ScenarioAlternativeRow(
                        alternative_id=alternative_id,
                        scenario_snapshot_id=ready_snapshot_id,
                        alternative_key="option-a",
                        name="Option A",
                        description="First option",
                        display_order=0,
                        metadata_json={},
                    ),
                    ScenarioScaleRow(
                        scale_id=scale_id,
                        scenario_snapshot_id=ready_snapshot_id,
                        scale_key="importance",
                        name="Importance",
                        scale_type="numeric",
                        ordered=True,
                        definition_version=1,
                        metadata_json={},
                    ),
                )
            )
            database_session.add_all(
                (
                    ScenarioScaleValueRow(
                        scale_value_id=uuid4(),
                        scale_id=scale_id,
                        stable_value_key="high",
                        label="High",
                        ordinal=0,
                        numeric_value=Decimal("1"),
                        fuzzy_lower=None,
                        fuzzy_middle=None,
                        fuzzy_upper=None,
                        metadata_json={},
                    ),
                    ScenarioMatrixValueRow(
                        scenario_snapshot_id=ready_snapshot_id,
                        alternative_id=alternative_id,
                        criterion_id=criterion_id,
                        value_numeric=Decimal("10"),
                        value_json=None,
                        source_provenance_json={},
                    ),
                )
            )
            database_session.commit()
        return ready_snapshot_id

    @staticmethod
    def _snapshot(
        *,
        snapshot_id,
        definition_id,
        title: str,
        status: str,
        root_hash: str,
        ready_at: datetime | None,
    ) -> ScenarioSnapshotRow:
        return ScenarioSnapshotRow(
            scenario_snapshot_id=snapshot_id,
            scenario_definition_id=definition_id,
            declared_version="1.0",
            scenario_type="standard",
            schema_version=1,
            status=status,
            title=title,
            domain="Public policy",
            summary="Evaluate the available options.",
            policy_question="Which option should be selected?",
            manifest_json={"schema_version": 1},
            manifest_schema_version=1,
            root_hash=root_hash,
            materialized_input_hash="d" * 64,
            source_uri="urn:test:scenario",
            importer_version="test-importer/1",
            import_environment_json={},
            created_at=NOW,
            created_by="admin",
            ready_at=ready_at,
        )


if __name__ == "__main__":
    unittest.main()
