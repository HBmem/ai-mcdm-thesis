from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class ScenarioConfigurationType(StrEnum):
    PRODUCTION_JSON = "production_json"
    TEMPLATE_JSONC = "template_jsonc"
    MISSING = "missing"


class ScenarioDiscoveryStatus(StrEnum):
    READY = "ready"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class BundledScenarioCandidate:
    display_name: str
    relative_directory: str
    configuration_type: ScenarioConfigurationType
    discovery_status: ScenarioDiscoveryStatus
    declared_version: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioTemplateArchive:
    filename: str
    content: bytes = field(repr=False)
    file_paths: tuple[str, ...]


class BundledScenarioSourceError(RuntimeError):
    """Safe failure raised by a bundled scenario source adapter."""


class BundledScenarioSource(Protocol):
    def discover(self) -> tuple[BundledScenarioCandidate, ...]:
        """Return immediate bundled packages without exposing absolute paths."""
        ...

    def resolve_package(
        self,
        candidate: BundledScenarioCandidate,
    ) -> Path:
        """Resolve a previously discovered package inside the configured root."""
        ...

    def build_template_archive(self) -> ScenarioTemplateArchive:
        """Build an in-memory archive from the configured template directory."""
        ...
