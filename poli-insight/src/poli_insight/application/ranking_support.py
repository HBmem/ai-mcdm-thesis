"""Reusable construction and ordering helpers for ranking executions."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from poli_insight.application.ports.ranking import (
    RankingAlternativeInput,
    RankingAlternativeResult,
    RankingContractViolation,
    RankingCriterionInput,
    RankingDecisionCell,
    RankingRequest,
    RankingWeightInput,
)
from poli_insight.domain.processing import ProcessingMatrix
from poli_insight.domain.ranking import RankedAlternative

_STORAGE_QUANTUM = Decimal("1e-18")


def ranking_request_for_matrix(
    matrix: ProcessingMatrix, scenario, parameters: Mapping[str, object]
) -> RankingRequest:
    criteria_by_id = {item.criterion_id: item for item in scenario.criteria}
    try:
        criteria = tuple(criteria_by_id[item] for item in matrix.criterion_ids)
    except KeyError as error:
        raise RankingContractViolation(
            "The weighting matrix references an unknown scenario criterion."
        ) from error
    alternatives = tuple(
        sorted(
            scenario.alternatives,
            key=lambda item: (item.display_order, item.alternative_id),
        )
    )
    values = {
        (item.alternative_id, item.criterion_id): item
        for item in scenario.matrix_values
    }
    cells: list[RankingDecisionCell] = []
    for alternative in alternatives:
        for criterion in criteria:
            value = values.get((alternative.alternative_id, criterion.criterion_id))
            if value is None:
                raise RankingContractViolation(
                    "The scenario decision matrix is incomplete."
                )
            cells.append(
                RankingDecisionCell(
                    alternative_id=alternative.alternative_id,
                    criterion_id=criterion.criterion_id,
                    numeric_value=value.value_numeric,
                    structured_value=value.value_json,
                )
            )
    return RankingRequest(
        source_processing_matrix_id=matrix.processing_matrix_id,
        alternatives=tuple(
            RankingAlternativeInput(
                item.alternative_id,
                item.alternative_key,
                item.name,
                item.display_order,
            )
            for item in alternatives
        ),
        criteria=tuple(
            RankingCriterionInput(
                item.criterion_id,
                item.criterion_key,
                item.name,
                item.direction,
                item.data_type,
                item.display_order,
            )
            for item in criteria
        ),
        cells=tuple(cells),
        weights=weight_inputs(matrix),
        parameters=dict(parameters),
    )


def weight_inputs(matrix: ProcessingMatrix) -> tuple[RankingWeightInput, ...]:
    raw_values = matrix.weights_json.get("values")
    if not isinstance(raw_values, (list, tuple)):
        raise RankingContractViolation("The persisted weighting vector is malformed.")
    by_id: dict[str, RankingWeightInput] = {}
    for value in raw_values:
        if not isinstance(value, Mapping) or "criterion_id" not in value:
            raise RankingContractViolation(
                "The persisted weighting vector is malformed."
            )
        criterion_id = str(value["criterion_id"])
        if "weight" in value:
            try:
                weight = (
                    value["weight"]
                    if isinstance(value["weight"], Decimal)
                    else Decimal(str(value["weight"]))
                )
            except (InvalidOperation, TypeError, ValueError) as error:
                raise RankingContractViolation(
                    "The persisted weighting vector contains a nonnumeric weight."
                ) from error
            by_id[criterion_id] = RankingWeightInput(criterion_id, weight)
        else:
            by_id[criterion_id] = RankingWeightInput(
                criterion_id,
                {key: item for key, item in value.items() if key != "criterion_id"},
            )
    try:
        return tuple(by_id[item] for item in matrix.criterion_ids)
    except KeyError as error:
        raise RankingContractViolation(
            "The persisted weighting vector is incomplete."
        ) from error


def ranked_alternatives(
    values: tuple[RankingAlternativeResult, ...],
    alternatives: tuple[RankingAlternativeInput, ...],
) -> tuple[RankedAlternative, ...]:
    expected = {item.alternative_id for item in alternatives}
    if {item.alternative_id for item in values} != expected or len(values) != len(
        expected
    ):
        raise RankingContractViolation(
            "The ranking adapter did not return each requested alternative exactly once."
        )
    quantized = {
        item.alternative_id: stored_decimal(item.preference_value) for item in values
    }
    unique_scores = sorted(set(quantized.values()), reverse=True)
    rank_by_score = {score: index + 1 for index, score in enumerate(unique_scores)}
    result_by_id = {item.alternative_id: item for item in values}
    return tuple(
        RankedAlternative(
            alternative_id=item.alternative_id,
            rank=rank_by_score[quantized[item.alternative_id]],
            preference_value=quantized[item.alternative_id],
            method_metrics_json=dict(result_by_id[item.alternative_id].method_metrics),
        )
        for item in sorted(
            alternatives,
            key=lambda value: (
                rank_by_score[quantized[value.alternative_id]],
                value.display_order,
                value.alternative_id,
            ),
        )
    )


def stored_decimal(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise RankingContractViolation("Ranking preference values must be finite.")
    result = value.quantize(_STORAGE_QUANTUM)
    return Decimal(0) if result.is_zero() else result.normalize()
