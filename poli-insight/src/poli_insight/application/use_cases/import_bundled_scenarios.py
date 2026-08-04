"""Discover and independently import configured bundled scenario packages."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import quote

from poli_insight.application.ports.bundled_scenarios import (
    BundledScenarioCandidate,
    BundledScenarioSource,
    BundledScenarioSourceError,
    ScenarioDiscoveryStatus,
    ScenarioTemplateArchive,
)
from poli_insight.application.use_cases.import_scenario import (
    ImportScenario,
    ImportScenarioCommand,
    ScenarioImportError,
)
from poli_insight.core.ids import new_id
from poli_insight.domain.enum import ActorType


logger = logging.getLogger(__name__)
BatchProgress = Callable[[int, int, BundledScenarioCandidate], None]


class BundledScenarioOutcomeStatus(StrEnum):
    IMPORTED = "imported"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ImportBundledScenariosCommand:
    actor_id: str
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    actor_type: ActorType = ActorType.USER

    def __post_init__(self) -> None:
        if not self.actor_id.strip():
            raise ValueError("actor_id cannot be empty.")
        if not self.correlation_id.strip():
            raise ValueError("correlation_id cannot be empty.")


@dataclass(frozen=True, slots=True)
class BundledScenarioDiscoveryResult:
    correlation_id: str
    candidates: tuple[BundledScenarioCandidate, ...]
    error_message: str | None = None

    @property
    def ready_count(self) -> int:
        return sum(
            candidate.discovery_status == ScenarioDiscoveryStatus.READY
            for candidate in self.candidates
        )


@dataclass(frozen=True, slots=True)
class BundledScenarioImportOutcome:
    display_name: str
    relative_directory: str
    declared_version: str | None
    status: BundledScenarioOutcomeStatus
    snapshot_id: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class ImportBundledScenariosResult:
    correlation_id: str
    discovered_count: int
    imported_count: int
    skipped_duplicate_count: int
    failed_count: int
    outcomes: tuple[BundledScenarioImportOutcome, ...]
    discovery_error: str | None = None

    def __post_init__(self) -> None:
        counts = (
            self.discovered_count,
            self.imported_count,
            self.skipped_duplicate_count,
            self.failed_count,
        )
        if any(count < 0 for count in counts):
            raise ValueError("Bundled scenario result counts cannot be negative.")
        if self.discovery_error is None and self.discovered_count != len(
            self.outcomes
        ):
            raise ValueError("Every discovered package must have an outcome.")
        if (
            self.imported_count
            + self.skipped_duplicate_count
            + self.failed_count
            != len(self.outcomes)
        ):
            raise ValueError("Bundled scenario outcome counts are inconsistent.")


class ImportBundledScenarios:
    """Batch orchestrator that retains one transaction per scenario import."""

    def __init__(
        self,
        source: BundledScenarioSource,
        importer: ImportScenario,
    ) -> None:
        self._source = source
        self._importer = importer

    def discover(self, *, correlation_id: str) -> BundledScenarioDiscoveryResult:
        if not correlation_id.strip():
            raise ValueError("correlation_id cannot be empty.")
        try:
            candidates = self._source.discover()
        except Exception:  # noqa: BLE001 - adapter details remain server-side
            logger.exception(
                "Bundled scenario discovery failed [%s]",
                correlation_id,
            )
            return BundledScenarioDiscoveryResult(
                correlation_id=correlation_id,
                candidates=(),
                error_message="Bundled scenarios could not be discovered.",
            )
        return BundledScenarioDiscoveryResult(
            correlation_id=correlation_id,
            candidates=candidates,
        )

    def execute(
        self,
        command: ImportBundledScenariosCommand,
        *,
        candidates: Sequence[BundledScenarioCandidate] | None = None,
        on_progress: BatchProgress | None = None,
    ) -> ImportBundledScenariosResult:
        discovery_error: str | None = None
        if candidates is None:
            discovery = self.discover(correlation_id=command.correlation_id)
            discovered = discovery.candidates
            discovery_error = discovery.error_message
        else:
            discovered = tuple(candidates)

        if discovery_error is not None:
            return ImportBundledScenariosResult(
                correlation_id=command.correlation_id,
                discovered_count=0,
                imported_count=0,
                skipped_duplicate_count=0,
                failed_count=0,
                outcomes=(),
                discovery_error=discovery_error,
            )

        outcomes: list[BundledScenarioImportOutcome] = []
        total = len(discovered)
        for index, candidate in enumerate(discovered, start=1):
            outcome = self._import_candidate(command, candidate)
            outcomes.append(outcome)
            if on_progress is not None:
                on_progress(index, total, candidate)

        imported_count = sum(
            outcome.status == BundledScenarioOutcomeStatus.IMPORTED
            for outcome in outcomes
        )
        skipped_count = sum(
            outcome.status == BundledScenarioOutcomeStatus.SKIPPED
            for outcome in outcomes
        )
        failed_count = sum(
            outcome.status == BundledScenarioOutcomeStatus.FAILED
            for outcome in outcomes
        )
        return ImportBundledScenariosResult(
            correlation_id=command.correlation_id,
            discovered_count=total,
            imported_count=imported_count,
            skipped_duplicate_count=skipped_count,
            failed_count=failed_count,
            outcomes=tuple(outcomes),
        )

    def template_archive(self) -> ScenarioTemplateArchive:
        return self._source.build_template_archive()

    def _import_candidate(
        self,
        command: ImportBundledScenariosCommand,
        candidate: BundledScenarioCandidate,
    ) -> BundledScenarioImportOutcome:
        if candidate.discovery_status != ScenarioDiscoveryStatus.READY:
            return _failed_outcome(
                candidate,
                candidate.error_message
                or "The bundled scenario package is not importable.",
            )

        source_directory: Path | None = None
        try:
            source_directory = self._source.resolve_package(candidate)
            result = self._importer.execute(
                ImportScenarioCommand(
                    source_directory=source_directory,
                    actor_id=command.actor_id,
                    correlation_id=command.correlation_id,
                    source_uri=(
                        "urn:poli-insight:bundled-scenario:"
                        f"{quote(candidate.relative_directory, safe='')}"
                    ),
                    actor_type=command.actor_type,
                )
            )
        except (BundledScenarioSourceError, ScenarioImportError) as error:
            logger.warning(
                "Bundled scenario import failed [%s] package=%s",
                command.correlation_id,
                candidate.relative_directory,
                exc_info=True,
            )
            return _failed_outcome(
                candidate,
                _safe_import_error(
                    error,
                    source_directory=source_directory,
                ),
            )
        except Exception:  # noqa: BLE001 - continue independent packages
            logger.exception(
                "Unexpected bundled scenario import failure [%s] package=%s",
                command.correlation_id,
                candidate.relative_directory,
            )
            return _failed_outcome(
                candidate,
                "The package could not be imported because of an internal error.",
            )

        return BundledScenarioImportOutcome(
            display_name=candidate.display_name,
            relative_directory=candidate.relative_directory,
            declared_version=candidate.declared_version,
            status=(
                BundledScenarioOutcomeStatus.IMPORTED
                if result.created
                else BundledScenarioOutcomeStatus.SKIPPED
            ),
            snapshot_id=result.scenario_snapshot_id,
        )


def _failed_outcome(
    candidate: BundledScenarioCandidate,
    message: str,
) -> BundledScenarioImportOutcome:
    return BundledScenarioImportOutcome(
        display_name=candidate.display_name,
        relative_directory=candidate.relative_directory,
        declared_version=candidate.declared_version,
        status=BundledScenarioOutcomeStatus.FAILED,
        error_message=message,
    )


def _safe_import_error(
    error: Exception,
    *,
    source_directory: Path | None,
) -> str:
    message = " ".join(str(error).split())
    if source_directory is not None:
        sensitive_paths = (
            str(source_directory),
            str(source_directory.parent),
        )
        for sensitive_path in sensitive_paths:
            message = message.replace(sensitive_path, "bundled package")
    if not message:
        return "The package could not be imported."
    return message[:500]
