from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from poli_insight.config import Settings, SettingsError, resolve_scenario_paths


class ScenarioSettingsTests(unittest.TestCase):
    def test_resolves_source_and_template_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            template = root / "template"
            template.mkdir()

            paths = resolve_scenario_paths(
                Settings(
                    database_url="sqlite+pysqlite:///:memory:",
                    app_timezone="UTC",
                    scenario_source_root=root,
                    scenario_template_directory="template",
                )
            )

        self.assertTrue(paths.source_root.is_absolute())
        self.assertEqual(paths.template_directory, template.resolve())

    def test_rejects_template_outside_source_root(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root_name,
            tempfile.TemporaryDirectory() as outside_name,
        ):
            with self.assertRaises(SettingsError):
                resolve_scenario_paths(
                    Settings(
                        database_url="sqlite+pysqlite:///:memory:",
                        app_timezone="UTC",
                        scenario_source_root=Path(root_name),
                        scenario_template_directory=Path(outside_name),
                    )
                )


if __name__ == "__main__":
    unittest.main()
