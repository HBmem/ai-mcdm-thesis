from __future__ import annotations

import io
import unittest
from zipfile import ZipFile, ZipInfo

from poli_insight.presentation.streamlit.components.scenario_archive import (
    ScenarioArchiveError,
    extracted_scenario_directory,
    inspect_scenario_archive,
)


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


class ScenarioArchiveTests(unittest.TestCase):
    def test_inspects_and_extracts_one_nested_package(self) -> None:
        archive_bytes = _archive(
            {
                "scenario/scenario.json": b"{}",
                "scenario/data/source.csv": b"name,value\nA,1\n",
                "README.txt": b"outside the package",
            }
        )

        inspection = inspect_scenario_archive(
            archive_bytes,
            filename="example.zip",
        )

        self.assertEqual(inspection.package_label, "scenario")
        self.assertEqual(inspection.file_count, 2)
        with extracted_scenario_directory(inspection) as source_directory:
            self.assertEqual(
                (source_directory / "scenario.json").read_bytes(),
                b"{}",
            )
            self.assertFalse((source_directory / "README.txt").exists())

    def test_rejects_path_traversal(self) -> None:
        archive_bytes = _archive(
            {
                "scenario.json": b"{}",
                "../outside.txt": b"unsafe",
            }
        )

        with self.assertRaisesRegex(ScenarioArchiveError, "unsafe file path"):
            inspect_scenario_archive(archive_bytes, filename="unsafe.zip")

    def test_rejects_multiple_scenario_packages(self) -> None:
        archive_bytes = _archive(
            {
                "one/scenario.json": b"{}",
                "two/scenario.jsonc": b"{}",
            }
        )

        with self.assertRaisesRegex(ScenarioArchiveError, "one scenario"):
            inspect_scenario_archive(archive_bytes, filename="multiple.zip")

    def test_rejects_symbolic_links(self) -> None:
        buffer = io.BytesIO()
        link = ZipInfo("scenario/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        with ZipFile(buffer, "w") as archive:
            archive.writestr("scenario/scenario.json", b"{}")
            archive.writestr(link, b"target")

        with self.assertRaisesRegex(ScenarioArchiveError, "Symbolic links"):
            inspect_scenario_archive(buffer.getvalue(), filename="links.zip")


if __name__ == "__main__":
    unittest.main()
