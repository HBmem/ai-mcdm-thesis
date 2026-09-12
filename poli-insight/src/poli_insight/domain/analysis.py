"""Immutable sensitivity and robustness analysis evidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    AnalysisType,
    ArtifactType,
    RunStatus,
)

JsonObject = Mapping[str, Any]


class AnalysisRuleViolation(ValueError):
    pass


_METHOD_TYPES = {
    AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION: AnalysisType.SENSITIVITY,
    AnalysisMethod.CRITERION_REMOVAL: AnalysisType.ROBUSTNESS,
    AnalysisMethod.RANK_REVERSAL: AnalysisType.ROBUSTNESS,
    AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE: AnalysisType.STAKEHOLDER_COMPARISON,
    AnalysisMethod.PARTICIPANT_INFLUENCE: AnalysisType.PARTICIPANT_IMPACT,
}


def analysis_type_for(method: AnalysisMethod) -> AnalysisType:
    return _METHOD_TYPES[method]


def _text(value: str, label: str) -> None:
    if not value.strip() or value != value.strip():
        raise AnalysisRuleViolation(f"{label} must be nonempty and trimmed.")


def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise AnalysisRuleViolation(f"{label} must include timezone information.")


@dataclass(frozen=True, slots=True)
class AnalysisCase:
    analysis_case_id: str
    analysis_run_id: str
    sequence: int
    status: AnalysisCaseStatus
    scope_type: str
    subject_type: str
    subject_id: str | None
    input_json: JsonObject
    result_json: JsonObject
    warnings: tuple[str, ...]
    content_hash: str
    scope_id: str | None = None

    def __post_init__(self) -> None:
        _text(self.analysis_case_id, "Analysis case ID")
        _text(self.analysis_run_id, "Analysis case run ID")
        _text(self.scope_type, "Analysis case scope type")
        _text(self.subject_type, "Analysis case subject type")
        if self.sequence < 1:
            raise AnalysisRuleViolation("Analysis case sequence must be positive.")
        if self.subject_id is not None:
            _text(self.subject_id, "Analysis case subject ID")
        if self.scope_id is not None:
            _text(self.scope_id, "Analysis case scope ID")
        if self.content_hash != hash_json(self._manifest()):
            raise AnalysisRuleViolation("Analysis case hash is inconsistent.")

    @classmethod
    def create(cls, **values: Any) -> Self:
        manifest = {
            "sequence": values["sequence"],
            "status": values["status"].value,
            "scope_type": values["scope_type"],
            "scope_id": values.get("scope_id"),
            "subject_type": values["subject_type"],
            "subject_id": values.get("subject_id"),
            "input": dict(values.get("input_json", {})),
            "result": dict(values.get("result_json", {})),
            "warnings": list(values.get("warnings", ())),
        }
        return cls(**values, content_hash=hash_json(manifest))

    def _manifest(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "status": self.status.value,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "input": dict(self.input_json),
            "result": dict(self.result_json),
            "warnings": list(self.warnings),
        }

    def to_manifest(self) -> dict[str, object]:
        return {**self._manifest(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class AnalysisArtifact:
    analysis_artifact_id: str
    analysis_run_id: str
    artifact_type: ArtifactType
    schema_version: int
    content_json: JsonObject
    content_hash: str

    def __post_init__(self) -> None:
        _text(self.analysis_artifact_id, "Analysis artifact ID")
        _text(self.analysis_run_id, "Analysis artifact run ID")
        if self.schema_version < 1:
            raise AnalysisRuleViolation("Analysis artifact schema must be positive.")
        if self.content_hash != hash_json(self.content_json):
            raise AnalysisRuleViolation("Analysis artifact hash is inconsistent.")

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(**values, content_hash=hash_json(values["content_json"]))


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    analysis_run_id: str
    session_id: str
    source_processing_run_id: str
    source_ranking_run_id: str
    run_number: int
    analysis_type: AnalysisType
    method: AnalysisMethod
    status: RunStatus
    source_processing_output_hash: str
    source_ranking_output_hash: str
    input_hash: str
    parameter_json: JsonObject
    environment_json: JsonObject
    created_at: datetime
    created_by: str
    completed_at: datetime
    correlation_id: str
    cases: tuple[AnalysisCase, ...] = field(default_factory=tuple)
    artifacts: tuple[AnalysisArtifact, ...] = field(default_factory=tuple)
    output_hash: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.analysis_run_id, "Analysis run ID"),
            (self.session_id, "Analysis session ID"),
            (self.source_processing_run_id, "Analysis processing run ID"),
            (self.source_ranking_run_id, "Analysis ranking run ID"),
            (self.source_processing_output_hash, "Processing output hash"),
            (self.source_ranking_output_hash, "Ranking output hash"),
            (self.input_hash, "Analysis input hash"),
            (self.created_by, "Analysis creator"),
            (self.correlation_id, "Analysis correlation ID"),
        ):
            _text(value, label)
        if self.run_number < 1:
            raise AnalysisRuleViolation("Analysis run number must be positive.")
        if self.analysis_type != analysis_type_for(self.method):
            raise AnalysisRuleViolation("Analysis method and category do not match.")
        _aware(self.created_at, "Analysis creation time")
        _aware(self.completed_at, "Analysis completion time")
        if self.status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise AnalysisRuleViolation("Analysis runs must be terminal.")
        if any(item.analysis_run_id != self.analysis_run_id for item in self.cases):
            raise AnalysisRuleViolation("Analysis cases belong to another run.")
        if any(item.analysis_run_id != self.analysis_run_id for item in self.artifacts):
            raise AnalysisRuleViolation("Analysis artifacts belong to another run.")
        if self.status == RunStatus.SUCCEEDED:
            if not self.cases or self.output_hash is None:
                raise AnalysisRuleViolation(
                    "Successful analyses require cases and output evidence."
                )
            if self.failure_code is not None or self.failure_detail is not None:
                raise AnalysisRuleViolation(
                    "Successful analyses cannot have failure evidence."
                )
            expected = hash_json(
                {
                    "schema_version": 1,
                    "input_hash": self.input_hash,
                    "cases": [item.content_hash for item in self.cases],
                    "artifacts": [item.content_hash for item in self.artifacts],
                }
            )
            if self.output_hash != expected:
                raise AnalysisRuleViolation("Analysis output hash is inconsistent.")
        elif self.failure_code is None or self.failure_detail is None:
            raise AnalysisRuleViolation(
                "Failed analyses require safe failure evidence."
            )

    @classmethod
    def succeeded(
        cls,
        *,
        cases: tuple[AnalysisCase, ...],
        artifacts: tuple[AnalysisArtifact, ...],
        **values: Any,
    ) -> Self:
        output_hash = hash_json(
            {
                "schema_version": 1,
                "input_hash": values["input_hash"],
                "cases": [item.content_hash for item in cases],
                "artifacts": [item.content_hash for item in artifacts],
            }
        )
        return cls(
            **values,
            status=RunStatus.SUCCEEDED,
            cases=cases,
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


@dataclass(frozen=True, slots=True)
class AnalysisRunSummary:
    """Analysis history projection that does not hydrate variable-size cases."""

    analysis_run_id: str
    session_id: str
    source_processing_run_id: str
    source_ranking_run_id: str
    run_number: int
    analysis_type: AnalysisType
    method: AnalysisMethod
    status: RunStatus
    source_processing_output_hash: str
    source_ranking_output_hash: str
    input_hash: str
    parameter_json: JsonObject
    environment_json: JsonObject
    created_at: datetime
    created_by: str
    completed_at: datetime
    correlation_id: str
    artifacts: tuple[AnalysisArtifact, ...]
    output_hash: str | None
    failure_code: str | None
    failure_detail: str | None
