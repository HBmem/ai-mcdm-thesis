from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from poli_insight.application.use_cases.activate_session_configuration import (
    ActivateSessionConfigurationCommand,
)
from poli_insight.application.use_cases.close_session import CloseSessionCommand
from poli_insight.application.use_cases.create_session import (
    CreateSessionCommand,
)
from poli_insight.application.use_cases.create_session_configuration import (
    AlgorithmSelectionInput,
    CreateSessionConfigurationCommand,
    StakeholderGroupInput,
)
from poli_insight.application.use_cases.import_bundled_scenarios import (
    ImportBundledScenariosCommand,
)
from poli_insight.application.use_cases.open_session import OpenSessionCommand
from poli_insight.application.use_cases.transition_session import (
    SessionTransition,
    TransitionSessionCommand,
)
from poli_insight.bootstrap import create_container
from poli_insight.config import Settings
from poli_insight.domain.enum import (
    AlgorithmRole,
    ResponseFormat,
    ResponseTargetType,
    ScenarioSnapshotStatus,
    SessionStatus,
)

PROJECT_ROOT = Path(__file__).parents[2]


class SessionManagementIntegrationTests(unittest.TestCase):
    def test_admin_core_migration_preserves_existing_audit_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            database_path = Path(temp_name) / "migration.sqlite"
            database_url = f"sqlite+pysqlite:///{database_path}"
            alembic_config = AlembicConfig(
                str(PROJECT_ROOT / "alembic.ini")
            )
            with patch.dict(
                os.environ,
                {"DATABASE_URL": database_url},
                clear=False,
            ):
                alembic_command.upgrade(alembic_config, "0005")
                with sqlite3.connect(database_path) as connection:
                    connection.execute(
                        """
                        INSERT INTO audit_events (
                            audit_event_id, occurred_at, actor_type, actor_id,
                            action, entity_type, entity_id, correlation_id,
                            event_hash, schema_version
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "20000000-0000-4000-8000-000000000001",
                            "2026-08-03T12:00:00+00:00",
                            "user",
                            "migration-admin",
                            "created",
                            "session",
                            "20000000-0000-4000-8000-000000000002",
                            "migration-correlation",
                            "0" * 64,
                            1,
                        ),
                    )
                alembic_command.upgrade(alembic_config, "head")

            with sqlite3.connect(database_path) as connection:
                preserved = connection.execute(
                    "SELECT action, correlation_id FROM audit_events"
                ).fetchall()
                algorithm_count = connection.execute(
                    "SELECT count(*) FROM algorithm_implementations"
                ).fetchone()
            self.assertEqual(
                preserved,
                [("created", "migration-correlation")],
            )
            assert algorithm_count is not None
            self.assertEqual(algorithm_count[0], 2)

    def test_created_draft_refreshes_catalog_and_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            database_path = Path(temp_name) / "session-management.sqlite"
            database_url = f"sqlite+pysqlite:///{database_path}"
            with patch.dict(
                os.environ,
                {"DATABASE_URL": database_url},
                clear=False,
            ):
                alembic_command.upgrade(
                    AlembicConfig(str(PROJECT_ROOT / "alembic.ini")),
                    "head",
                )

            container = create_container(
                Settings(
                    database_url=database_url,
                    app_timezone="UTC",
                    scenario_source_root=PROJECT_ROOT / "scenarios",
                    scenario_template_directory="_template",
                )
            )
            imported = container.import_bundled_scenarios.execute(
                ImportBundledScenariosCommand(actor_id="integration-admin")
            )
            self.assertEqual(imported.imported_count, 2)
            snapshot = container.page_queries.list_scenario_snapshots(
                status=ScenarioSnapshotStatus.READY,
                page_size=10,
            ).items[0]
            scenario_detail = container.page_queries.get_scenario_snapshot_detail(
                snapshot.scenario_snapshot_id
            )
            assert scenario_detail is not None
            self.assertEqual(
                sum(
                    item.is_application_defined
                    for item in scenario_detail.scales
                ),
                4,
            )
            self.assertEqual(
                scenario_detail.default_scale_key,
                "pairwise_seven_point_v1",
            )
            self.assertTrue(scenario_detail.stakeholder_group_defaults)
            self.assertEqual(
                sum(
                    item.allocation_units
                    for item in scenario_detail.stakeholder_group_defaults
                ),
                10_000,
            )
            opens_at = datetime.now(tz=UTC) + timedelta(days=1)
            closes_at = opens_at + timedelta(days=14)

            result = container.sessions.create.execute(
                CreateSessionCommand(
                    scenario_snapshot_id=snapshot.scenario_snapshot_id,
                    public_slug="integration-session",
                    title="Integration session",
                    description="Session catalog integration test.",
                    opens_at=opens_at,
                    closes_at=closes_at,
                    actor_id="integration-admin",
                )
            )

            metrics = container.page_queries.get_session_catalog_metrics()
            catalog = container.page_queries.list_admin_sessions()
            detail = container.page_queries.get_admin_session_detail(
                result.session_id
            )

            self.assertEqual(metrics.total_count, 1)
            self.assertEqual(metrics.open_count, 0)
            self.assertEqual(metrics.attention_count, 1)
            self.assertEqual(catalog.total, 1)
            self.assertEqual(catalog.items[0].status, SessionStatus.DRAFT)
            self.assertTrue(catalog.items[0].needs_attention)
            self.assertFalse(
                container.page_queries.is_public_slug_available(
                    "integration-session"
                )
            )
            self.assertIsNotNone(detail)
            assert detail is not None
            self.assertEqual(detail.summary.title, "Integration session")
            self.assertEqual(detail.summary.opens_at, opens_at)
            self.assertEqual(detail.summary.closes_at, closes_at)
            self.assertIsNone(detail.configuration)
            self.assertEqual(detail.participant_total, 0)
            self.assertEqual(detail.submission_total, 0)
            self.assertEqual(detail.audit_events[0].action, "Created")

    def test_configuration_lifecycle_and_audit_core(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            database_path = Path(temp_name) / "admin-session-core.sqlite"
            database_url = f"sqlite+pysqlite:///{database_path}"
            with patch.dict(
                os.environ,
                {"DATABASE_URL": database_url},
                clear=False,
            ):
                alembic_command.upgrade(
                    AlembicConfig(str(PROJECT_ROOT / "alembic.ini")),
                    "head",
                )
            container = create_container(
                Settings(
                    database_url=database_url,
                    app_timezone="UTC",
                    scenario_source_root=PROJECT_ROOT / "scenarios",
                    scenario_template_directory="_template",
                )
            )
            imported = container.import_bundled_scenarios.execute(
                ImportBundledScenariosCommand(actor_id="integration-admin")
            )
            self.assertEqual(imported.imported_count, 2)
            snapshot = container.page_queries.list_scenario_snapshots(
                status=ScenarioSnapshotStatus.READY,
                page_size=10,
            ).items[0]
            scenario = container.page_queries.get_scenario_snapshot_detail(
                snapshot.scenario_snapshot_id
            )
            assert scenario is not None
            pairwise_scale = next(
                item
                for item in scenario.scales
                if item.scale_key == "pairwise_seven_point_v1"
            )
            weighting = container.page_queries.list_active_algorithm_implementations(
                role=AlgorithmRole.WEIGHTING
            )[0]
            ranking = container.page_queries.list_active_algorithm_implementations(
                role=AlgorithmRole.RANKING
            )[0]
            created = container.sessions.create.execute(
                CreateSessionCommand(
                    scenario_snapshot_id=snapshot.scenario_snapshot_id,
                    public_slug="core-lifecycle",
                    title="Core lifecycle",
                    actor_id="integration-admin",
                )
            )
            configured = container.sessions.create_configuration.execute(
                CreateSessionConfigurationCommand(
                    session_id=created.session_id,
                    actor_id="integration-admin",
                    response_format=ResponseFormat.PAIRWISE,
                    response_target_type=ResponseTargetType.CRITERION,
                    scale_id=pairwise_scale.scale_id,
                    stakeholder_groups=(
                        StakeholderGroupInput(
                            group_key="all_participants",
                            name="All participants",
                            description="All eligible participants.",
                            allocation_units=10_000,
                            required=True,
                        ),
                    ),
                    algorithms=(
                        AlgorithmSelectionInput(
                            weighting.algorithm_implementation_id,
                            AlgorithmRole.WEIGHTING,
                        ),
                        AlgorithmSelectionInput(
                            ranking.algorithm_implementation_id,
                            AlgorithmRole.RANKING,
                        ),
                    ),
                )
            )
            self.assertEqual(
                configured.question_count,
                len(scenario.criteria) * (len(scenario.criteria) - 1) // 2,
            )
            detail = container.page_queries.get_admin_session_detail(
                created.session_id
            )
            assert detail is not None
            self.assertIsNone(detail.configuration)
            self.assertEqual(len(detail.configurations), 1)
            self.assertFalse(detail.configurations[0].is_active)

            container.sessions.activate_configuration.execute(
                ActivateSessionConfigurationCommand(
                    session_id=created.session_id,
                    configuration_version_id=(
                        configured.configuration_version_id
                    ),
                    actor_id="integration-admin",
                )
            )
            container.sessions.open.execute(
                OpenSessionCommand(
                    session_id=created.session_id,
                    actor_id="integration-admin",
                )
            )
            for transition in (
                SessionTransition.PAUSE,
                SessionTransition.RESUME,
            ):
                container.sessions.transition.execute(
                    TransitionSessionCommand(
                        session_id=created.session_id,
                        transition=transition,
                        actor_id="integration-admin",
                    )
                )
            container.sessions.close.execute(
                CloseSessionCommand(
                    session_id=created.session_id,
                    actor_id="integration-admin",
                )
            )
            container.sessions.transition.execute(
                TransitionSessionCommand(
                    session_id=created.session_id,
                    transition=SessionTransition.ARCHIVE,
                    actor_id="integration-admin",
                    reason_code="integration_complete",
                )
            )

            refreshed = container.page_queries.get_admin_session_detail(
                created.session_id
            )
            assert refreshed is not None
            self.assertEqual(refreshed.summary.status, SessionStatus.ARCHIVED)
            self.assertIsNotNone(refreshed.configuration)
            assert refreshed.configuration is not None
            self.assertEqual(refreshed.configuration.version_number, 1)
            actions = {item.action for item in refreshed.audit_events}
            self.assertTrue(
                {
                    "Created",
                    "Activated",
                    "Opened",
                    "Paused",
                    "Resumed",
                    "Closed",
                    "Archived",
                }.issubset(actions)
            )
            audit = container.page_queries.list_admin_audit_events(
                search="core-lifecycle",
                page_size=25,
            )
            self.assertGreaterEqual(audit.total, 7)
            self.assertTrue(
                all(item.session_title == "Core lifecycle" for item in audit.items)
            )

            scheduled = container.sessions.create.execute(
                CreateSessionCommand(
                    scenario_snapshot_id=snapshot.scenario_snapshot_id,
                    public_slug="scheduled-cancel",
                    title="Scheduled cancellation",
                    opens_at=datetime.now(tz=UTC) + timedelta(days=2),
                    actor_id="integration-admin",
                )
            )
            for transition in (
                SessionTransition.SCHEDULE,
                SessionTransition.CANCEL,
                SessionTransition.ARCHIVE,
            ):
                container.sessions.transition.execute(
                    TransitionSessionCommand(
                        session_id=scheduled.session_id,
                        transition=transition,
                        actor_id="integration-admin",
                        reason_code=(
                            "integration_cancel"
                            if transition == SessionTransition.CANCEL
                            else None
                        ),
                    )
                )
            scheduled_detail = container.page_queries.get_admin_session_detail(
                scheduled.session_id
            )
            assert scheduled_detail is not None
            self.assertEqual(
                scheduled_detail.summary.status,
                SessionStatus.ARCHIVED,
            )
            self.assertTrue(
                {"Scheduled", "Canceled", "Archived"}.issubset(
                    {item.action for item in scheduled_detail.audit_events}
                )
            )


if __name__ == "__main__":
    unittest.main()
