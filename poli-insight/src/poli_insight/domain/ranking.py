"""Immutable, algorithm-neutral ranking runs and result evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Self

from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import ArtifactType, RunStatus

JsonObject = Mapping[str, Any]


class RankingRuleViolation(ValueError):
    pass


def _text(value: str, label: str) -> None:
    if not value.strip() or value != value.strip():
        raise RankingRuleViolation(f"{label} must be nonempty and trimmed.")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise RankingRuleViolation(f"{label} must include timezone information.")


@dataclass(frozen=True, slots=True)
class RankedAlternative:
    alternative_id: str
    rank: int
    preference_value: Decimal
    method_metrics_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _text(self.alternative_id, "Ranked alternative ID")
        if self.rank < 1:
            raise RankingRuleViolation("Alternative rank must be positive.")
        if not self.preference_value.is_finite():
            raise RankingRuleViolation("Preference values must be finite.")

    def to_manifest(self) -> dict[str, object]:
        return {
            "alternative_id": self.alternative_id,
            "rank": self.rank,
            "preference_value": self.preference_value,
            "method_metrics": dict(self.method_metrics_json),
        }


@dataclass(frozen=True, slots=True)
class RankingResult:
    ranking_result_id: str
    ranking_run_id: str
    source_processing_matrix_id: str
    level: str
    alternatives: tuple[RankedAlternative, ...]
    metric_label: str
    diagnostics_json: JsonObject
    result_hash: str
    stakeholder_group_id: str | None = None
    validation_id: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.ranking_result_id, "Ranking result ID"),
            (self.ranking_run_id, "Ranking result run ID"),
            (self.source_processing_matrix_id, "Source processing matrix ID"),
            (self.metric_label, "Ranking result metric label"),
        ):
            _text(value, label)
        if self.level not in {"participant", "stakeholder_group", "session"}:
            raise RankingRuleViolation("Unsupported ranking evidence level.")
        if self.level == "participant" and self.validation_id is None:
            raise RankingRuleViolation(
                "Participant rankings require validation identity."
            )
        if self.level != "participant" and self.validation_id is not None:
            raise RankingRuleViolation(
                "Aggregate ranking results cannot contain validation identity."
            )
        if self.level == "stakeholder_group" and self.stakeholder_group_id is None:
            raise RankingRuleViolation("Group rankings require stakeholder identity.")
        if not self.alternatives:
            raise RankingRuleViolation("Ranking results cannot be empty.")
        if len({item.alternative_id for item in self.alternatives}) != len(
            self.alternatives
        ):
            raise RankingRuleViolation("Ranked alternatives must be unique.")
        ranks = sorted({item.rank for item in self.alternatives})
        if ranks != list(range(1, len(ranks) + 1)):
            raise RankingRuleViolation("Ranking results require dense ranks.")
        if self.result_hash != hash_json(self._manifest()):
            raise RankingRuleViolation("Ranking result hash is inconsistent.")

    @classmethod
    def create(
        cls,
        *,
        ranking_result_id: str,
        ranking_run_id: str,
        source_processing_matrix_id: str,
        level: str,
        alternatives: tuple[RankedAlternative, ...],
        metric_label: str,
        diagnostics_json: JsonObject,
        stakeholder_group_id: str | None = None,
        validation_id: str | None = None,
    ) -> Self:
        manifest = {
            "source_processing_matrix_id": source_processing_matrix_id,
            "level": level,
            "stakeholder_group_id": stakeholder_group_id,
            "validation_id": validation_id,
            "metric_label": metric_label,
            "alternatives": [item.to_manifest() for item in alternatives],
            "diagnostics": dict(diagnostics_json),
        }
        return cls(
            ranking_result_id=ranking_result_id,
            ranking_run_id=ranking_run_id,
            source_processing_matrix_id=source_processing_matrix_id,
            level=level,
            stakeholder_group_id=stakeholder_group_id,
            validation_id=validation_id,
            alternatives=alternatives,
            metric_label=metric_label,
            diagnostics_json=dict(diagnostics_json),
            result_hash=hash_json(manifest),
        )

    def _manifest(self) -> dict[str, object]:
        return {
            "source_processing_matrix_id": self.source_processing_matrix_id,
            "level": self.level,
            "stakeholder_group_id": self.stakeholder_group_id,
            "validation_id": self.validation_id,
            "metric_label": self.metric_label,
            "alternatives": [item.to_manifest() for item in self.alternatives],
            "diagnostics": dict(self.diagnostics_json),
        }

    def to_manifest(self) -> dict[str, object]:
        return {**self._manifest(), "result_hash": self.result_hash}


@dataclass(frozen=True, slots=True)
class RankingArtifact:
    ranking_artifact_id: str
    ranking_run_id: str
    artifact_type: ArtifactType
    schema_version: int
    content_json: JsonObject
    content_hash: str

    def __post_init__(self) -> None:
        _text(self.ranking_artifact_id, "Ranking artifact ID")
        _text(self.ranking_run_id, "Ranking artifact run ID")
        if self.schema_version < 1:
            raise RankingRuleViolation(
                "Ranking artifact schema version must be positive."
            )
        if self.content_hash != hash_json(self.content_json):
            raise RankingRuleViolation("Ranking artifact hash is inconsistent.")

    @classmethod
    def create(
        cls,
        *,
        ranking_artifact_id: str,
        ranking_run_id: str,
        artifact_type: ArtifactType,
        schema_version: int,
        content_json: JsonObject,
    ) -> Self:
        return cls(
            ranking_artifact_id=ranking_artifact_id,
            ranking_run_id=ranking_run_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            content_json=dict(content_json),
            content_hash=hash_json(content_json),
        )


@dataclass(frozen=True, slots=True)
class RankingRun:
    ranking_run_id: str
    session_id: str
    source_processing_run_id: str
    configuration_version_id: str
    scenario_snapshot_id: str
    run_number: int
    status: RunStatus
    roster_hash: str
    input_hash: str
    algorithm_implementation_id: str
    implementation_version: str
    adapter_version: str
    parameter_json: JsonObject
    environment_json: JsonObject
    created_at: datetime
    created_by: str
    completed_at: datetime
    results: tuple[RankingResult, ...] = field(default_factory=tuple)
    artifacts: tuple[RankingArtifact, ...] = field(default_factory=tuple)
    output_hash: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.ranking_run_id, "Ranking run ID"),
            (self.session_id, "Ranking session ID"),
            (self.source_processing_run_id, "Source processing run ID"),
            (self.configuration_version_id, "Ranking configuration ID"),
            (self.scenario_snapshot_id, "Ranking scenario ID"),
            (self.algorithm_implementation_id, "Ranking algorithm ID"),
            (self.implementation_version, "Ranking implementation version"),
            (self.adapter_version, "Ranking adapter version"),
            (self.created_by, "Ranking creator"),
        ):
            _text(value, label)
        if self.run_number < 1:
            raise RankingRuleViolation("Ranking run number must be positive.")
        _aware(self.created_at, "Ranking creation time")
        _aware(self.completed_at, "Ranking completion time")
        if self.status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise RankingRuleViolation("Ranking runs must persist a terminal status.")
        if self.status == RunStatus.SUCCEEDED:
            if not self.results or self.output_hash is None:
                raise RankingRuleViolation(
                    "Succeeded ranking runs require results and an output hash."
                )
            if self.failure_code is not None or self.failure_detail is not None:
                raise RankingRuleViolation(
                    "Succeeded ranking runs cannot contain failure fields."
                )
            expected_output_hash = hash_json(
                {
                    "schema_version": 1,
                    "input_hash": self.input_hash,
                    "results": [item.to_manifest() for item in self.results],
                    "artifacts": [item.content_hash for item in self.artifacts],
                }
            )
            if self.output_hash != expected_output_hash:
                raise RankingRuleViolation("Ranking run output hash is inconsistent.")
        else:
            if self.failure_code is None or self.failure_detail is None:
                raise RankingRuleViolation(
                    "Failed ranking runs require safe failure evidence."
                )
            if self.results or self.output_hash is not None:
                raise RankingRuleViolation(
                    "Failed ranking runs cannot contain result evidence."
                )
        if any(item.ranking_run_id != self.ranking_run_id for item in self.results):
            raise RankingRuleViolation("Ranking results belong to a different run.")
        if any(item.ranking_run_id != self.ranking_run_id for item in self.artifacts):
            raise RankingRuleViolation("Ranking artifacts belong to a different run.")

    @classmethod
    def succeeded(
        cls,
        *,
        results: tuple[RankingResult, ...],
        artifacts: tuple[RankingArtifact, ...],
        **values: Any,
    ) -> Self:
        output_hash = hash_json(
            {
                "schema_version": 1,
                "input_hash": values["input_hash"],
                "results": [item.to_manifest() for item in results],
                "artifacts": [item.content_hash for item in artifacts],
            }
        )
        return cls(
            **values,
            status=RunStatus.SUCCEEDED,
            results=results,
            artifacts=artifacts,
            output_hash=output_hash,
        )

    @classmethod
    def failed(cls, *, failure_code: str, failure_detail: str, **values: Any) -> Self:
        return cls(
            **values,
            status=RunStatus.FAILED,
            failure_code=failure_code,
            failure_detail=failure_detail,
        )
