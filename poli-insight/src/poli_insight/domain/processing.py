"""Versioned validation bundles and deterministic weighting artifacts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Self

from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import ArtifactType, RunInclusionStatus, RunStatus

JsonObject = Mapping[str, Any]


class ProcessingRuleViolation(ValueError):
    pass


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProcessingRuleViolation(f"{label} must be nonempty and trimmed.")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProcessingRuleViolation(f"{label} must include timezone information.")


@dataclass(frozen=True, slots=True)
class ProcessingRunSubmission:
    processing_run_id: str
    submission_id: str
    participant_id: str
    stakeholder_group_id: str
    inclusion_status: RunInclusionStatus
    validation_id: str | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.processing_run_id, "Processing run ID"),
            (self.submission_id, "Run submission ID"),
            (self.participant_id, "Run participant ID"),
            (self.stakeholder_group_id, "Run stakeholder group ID"),
        ):
            _text(value, label)
        if self.validation_id is not None:
            _text(self.validation_id, "Run validation ID")
        if self.inclusion_status in {
            RunInclusionStatus.INCLUDED,
            RunInclusionStatus.PENDING_REVIEW,
        } and self.validation_id is None:
            raise ProcessingRuleViolation(
                "Included or pending-review submissions require validation evidence."
            )
        if self.inclusion_status == RunInclusionStatus.INCLUDED:
            if self.exclusion_reason is not None:
                raise ProcessingRuleViolation(
                    "Included submissions cannot have an exclusion reason."
                )
        elif (
            self.inclusion_status != RunInclusionStatus.PENDING_REVIEW
            and self.exclusion_reason is None
        ):
            raise ProcessingRuleViolation(
                "Excluded submissions require a stable reason."
            )

    def to_manifest(self) -> dict[str, object]:
        return {
            "submission_id": self.submission_id,
            "participant_id": self.participant_id,
            "stakeholder_group_id": self.stakeholder_group_id,
            "validation_id": self.validation_id,
            "inclusion_status": self.inclusion_status.value,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True, slots=True)
class ProcessingMatrix:
    processing_matrix_id: str
    processing_run_id: str
    level: str
    criterion_ids: tuple[str, ...]
    matrix_json: JsonObject
    weights_json: JsonObject
    diagnostics_json: JsonObject
    matrix_hash: str
    stakeholder_group_id: str | None = None
    validation_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.processing_matrix_id, "Processing matrix ID")
        _text(self.processing_run_id, "Processing matrix run ID")
        if self.level not in {"participant", "stakeholder_group", "session"}:
            raise ProcessingRuleViolation("Unsupported processing matrix level.")
        if not self.criterion_ids or len(set(self.criterion_ids)) != len(
            self.criterion_ids
        ):
            raise ProcessingRuleViolation(
                "Processing matrix criterion order must be nonempty and unique."
            )
        if self.level == "stakeholder_group" and self.stakeholder_group_id is None:
            raise ProcessingRuleViolation("Group matrices require a stakeholder group.")
        if self.level == "participant" and self.validation_id is None:
            raise ProcessingRuleViolation("Participant matrices require a validation.")
        if self.matrix_hash != hash_json(self._matrix_manifest()):
            raise ProcessingRuleViolation("Processing matrix hash is inconsistent.")

    @classmethod
    def create(
        cls,
        *,
        processing_matrix_id: str,
        processing_run_id: str,
        level: str,
        criterion_ids: tuple[str, ...],
        matrix_json: JsonObject,
        weights_json: JsonObject,
        diagnostics_json: JsonObject,
        stakeholder_group_id: str | None = None,
        validation_id: str | None = None,
    ) -> Self:
        manifest = {
            "criterion_ids": list(criterion_ids),
            "matrix": dict(matrix_json),
        }
        return cls(
            processing_matrix_id=processing_matrix_id,
            processing_run_id=processing_run_id,
            level=level,
            criterion_ids=criterion_ids,
            matrix_json=dict(matrix_json),
            weights_json=dict(weights_json),
            diagnostics_json=dict(diagnostics_json),
            matrix_hash=hash_json(manifest),
            stakeholder_group_id=stakeholder_group_id,
            validation_id=validation_id,
        )

    def _matrix_manifest(self) -> dict[str, object]:
        return {
            "criterion_ids": list(self.criterion_ids),
            "matrix": dict(self.matrix_json),
        }

    def to_manifest(self) -> dict[str, object]:
        return {
            "level": self.level,
            "stakeholder_group_id": self.stakeholder_group_id,
            "validation_id": self.validation_id,
            "criterion_ids": list(self.criterion_ids),
            "matrix": dict(self.matrix_json),
            "weights": dict(self.weights_json),
            "diagnostics": dict(self.diagnostics_json),
            "matrix_hash": self.matrix_hash,
        }


@dataclass(frozen=True, slots=True)
class RunArtifact:
    run_artifact_id: str
    processing_run_id: str
    artifact_type: ArtifactType
    schema_version: int
    content_json: JsonObject
    content_hash: str

    def __post_init__(self) -> None:
        _text(self.run_artifact_id, "Run artifact ID")
        _text(self.processing_run_id, "Run artifact processing ID")
        if self.schema_version < 1:
            raise ProcessingRuleViolation("Artifact schema version must be positive.")
        if self.content_hash != hash_json(self.content_json):
            raise ProcessingRuleViolation("Run artifact hash is inconsistent.")

    @classmethod
    def create(
        cls,
        *,
        run_artifact_id: str,
        processing_run_id: str,
        artifact_type: ArtifactType,
        schema_version: int,
        content_json: JsonObject,
    ) -> Self:
        return cls(
            run_artifact_id=run_artifact_id,
            processing_run_id=processing_run_id,
            artifact_type=artifact_type,
            schema_version=schema_version,
            content_json=dict(content_json),
            content_hash=hash_json(content_json),
        )


@dataclass(frozen=True, slots=True)
class ProcessingRun:
    processing_run_id: str
    session_id: str
    configuration_version_id: str
    scenario_snapshot_id: str
    run_number: int
    status: RunStatus
    roster_hash: str
    input_hash: str
    algorithm_implementation_id: str
    parameter_json: JsonObject
    environment_json: JsonObject
    created_at: datetime
    created_by: str
    submissions: tuple[ProcessingRunSubmission, ...]
    matrices: tuple[ProcessingMatrix, ...] = field(default_factory=tuple)
    artifacts: tuple[RunArtifact, ...] = field(default_factory=tuple)
    completed_at: datetime | None = None
    output_hash: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.processing_run_id, "Processing run ID"),
            (self.session_id, "Processing session ID"),
            (self.configuration_version_id, "Processing configuration ID"),
            (self.scenario_snapshot_id, "Processing scenario ID"),
            (self.algorithm_implementation_id, "Processing algorithm ID"),
            (self.created_by, "Processing creator"),
        ):
            _text(value, label)
        if self.run_number < 1:
            raise ProcessingRuleViolation("Processing run number must be positive.")
        _aware(self.created_at, "Processing creation time")
        if self.completed_at is not None:
            _aware(self.completed_at, "Processing completion time")
        if self.status == RunStatus.SUCCEEDED and (
            self.completed_at is None or self.output_hash is None
        ):
            raise ProcessingRuleViolation(
                "Succeeded processing runs require completion evidence."
            )
        if len({item.submission_id for item in self.submissions}) != len(
            self.submissions
        ):
            raise ProcessingRuleViolation("Run submissions must be unique.")

    @classmethod
    def awaiting_review(
        cls,
        *,
        processing_run_id: str,
        session_id: str,
        configuration_version_id: str,
        scenario_snapshot_id: str,
        run_number: int,
        roster_hash: str,
        algorithm_implementation_id: str,
        parameter_json: JsonObject,
        environment_json: JsonObject,
        created_at: datetime,
        created_by: str,
        submissions: tuple[ProcessingRunSubmission, ...],
    ) -> Self:
        input_manifest = {
            "schema_version": 1,
            "session_id": session_id,
            "configuration_version_id": configuration_version_id,
            "scenario_snapshot_id": scenario_snapshot_id,
            "roster_hash": roster_hash,
            "algorithm_implementation_id": algorithm_implementation_id,
            "parameters": dict(parameter_json),
            "submissions": [item.to_manifest() for item in submissions],
        }
        return cls(
            processing_run_id=processing_run_id,
            session_id=session_id,
            configuration_version_id=configuration_version_id,
            scenario_snapshot_id=scenario_snapshot_id,
            run_number=run_number,
            status=RunStatus.AWAITING_REVIEW,
            roster_hash=roster_hash,
            input_hash=hash_json(input_manifest),
            algorithm_implementation_id=algorithm_implementation_id,
            parameter_json=dict(parameter_json),
            environment_json=dict(environment_json),
            created_at=created_at,
            created_by=created_by,
            submissions=submissions,
        )

    def complete(
        self,
        *,
        at: datetime,
        submissions: tuple[ProcessingRunSubmission, ...],
        matrices: tuple[ProcessingMatrix, ...],
        artifacts: tuple[RunArtifact, ...],
    ) -> Self:
        if self.status != RunStatus.AWAITING_REVIEW:
            raise ProcessingRuleViolation(
                "Only an awaiting-review run can be finalized."
            )
        output_manifest = {
            "schema_version": 1,
            "input_hash": self.input_hash,
            "submissions": [item.to_manifest() for item in submissions],
            "matrices": [item.to_manifest() for item in matrices],
            "artifacts": [item.content_hash for item in artifacts],
        }
        return replace(
            self,
            status=RunStatus.SUCCEEDED,
            submissions=submissions,
            matrices=matrices,
            artifacts=artifacts,
            completed_at=at,
            output_hash=hash_json(output_manifest),
        )
