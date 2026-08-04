"""Read-only discovery and template packaging for bundled scenarios."""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from poli_insight.application.ports.bundled_scenarios import (
    BundledScenarioCandidate,
    BundledScenarioSourceError,
    ScenarioConfigurationType,
    ScenarioDiscoveryStatus,
    ScenarioTemplateArchive,
)


_SAFE_DIRECTORY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MAX_SCENARIO_CONFIG_BYTES = 1024 * 1024
_MAX_TEMPLATE_BYTES = 25 * 1024 * 1024
_MAX_TEMPLATE_FILES = 500
_CONFIG_FILENAMES = frozenset(
    {
        "criteria.json",
        "criteria.jsonc",
        "data_sources.json",
        "data_sources.jsonc",
        "preprocessing.json",
        "preprocessing.jsonc",
        "session_rules.json",
        "session_rules.jsonc",
        "ui_config.json",
        "ui_config.jsonc",
    }
)


class FilesystemBundledScenarioSource:
    """Discover immediate scenario directories beneath one validated root."""

    def __init__(
        self,
        source_root: Path,
        template_directory: Path | None,
    ) -> None:
        self._root = source_root.resolve(strict=True)
        if not self._root.is_dir():
            raise BundledScenarioSourceError(
                "The bundled scenario source is unavailable."
            )
        self._template = (
            template_directory.resolve(strict=True)
            if template_directory is not None
            else None
        )
        if self._template is not None and (
            not self._template.is_dir()
            or not self._template.is_relative_to(self._root)
        ):
            raise BundledScenarioSourceError(
                "The scenario template configuration is invalid."
            )

    def discover(self) -> tuple[BundledScenarioCandidate, ...]:
        try:
            entries = sorted(
                self._root.iterdir(),
                key=lambda path: (path.name.casefold(), path.name),
            )
            candidates = [
                candidate
                for entry in entries
                if (candidate := self._inspect_entry(entry)) is not None
            ]
        except BundledScenarioSourceError:
            raise
        except OSError as error:
            raise BundledScenarioSourceError(
                "Bundled scenarios could not be scanned."
            ) from error
        return tuple(candidates)

    def resolve_package(
        self,
        candidate: BundledScenarioCandidate,
    ) -> Path:
        if candidate.discovery_status != ScenarioDiscoveryStatus.READY:
            raise BundledScenarioSourceError(
                "The bundled scenario package is not importable."
            )
        relative = Path(candidate.relative_directory)
        if (
            len(relative.parts) != 1
            or relative.name != candidate.relative_directory
            or not _SAFE_DIRECTORY_NAME.fullmatch(relative.name)
        ):
            raise BundledScenarioSourceError(
                "The bundled scenario package name is invalid."
            )
        try:
            package = (self._root / relative).resolve(strict=True)
        except OSError as error:
            raise BundledScenarioSourceError(
                "The bundled scenario package is unavailable."
            ) from error
        if (
            not package.is_dir()
            or not package.is_relative_to(self._root)
            or package == self._template
        ):
            raise BundledScenarioSourceError(
                "The bundled scenario package is outside the configured source."
            )
        return package

    def build_template_archive(self) -> ScenarioTemplateArchive:
        template = self._template
        if template is None:
            raise BundledScenarioSourceError(
                "No scenario template directory is configured."
            )
        try:
            files = self._template_files()
            buffer = io.BytesIO()
            with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
                for path in files:
                    relative = path.relative_to(template).as_posix()
                    archive.writestr(
                        f"scenario-template/{relative}",
                        path.read_bytes(),
                    )
        except BundledScenarioSourceError:
            raise
        except OSError as error:
            raise BundledScenarioSourceError(
                "The scenario template could not be packaged."
            ) from error
        return ScenarioTemplateArchive(
            filename="poli-insight-scenario-template.zip",
            content=buffer.getvalue(),
            file_paths=tuple(
                f"scenario-template/{path.relative_to(template).as_posix()}"
                for path in files
            ),
        )

    def _inspect_entry(
        self,
        entry: Path,
    ) -> BundledScenarioCandidate | None:
        relative_name = entry.name
        safe_name = _safe_text(relative_name.replace("_", " ").title())
        if entry.is_symlink():
            try:
                resolved_entry = entry.resolve(strict=True)
            except OSError:
                return _invalid_candidate(
                    safe_name,
                    relative_name,
                    "The package link target is unavailable.",
                )
            if not resolved_entry.is_relative_to(self._root):
                return _invalid_candidate(
                    safe_name,
                    relative_name,
                    "The package link points outside the configured source.",
                )
        else:
            resolved_entry = entry.resolve()

        if not resolved_entry.is_dir():
            return None
        if self._template is not None and resolved_entry == self._template:
            return None
        if not _SAFE_DIRECTORY_NAME.fullmatch(relative_name):
            return _invalid_candidate(
                safe_name or "Invalid package",
                _safe_text(relative_name),
                "The directory name is not valid for a bundled scenario.",
            )

        scenario_json = resolved_entry / "scenario.json"
        scenario_jsonc = resolved_entry / "scenario.jsonc"
        if scenario_jsonc.is_file() and not scenario_json.is_file():
            return None
        if not scenario_json.is_file():
            if _contains_scenario_configuration(resolved_entry):
                return _invalid_candidate(
                    safe_name,
                    relative_name,
                    "scenario.json is required for bundled production scenarios.",
                )
            return None

        try:
            resolved_config = scenario_json.resolve(strict=True)
        except OSError:
            return _invalid_candidate(
                safe_name,
                relative_name,
                "scenario.json is unavailable.",
            )
        if not resolved_config.is_relative_to(resolved_entry):
            return _invalid_candidate(
                safe_name,
                relative_name,
                "scenario.json points outside its package directory.",
            )

        try:
            if resolved_config.stat().st_size > _MAX_SCENARIO_CONFIG_BYTES:
                return _invalid_candidate(
                    safe_name,
                    relative_name,
                    "scenario.json exceeds the discovery size limit.",
                    configuration_type=(
                        ScenarioConfigurationType.PRODUCTION_JSON
                    ),
                )
            document = json.loads(resolved_config.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return _invalid_candidate(
                safe_name,
                relative_name,
                "scenario.json is not a valid JSON document.",
                configuration_type=ScenarioConfigurationType.PRODUCTION_JSON,
            )
        if not isinstance(document, dict):
            return _invalid_candidate(
                safe_name,
                relative_name,
                "scenario.json must contain a JSON object.",
                configuration_type=ScenarioConfigurationType.PRODUCTION_JSON,
            )

        title = document.get("title")
        version = document.get("scenario_version")
        display_name = (
            _safe_text(title) if isinstance(title, str) else safe_name
        )
        declared_version = (
            _safe_text(version) if isinstance(version, str) else None
        )
        if not display_name or not declared_version:
            return _invalid_candidate(
                display_name or safe_name,
                relative_name,
                "scenario.json must declare a title and scenario_version.",
                declared_version=declared_version,
                configuration_type=ScenarioConfigurationType.PRODUCTION_JSON,
            )
        return BundledScenarioCandidate(
            display_name=display_name,
            relative_directory=relative_name,
            configuration_type=ScenarioConfigurationType.PRODUCTION_JSON,
            discovery_status=ScenarioDiscoveryStatus.READY,
            declared_version=declared_version,
        )

    def _template_files(self) -> tuple[Path, ...]:
        template = self._template
        if template is None:
            raise BundledScenarioSourceError(
                "No scenario template directory is configured."
            )
        files: list[Path] = []
        total_bytes = 0
        for current_root, directories, filenames in os.walk(
            template,
            followlinks=False,
        ):
            current = Path(current_root)
            symlinked_directories = [
                name for name in directories if (current / name).is_symlink()
            ]
            if symlinked_directories:
                raise BundledScenarioSourceError(
                    "Symbolic links are not allowed in the scenario template."
                )
            directories[:] = sorted(
                name for name in directories if name != "__pycache__"
            )
            for filename in sorted(filenames):
                path = current / filename
                if (
                    path.is_symlink()
                    or filename.endswith(":Zone.Identifier")
                    or filename.endswith(".pyc")
                ):
                    continue
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(template):
                    raise BundledScenarioSourceError(
                        "The scenario template contains an unsafe file path."
                    )
                if resolved.is_file():
                    files.append(resolved)
                    total_bytes += resolved.stat().st_size
                    if (
                        len(files) > _MAX_TEMPLATE_FILES
                        or total_bytes > _MAX_TEMPLATE_BYTES
                    ):
                        raise BundledScenarioSourceError(
                            "The scenario template exceeds the packaging limits."
                        )
        return tuple(
            sorted(
                files,
                key=lambda path: path.relative_to(template).as_posix(),
            )
        )


def _contains_scenario_configuration(directory: Path) -> bool:
    try:
        return any(
            path.is_file() and path.name.casefold() in _CONFIG_FILENAMES
            for path in directory.iterdir()
        )
    except OSError as error:
        raise BundledScenarioSourceError(
            "A bundled scenario directory could not be inspected."
        ) from error


def _invalid_candidate(
    display_name: str,
    relative_directory: str,
    error_message: str,
    *,
    declared_version: str | None = None,
    configuration_type: ScenarioConfigurationType = (
        ScenarioConfigurationType.MISSING
    ),
) -> BundledScenarioCandidate:
    return BundledScenarioCandidate(
        display_name=display_name,
        relative_directory=relative_directory,
        configuration_type=configuration_type,
        discovery_status=ScenarioDiscoveryStatus.INVALID,
        declared_version=declared_version,
        error_message=error_message,
    )


def _safe_text(value: str, *, limit: int = 200) -> str:
    normalized = " ".join(value.split())
    printable = "".join(
        character for character in normalized if character.isprintable()
    )
    return printable[:limit]
