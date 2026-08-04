from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from poli_insight.application.use_cases.import_bundled_scenarios import (
    ImportBundledScenariosCommand,
)
from poli_insight.bootstrap import create_container
from poli_insight.config import Settings
from poli_insight.infrastructure.database.engine import build_engine
from poli_insight.infrastructure.database.models.audit import AuditEventRow


PROJECT_ROOT = Path(__file__).parents[2]


class BundledScenarioScanIntegrationTests(unittest.TestCase):
    def test_fresh_database_imports_then_skips_bundled_scenarios(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            temporary_root = Path(temp_name)
            database_path = temporary_root / "scenario-scan.sqlite"
            scenario_root = temporary_root / "scenarios"
            shutil.copytree(PROJECT_ROOT / "scenarios", scenario_root)
            database_url = f"sqlite+pysqlite:///{database_path}"
            with patch.dict(
                os.environ,
                {"DATABASE_URL": database_url},
                clear=False,
            ):
                alembic_config = AlembicConfig(
                    str(PROJECT_ROOT / "alembic.ini")
                )
                alembic_command.upgrade(alembic_config, "head")

            settings = Settings(
                database_url=database_url,
                app_timezone="UTC",
                scenario_source_root=scenario_root,
                scenario_template_directory="_template",
            )
            container = create_container(settings)

            first = container.import_bundled_scenarios.execute(
                ImportBundledScenariosCommand(
                    actor_id="integration-admin",
                    correlation_id="integration-first",
                )
            )
            second = container.import_bundled_scenarios.execute(
                ImportBundledScenariosCommand(
                    actor_id="integration-admin",
                    correlation_id="integration-second",
                )
            )

            self.assertEqual(first.imported_count, 2)
            self.assertEqual(first.failed_count, 0)
            self.assertEqual(second.skipped_duplicate_count, 2)
            self.assertEqual(second.imported_count, 0)
            self.assertNotIn(
                "_template",
                tuple(outcome.relative_directory for outcome in first.outcomes),
            )

            metrics = container.page_queries.get_scenario_library_metrics()
            catalog = container.page_queries.list_scenario_snapshots(
                page_size=10
            )
            self.assertEqual(metrics.definition_count, 2)
            self.assertEqual(metrics.snapshot_count, 2)
            self.assertEqual(metrics.ready_count, 2)
            self.assertEqual(catalog.total, 2)
            for summary in catalog.items:
                detail = container.page_queries.get_scenario_snapshot_detail(
                    summary.scenario_snapshot_id
                )
                self.assertIsNotNone(detail)
                assert detail is not None
                self.assertGreater(len(detail.files), 0)
                self.assertGreater(detail.matrix_value_count, 0)

            public_safety_data = (
                scenario_root
                / "public_safety_resource_allocation"
                / "data"
                / "data.csv"
            )
            public_safety_data.write_text(
                public_safety_data.read_text(encoding="utf-8").replace(
                    "2500000",
                    "2500001",
                    1,
                ),
                encoding="utf-8",
            )
            changed = container.import_bundled_scenarios.execute(
                ImportBundledScenariosCommand(
                    actor_id="integration-admin",
                    correlation_id="integration-changed",
                )
            )
            self.assertEqual(changed.imported_count, 1)
            self.assertEqual(changed.skipped_duplicate_count, 1)
            refreshed_metrics = (
                container.page_queries.get_scenario_library_metrics()
            )
            self.assertEqual(refreshed_metrics.definition_count, 2)
            self.assertEqual(refreshed_metrics.snapshot_count, 3)

            engine = build_engine(settings)
            try:
                with Session(engine) as database_session:
                    audit_count = database_session.scalar(
                        select(func.count()).select_from(AuditEventRow)
                    )
            finally:
                engine.dispose()
            self.assertEqual(audit_count, 3)


if __name__ == "__main__":
    unittest.main()
