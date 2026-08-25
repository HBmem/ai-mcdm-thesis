"""PyDecision TOPSIS adapter behind the provider-neutral ranking port."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from poli_insight.application.ports.ranking import (
    RankingAlternativeResult,
    RankingContractViolation,
    RankingExecutionError,
    RankingExecutionResult,
    RankingRequest,
    RankingRunnerMetadata,
)
from poli_insight.domain.enum import CriterionDataType, CriterionDirection

PYDECISION_TOPSIS_IMPLEMENTATION_ID = "10000000-0000-4000-8000-000000000002"


class PyDecisionTopsisRunner:
    """Translate canonical numeric ranking input to pyDecision TOPSIS."""

    metadata = RankingRunnerMetadata(
        algorithm_implementation_id=PYDECISION_TOPSIS_IMPLEMENTATION_ID,
        implementation_version="1.0.0",
        adapter_version="1.0.0",
        parameter_schema_version=1,
        capabilities_json={
            "decision_value_shapes": ["crisp_numeric"],
            "weight_shapes": ["crisp"],
            "preference_orientation": "higher_is_better",
        },
    )

    def execute(self, request: RankingRequest) -> RankingExecutionResult:
        if request.parameters:
            raise RankingContractViolation(
                "The configured TOPSIS adapter does not accept parameters."
            )
        if any(
            criterion.data_type != CriterionDataType.NUMERIC
            for criterion in request.criteria
        ):
            raise RankingContractViolation(
                "The configured TOPSIS adapter requires numeric criteria."
            )
        cells = {
            (item.alternative_id, item.criterion_id): item for item in request.cells
        }
        matrix: list[list[float]] = []
        for alternative in request.alternatives:
            row: list[float] = []
            for criterion in request.criteria:
                value = cells[(alternative.alternative_id, criterion.criterion_id)]
                if value.numeric_value is None or not value.numeric_value.is_finite():
                    raise RankingContractViolation(
                        "The configured TOPSIS adapter requires finite numeric values."
                    )
                row.append(float(value.numeric_value))
            matrix.append(row)

        weights: list[float] = []
        for item in request.weights:
            if not isinstance(item.value, Decimal) or not item.value.is_finite():
                raise RankingContractViolation(
                    "The configured TOPSIS adapter requires crisp finite weights."
                )
            if item.value < 0:
                raise RankingContractViolation("Ranking weights cannot be negative.")
            weights.append(float(item.value))
        if sum(weights) <= 0:
            raise RankingContractViolation(
                "Ranking weights must have a positive total."
            )
        for column_index in range(len(request.criteria)):
            if sum(row[column_index] ** 2 for row in matrix) <= 0:
                raise RankingContractViolation(
                    "TOPSIS cannot normalize an all-zero criterion column."
                )

        try:
            import numpy as np
            from pyDecision.algorithm import (  # type: ignore[import-untyped]
                topsis_method,
            )
        except ImportError as error:
            raise RankingExecutionError(
                code="provider.pydecision_unavailable",
                safe_detail="The configured ranking provider is unavailable.",
                retryable=True,
            ) from error
        directions = [
            "min" if item.direction == CriterionDirection.COST else "max"
            for item in request.criteria
        ]
        try:
            provider_scores = topsis_method(
                np.asarray(matrix, dtype=float),
                weights,
                directions,
                graph=False,
                verbose=False,
            )
        except Exception as error:
            raise RankingExecutionError(
                code="provider.topsis_execution_failed",
                safe_detail="The configured ranking provider could not rank the alternatives.",
                retryable=False,
            ) from error
        if len(provider_scores) != len(request.alternatives):
            raise RankingContractViolation(
                "The ranking provider returned an unexpected result length."
            )
        results: list[RankingAlternativeResult] = []
        for alternative, raw_score in zip(
            request.alternatives, provider_scores, strict=True
        ):
            try:
                score = Decimal(str(raw_score))
            except (InvalidOperation, TypeError, ValueError) as error:
                raise RankingContractViolation(
                    "The ranking provider returned a nonnumeric preference value."
                ) from error
            if not score.is_finite() or score < 0 or score > 1:
                raise RankingContractViolation(
                    "The ranking provider returned an invalid preference value."
                )
            results.append(
                RankingAlternativeResult(
                    alternative_id=alternative.alternative_id,
                    preference_value=score,
                    method_metrics={"closeness_coefficient": score},
                )
            )
        return RankingExecutionResult(
            alternatives=tuple(results),
            metric_label="Closeness coefficient",
            diagnostics_json={
                "alternative_count": len(request.alternatives),
                "criterion_count": len(request.criteria),
                "criterion_directions": directions,
            },
            trace_json={
                "normalization": "vector",
                "positive_ideal": "directional_best",
                "negative_ideal": "directional_worst",
            },
            algorithm_metadata_json={
                "provider": "pydecision",
                "method": "topsis",
                "adapter_version": self.metadata.adapter_version,
            },
        )


class StaticRankingRunnerRegistry:
    """Resolve adapters by persisted implementation identity."""

    def __init__(self, *runners) -> None:
        self._runners = {
            runner.metadata.algorithm_implementation_id: runner for runner in runners
        }

    def get(self, implementation_id: str):
        try:
            return self._runners[implementation_id]
        except KeyError as error:
            raise RankingContractViolation(
                "No ranking adapter is registered for this implementation."
            ) from error
