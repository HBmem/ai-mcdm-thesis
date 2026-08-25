"""Provider-neutral contracts for deterministic ranking algorithms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from poli_insight.domain.enum import CriterionDataType, CriterionDirection

JsonObject = Mapping[str, Any]


class RankingContractViolation(ValueError):
    """Raised when a ranking request or adapter result is inconsistent."""


class RankingExecutionError(RuntimeError):
    """Sanitized provider failure safe to persist and present."""

    def __init__(self, *, code: str, safe_detail: str, retryable: bool = False) -> None:
        if not code.strip() or not safe_detail.strip():
            raise RankingContractViolation(
                "Ranking execution errors require a code and safe detail."
            )
        self.code = code
        self.safe_detail = safe_detail
        self.retryable = retryable
        super().__init__(f"{code}: {safe_detail}")


@dataclass(frozen=True, slots=True)
class RankingRunnerMetadata:
    algorithm_implementation_id: str
    implementation_version: str
    adapter_version: str
    parameter_schema_version: int = 1
    capabilities_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, label in (
            (self.algorithm_implementation_id, "Ranking implementation ID"),
            (self.implementation_version, "Ranking implementation version"),
            (self.adapter_version, "Ranking adapter version"),
        ):
            if not value.strip() or value != value.strip():
                raise RankingContractViolation(
                    f"{label} must be nonempty and trimmed."
                )
        if self.parameter_schema_version < 1:
            raise RankingContractViolation(
                "Ranking parameter schema version must be positive."
            )


@dataclass(frozen=True, slots=True)
class RankingAlternativeInput:
    alternative_id: str
    alternative_key: str
    label: str
    display_order: int


@dataclass(frozen=True, slots=True)
class RankingCriterionInput:
    criterion_id: str
    criterion_key: str
    label: str
    direction: CriterionDirection
    data_type: CriterionDataType
    display_order: int


@dataclass(frozen=True, slots=True)
class RankingDecisionCell:
    alternative_id: str
    criterion_id: str
    numeric_value: Decimal | None = None
    structured_value: JsonObject | None = None

    def __post_init__(self) -> None:
        if (self.numeric_value is None) == (self.structured_value is None):
            raise RankingContractViolation(
                "A ranking decision cell requires exactly one value representation."
            )
        if self.numeric_value is not None and not isinstance(
            self.numeric_value, Decimal
        ):
            raise RankingContractViolation(
                "Numeric ranking decision values must use Decimal."
            )


@dataclass(frozen=True, slots=True)
class RankingWeightInput:
    criterion_id: str
    value: Decimal | JsonObject


@dataclass(frozen=True, slots=True)
class RankingRequest:
    """Canonical typed ranking input independent of any provider API."""

    source_processing_matrix_id: str
    alternatives: tuple[RankingAlternativeInput, ...]
    criteria: tuple[RankingCriterionInput, ...]
    cells: tuple[RankingDecisionCell, ...]
    weights: tuple[RankingWeightInput, ...]
    parameters: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_processing_matrix_id.strip():
            raise RankingContractViolation("Source weighting matrix ID is required.")
        if not self.alternatives or not self.criteria:
            raise RankingContractViolation(
                "Ranking requires alternatives and criteria."
            )
        alternative_ids = tuple(item.alternative_id for item in self.alternatives)
        criterion_ids = tuple(item.criterion_id for item in self.criteria)
        if len(set(alternative_ids)) != len(alternative_ids):
            raise RankingContractViolation("Ranking alternatives must be unique.")
        if len(set(criterion_ids)) != len(criterion_ids):
            raise RankingContractViolation("Ranking criteria must be unique.")
        if tuple(item.criterion_id for item in self.weights) != criterion_ids:
            raise RankingContractViolation(
                "Ranking weights must follow the requested criterion order."
            )
        cell_keys = {(item.alternative_id, item.criterion_id) for item in self.cells}
        expected = {
            (alternative_id, criterion_id)
            for alternative_id in alternative_ids
            for criterion_id in criterion_ids
        }
        if cell_keys != expected or len(cell_keys) != len(self.cells):
            raise RankingContractViolation(
                "Ranking decision cells must form one complete rectangular matrix."
            )


@dataclass(frozen=True, slots=True)
class RankingAlternativeResult:
    alternative_id: str
    preference_value: Decimal
    rank: int | None = None
    method_metrics: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.alternative_id.strip():
            raise RankingContractViolation("Ranked alternative ID is required.")
        if not isinstance(self.preference_value, Decimal) or not (
            self.preference_value.is_finite()
        ):
            raise RankingContractViolation(
                "Ranking adapters must return finite Decimal preference values."
            )
        if self.rank is not None and self.rank < 1:
            raise RankingContractViolation("Ranking adapter rank must be positive.")


@dataclass(frozen=True, slots=True)
class RankingExecutionResult:
    alternatives: tuple[RankingAlternativeResult, ...]
    metric_label: str
    diagnostics_json: JsonObject = field(default_factory=dict)
    trace_json: JsonObject = field(default_factory=dict)
    algorithm_metadata_json: JsonObject = field(default_factory=dict)


class RankingAlgorithmRunner(Protocol):
    metadata: RankingRunnerMetadata

    def execute(self, request: RankingRequest) -> RankingExecutionResult: ...


class RankingRunnerRegistry(Protocol):
    def get(self, implementation_id: str) -> RankingAlgorithmRunner: ...
