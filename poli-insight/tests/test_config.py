from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from poli_insight.config import Settings, SettingsError, resolve_scenario_paths


class ScenarioSettingsTests(unittest.TestCase):
    def test_production_environment_requires_import_secrets(self) -> None:
        with (
            patch.dict(
                "os.environ",
                {
                    "POLI_INSIGHT_ENVIRONMENT": "production",
                    "PUBLIC_BASE_URL": "https://research.example.test",
                },
                clear=True,
            ),
            self.assertRaisesRegex(
                SettingsError, "PARTICIPANT_IMPORT_HMAC_SECRET"
            ),
        ):
            Settings.from_environment()

    def test_import_security_configuration_is_validated(self) -> None:
        with self.assertRaisesRegex(SettingsError, "at least 32"):
            Settings(
                database_url="sqlite+pysqlite:///:memory:",
                app_timezone="UTC",
                participant_import_hmac_secret="too-short",
            )
        with self.assertRaisesRegex(SettingsError, "between 1 and 3650"):
            Settings(
                database_url="sqlite+pysqlite:///:memory:",
                app_timezone="UTC",
                imported_identity_retention_days=0,
            )

    def test_public_base_url_is_normalized_and_production_requires_https(self) -> None:
        settings = Settings(
            database_url="sqlite+pysqlite:///:memory:",
            app_timezone="UTC",
            public_base_url="https://research.example.test/poli/",
            app_environment="production",
        )

        self.assertEqual(
            settings.public_base_url,
            "https://research.example.test/poli",
        )
        with self.assertRaisesRegex(SettingsError, "HTTPS"):
            Settings(
                database_url="sqlite+pysqlite:///:memory:",
                app_timezone="UTC",
                public_base_url="http://research.example.test",
                app_environment="production",
            )

    def test_public_base_url_rejects_embedded_credentials_or_query(self) -> None:
        for unsafe_url in (
            "https://user:secret@example.test",
            "https://example.test?access=secret",
        ):
            with self.subTest(unsafe_url=unsafe_url), self.assertRaises(
                SettingsError
            ):
                Settings(
                    database_url="sqlite+pysqlite:///:memory:",
                    app_timezone="UTC",
                    public_base_url=unsafe_url,
                )
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
            self.assertRaises(SettingsError),
        ):
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
