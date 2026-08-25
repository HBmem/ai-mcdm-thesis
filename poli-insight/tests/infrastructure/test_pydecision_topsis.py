from __future__ import annotations

from decimal import Decimal
from types import ModuleType

import numpy as np
import pytest

from poli_insight.application.ports.ranking import (
    RankingAlternativeInput,
    RankingContractViolation,
    RankingCriterionInput,
    RankingDecisionCell,
    RankingExecutionError,
    RankingRequest,
    RankingRunnerMetadata,
    RankingWeightInput,
)
from poli_insight.domain.enum import CriterionDataType, CriterionDirection
from poli_insight.infrastructure.ranking.pydecision_topsis import (
    PyDecisionTopsisRunner,
    StaticRankingRunnerRegistry,
)


def _request() -> RankingRequest:
    alternatives = (
        RankingAlternativeInput("a", "a", "A", 0),
        RankingAlternativeInput("b", "b", "B", 1),
    )
    criteria = (
        RankingCriterionInput(
            "cost",
            "cost",
            "Cost",
            CriterionDirection.COST,
            CriterionDataType.NUMERIC,
            0,
        ),
        RankingCriterionInput(
            "benefit",
            "benefit",
            "Benefit",
            CriterionDirection.BENEFIT,
            CriterionDataType.NUMERIC,
            1,
        ),
    )
    return RankingRequest(
        source_processing_matrix_id="matrix-1",
        alternatives=alternatives,
        criteria=criteria,
        cells=(
            RankingDecisionCell("a", "cost", Decimal(2)),
            RankingDecisionCell("a", "benefit", Decimal(8)),
            RankingDecisionCell("b", "cost", Decimal(5)),
            RankingDecisionCell("b", "benefit", Decimal(3)),
        ),
        weights=(
            RankingWeightInput("cost", Decimal("0.4")),
            RankingWeightInput("benefit", Decimal("0.6")),
        ),
    )


def _provider(monkeypatch, function) -> None:
    algorithm = ModuleType("pyDecision.algorithm")
    algorithm.topsis_method = function  # type: ignore[attr-defined]
    package = ModuleType("pyDecision")
    package.algorithm = algorithm  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "pyDecision", package)
    monkeypatch.setitem(__import__("sys").modules, "pyDecision.algorithm", algorithm)


def test_topsis_adapter_maps_directions_and_disables_provider_output(monkeypatch):
    calls = []

    def fake_topsis(dataset, weights, directions, *, graph, verbose):
        calls.append((dataset, weights, directions, graph, verbose))
        return np.asarray([0.8, 0.2])

    _provider(monkeypatch, fake_topsis)
    result = PyDecisionTopsisRunner().execute(_request())

    assert calls[0][2:] == (["min", "max"], False, False)
    assert calls[0][0].tolist() == [[2.0, 8.0], [5.0, 3.0]]
    assert tuple(item.preference_value for item in result.alternatives) == (
        Decimal("0.8"),
        Decimal("0.2"),
    )
    assert result.metric_label == "Closeness coefficient"


def test_topsis_adapter_rejects_zero_norm_columns():
    request = _request()
    zero_cells = tuple(
        RankingDecisionCell(
            item.alternative_id,
            item.criterion_id,
            Decimal(0) if item.criterion_id == "cost" else item.numeric_value,
        )
        for item in request.cells
    )
    with pytest.raises(RankingContractViolation, match="all-zero"):
        PyDecisionTopsisRunner().execute(
            RankingRequest(
                request.source_processing_matrix_id,
                request.alternatives,
                request.criteria,
                zero_cells,
                request.weights,
            )
        )


def test_topsis_provider_failure_is_sanitized(monkeypatch):
    def failed(*args, **kwargs):
        raise RuntimeError("private provider internals")

    _provider(monkeypatch, failed)
    with pytest.raises(RankingExecutionError) as caught:
        PyDecisionTopsisRunner().execute(_request())

    assert caught.value.code == "provider.topsis_execution_failed"
    assert "private provider internals" not in caught.value.safe_detail


def test_registry_is_implementation_driven_and_rejects_unknown_adapter():
    runner = PyDecisionTopsisRunner()

    class FutureFuzzyRunner:
        metadata = RankingRunnerMetadata(
            algorithm_implementation_id="future.fuzzy-topsis",
            implementation_version="1.0.0",
            adapter_version="1.0.0",
            capabilities_json={"decision_value_shapes": ["triangular_fuzzy"]},
        )

        def execute(self, request):  # pragma: no cover - registry-only fixture
            raise NotImplementedError

    future = FutureFuzzyRunner()
    registry = StaticRankingRunnerRegistry(runner, future)

    assert registry.get(runner.metadata.algorithm_implementation_id) == runner
    assert registry.get("future.fuzzy-topsis") == future
    with pytest.raises(RankingContractViolation, match="No ranking adapter"):
        registry.get("unknown.ranking-method")
