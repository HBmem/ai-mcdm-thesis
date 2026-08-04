from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from poli_insight.application.use_cases.import_bundled_scenarios import (
    BundledScenarioOutcomeStatus,
    ImportBundledScenarios,
    ImportBundledScenariosCommand,
)
from poli_insight.application.use_cases.import_scenario import (
    ImportScenarioCommand,
    ImportScenarioResult,
    ScenarioImportError,
)
from poli_insight.domain.enum import ScenarioSnapshotStatus
from poli_insight.infrastructure.scenarios.bundled_source import (
    FilesystemBundledScenarioSource,
)


class ContentAddressedFakeImporter:
    def __init__(self) -> None:
        self.snapshots: dict[str, str] = {}

    def execute(self, command: ImportScenarioCommand) -> ImportScenarioResult:
        if (command.source_directory / "fail.marker").exists():
            raise ScenarioImportError(
                f"Invalid package at {command.source_directory}"
            )
        digest = hashlib.sha256()
        for path in sorted(command.source_directory.rglob("*")):
            if path.is_file():
                relative_path = path.relative_to(
                    command.source_directory
                ).as_posix()
                digest.update(relative_path.encode())
                digest.update(path.read_bytes())
        root_hash = digest.hexdigest()
        created = root_hash not in self.snapshots
        snapshot_id = self.snapshots.setdefault(
            root_hash,
            f"snapshot-{len(self.snapshots) + 1}",
        )
        return ImportScenarioResult(
            scenario_definition_id="definition",
            scenario_snapshot_id=snapshot_id,
            root_hash=root_hash,
            materialized_input_hash="m" * 64,
            status=ScenarioSnapshotStatus.READY,
            created=created,
        )


class FailingDiscoverySource:
    def discover(self):
        raise OSError("technical failure at /private/scenarios")


class ImportBundledScenariosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.template = self.root / "_template"
        self.template.mkdir()
        (self.template / "scenario.jsonc").write_text("// template\n{}")
        self._write_package("alpha", title="Alpha")
        self._write_package("beta", title="Beta")
        self.importer = ContentAddressedFakeImporter()
        self.use_case = ImportBundledScenarios(
            FilesystemBundledScenarioSource(self.root, self.template),
            self.importer,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_first_scan_imports_and_second_scan_skips_duplicates(self) -> None:
        first = self.use_case.execute(
            ImportBundledScenariosCommand(
                actor_id="admin",
                correlation_id="first-batch",
            )
        )
        second = self.use_case.execute(
            ImportBundledScenariosCommand(
                actor_id="admin",
                correlation_id="second-batch",
            )
        )

        self.assertEqual(first.discovered_count, 2)
        self.assertEqual(first.imported_count, 2)
        self.assertEqual(first.failed_count, 0)
        self.assertEqual(second.skipped_duplicate_count, 2)
        self.assertTrue(
            all(
                outcome.status == BundledScenarioOutcomeStatus.SKIPPED
                for outcome in second.outcomes
            )
        )

    def test_changed_content_creates_a_new_snapshot(self) -> None:
        first = self.use_case.execute(
            ImportBundledScenariosCommand(actor_id="admin")
        )
        (self.root / "alpha" / "payload.txt").write_text("changed")

        second = self.use_case.execute(
            ImportBundledScenariosCommand(actor_id="admin")
        )

        first_alpha = next(
            outcome
            for outcome in first.outcomes
            if outcome.relative_directory == "alpha"
        )
        second_alpha = next(
            outcome
            for outcome in second.outcomes
            if outcome.relative_directory == "alpha"
        )
        self.assertIs(
            second_alpha.status,
            BundledScenarioOutcomeStatus.IMPORTED,
        )
        self.assertNotEqual(first_alpha.snapshot_id, second_alpha.snapshot_id)
        self.assertEqual(second.skipped_duplicate_count, 1)

    def test_invalid_package_does_not_block_valid_packages_or_leak_paths(self) -> None:
        (self.root / "beta" / "fail.marker").write_text("fail")

        result = self.use_case.execute(
            ImportBundledScenariosCommand(
                actor_id="admin",
                correlation_id="mixed-batch",
            )
        )

        self.assertEqual(result.imported_count, 1)
        self.assertEqual(result.failed_count, 1)
        failed = next(
            outcome
            for outcome in result.outcomes
            if outcome.status == BundledScenarioOutcomeStatus.FAILED
        )
        self.assertIsNotNone(failed.error_message)
        self.assertNotIn(str(self.root), failed.error_message or "")
        self.assertIn("bundled package", failed.error_message or "")

    def test_discovery_failure_is_logged_with_safe_batch_result(self) -> None:
        use_case = ImportBundledScenarios(
            FailingDiscoverySource(),
            self.importer,
        )

        with self.assertLogs(
            "poli_insight.application.use_cases.import_bundled_scenarios",
            level="ERROR",
        ) as captured:
            result = use_case.execute(
                ImportBundledScenariosCommand(
                    actor_id="admin",
                    correlation_id="safe-reference",
                )
            )

        self.assertEqual(
            result.discovery_error,
            "Bundled scenarios could not be discovered.",
        )
        self.assertNotIn("/private/scenarios", result.discovery_error or "")
        self.assertIn("safe-reference", "\n".join(captured.output))

    def _write_package(self, name: str, *, title: str) -> None:
        package = self.root / name
        package.mkdir()
        (package / "scenario.json").write_text(
            json.dumps(
                {
                    "title": title,
                    "scenario_version": "1.0",
                }
            )
        )
        (package / "payload.txt").write_text("initial")


if __name__ == "__main__":
    unittest.main()
