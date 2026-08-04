from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from poli_insight.application.ports.bundled_scenarios import (
    BundledScenarioCandidate,
    BundledScenarioSourceError,
    ScenarioConfigurationType,
    ScenarioDiscoveryStatus,
)
from poli_insight.infrastructure.scenarios.bundled_source import (
    FilesystemBundledScenarioSource,
)


PROJECT_ROOT = Path(__file__).parents[3]


class FilesystemBundledScenarioSourceTests(unittest.TestCase):
    def test_discovers_bundled_scenarios_and_excludes_jsonc_template(self) -> None:
        source = FilesystemBundledScenarioSource(
            PROJECT_ROOT / "scenarios",
            PROJECT_ROOT / "scenarios" / "_template",
        )

        candidates = source.discover()

        self.assertEqual(
            tuple(candidate.relative_directory for candidate in candidates),
            (
                "public_safety_resource_allocation",
                "seattle_school_closure",
            ),
        )
        self.assertTrue(
            all(
                candidate.configuration_type
                == ScenarioConfigurationType.PRODUCTION_JSON
                for candidate in candidates
            )
        )
        self.assertNotIn(
            "_template",
            tuple(candidate.relative_directory for candidate in candidates),
        )

    def test_ignores_unrelated_directories_and_orders_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            self._write_scenario(root / "zeta", title="Zeta")
            self._write_scenario(root / "alpha", title="Alpha")
            (root / "unrelated").mkdir()
            (root / "unrelated" / "README.txt").write_text("notes")
            template = root / "template"
            template.mkdir()
            (template / "scenario.jsonc").write_text("// template\n{}")
            source = FilesystemBundledScenarioSource(root, template)

            candidates = source.discover()

        self.assertEqual(
            tuple(candidate.relative_directory for candidate in candidates),
            ("alpha", "zeta"),
        )

    def test_rejects_symlink_escape_and_traversal_resolution(self) -> None:
        with (
            tempfile.TemporaryDirectory() as root_name,
            tempfile.TemporaryDirectory() as outside_name,
        ):
            root = Path(root_name)
            outside = Path(outside_name)
            self._write_scenario(outside, title="Outside")
            (root / "escape").symlink_to(outside, target_is_directory=True)
            source = FilesystemBundledScenarioSource(root, None)

            candidates = source.discover()
            forged = BundledScenarioCandidate(
                display_name="Traversal",
                relative_directory="../outside",
                configuration_type=ScenarioConfigurationType.PRODUCTION_JSON,
                discovery_status=ScenarioDiscoveryStatus.READY,
                declared_version="1.0",
            )

            self.assertEqual(len(candidates), 1)
            self.assertIs(
                candidates[0].discovery_status,
                ScenarioDiscoveryStatus.INVALID,
            )
            with self.assertRaises(BundledScenarioSourceError):
                source.resolve_package(forged)

    def test_template_archive_contains_only_template_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            template = root / "_template"
            template.mkdir()
            (template / "scenario.jsonc").write_text("// comments\n{}")
            (template / "criteria.jsonc").write_text("{}")
            (template / "ignored.pyc").write_bytes(b"bytecode")
            (template / "scenario.jsonc:Zone.Identifier").write_text("metadata")
            self._write_scenario(root / "production", title="Production")
            source = FilesystemBundledScenarioSource(root, template)

            archive = source.build_template_archive()
            candidates = source.discover()

            with ZipFile(io.BytesIO(archive.content)) as template_zip:
                archived_paths = tuple(sorted(template_zip.namelist()))

        self.assertEqual(
            archived_paths,
            (
                "scenario-template/criteria.jsonc",
                "scenario-template/scenario.jsonc",
            ),
        )
        self.assertEqual(
            tuple(candidate.relative_directory for candidate in candidates),
            ("production",),
        )

    @staticmethod
    def _write_scenario(directory: Path, *, title: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "scenario.json").write_text(
            json.dumps(
                {
                    "title": title,
                    "scenario_version": "1.0",
                }
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
