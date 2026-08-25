from decimal import Decimal
from types import ModuleType

import numpy as np
import pytest

from poli_insight.application.ports.validator import (
    PreparedComparisonMatrix,
    ValidatorExecutionError,
)
from poli_insight.domain.validation import ValidationPreparedMatrix
from poli_insight.infrastructure.weighting.pydecision_ahp import PyDecisionAhpRunner


def _matrix() -> PreparedComparisonMatrix:
    return PreparedComparisonMatrix(
        ValidationPreparedMatrix.create(
            validation_id="validation-1",
            response_format="pairwise",
            value_shape="crisp",
            criterion_ids=("a", "b", "c"),
            matrix_json={
                "values": [
                    ["1", "2", "4"],
                    ["0.5", "1", "2"],
                    ["0.25", "0.5", "1"],
                ]
            },
            preparer_version="test-v1",
        ),
        (),
    )


def test_pydecision_ahp_returns_normalized_geometric_weights_and_ratio():
    result = PyDecisionAhpRunner().execute(
        _matrix(),
        {"weight_derivation": "geometric"},
    )

    assert sum(result.crisp_weights) == Decimal(1)
    assert [float(value) for value in result.crisp_weights] == pytest.approx(
        [4 / 7, 2 / 7, 1 / 7]
    )
    assert float(result.consistency_ratio or 0) == pytest.approx(0, abs=1e-12)


def test_pydecision_adapter_pins_geometric_provider_mode(monkeypatch):
    calls = []
    algorithm = ModuleType("pyDecision.algorithm")

    def fake_ahp(dataset, *, wd):
        calls.append((dataset, wd))
        return np.asarray([2, 1, 1]), 0.08

    algorithm.ahp_method = fake_ahp  # type: ignore[attr-defined]
    package = ModuleType("pyDecision")
    package.algorithm = algorithm  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "pyDecision", package)
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyDecision.algorithm",
        algorithm,
    )

    result = PyDecisionAhpRunner().execute(_matrix(), {})

    assert calls[0][1] == "geometric"
    assert result.crisp_weights == (
        Decimal("0.5"),
        Decimal("0.25"),
        Decimal("0.25"),
    )
    assert result.consistency_ratio == Decimal("0.08")


def test_pydecision_provider_failure_is_sanitized(monkeypatch):
    algorithm = ModuleType("pyDecision.algorithm")

    def fake_ahp(dataset, *, wd):
        raise RuntimeError("participant value and provider internals")

    algorithm.ahp_method = fake_ahp  # type: ignore[attr-defined]
    package = ModuleType("pyDecision")
    package.algorithm = algorithm  # type: ignore[attr-defined]
    monkeypatch.setitem(__import__("sys").modules, "pyDecision", package)
    monkeypatch.setitem(
        __import__("sys").modules,
        "pyDecision.algorithm",
        algorithm,
    )

    with pytest.raises(ValidatorExecutionError) as caught:
        PyDecisionAhpRunner().execute(_matrix(), {})

    assert caught.value.code == "provider.ahp_execution_failed"
    assert "participant value" not in caught.value.safe_detail
