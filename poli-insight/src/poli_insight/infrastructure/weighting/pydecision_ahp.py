"""PyDecision AHP adapter with provider-neutral inputs and outputs."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from poli_insight.application.ports.validator import (
    PreparedComparisonMatrix,
    ValidatorContractViolation,
    ValidatorExecutionError,
    ValidatorMetadata,
    WeightingExecutionResult,
)

PYDECISION_AHP_IMPLEMENTATION_ID = "10000000-0000-4000-8000-000000000001"
_STORAGE_QUANTUM = Decimal("1e-18")


def _stored_decimal(value: Decimal) -> Decimal:
    quantized = value.quantize(_STORAGE_QUANTUM)
    return Decimal(0) if quantized.is_zero() else quantized.normalize()


class PyDecisionAhpRunner:
    """Execute pyDecision's AHP implementation in fixed geometric mode."""

    metadata = ValidatorMetadata(
        validator_implementation_id=PYDECISION_AHP_IMPLEMENTATION_ID,
        validator_version="1.0.0",
        adapter_version="1.0.0",
        parameter_schema_version=1,
        capabilities_json={
            "matrix_shapes": ["crisp"],
            "response_formats": ["pairwise", "direct_rating"],
            "consistency_ratio": True,
            "weight_derivations": ["geometric"],
        },
    )

    def execute(
        self,
        prepared: PreparedComparisonMatrix,
        parameters: Mapping[str, Any],
    ) -> WeightingExecutionResult:
        if prepared.matrix.value_shape != "crisp":
            raise ValidatorContractViolation(
                "The AHP adapter requires a crisp comparison matrix."
            )
        configured_mode = parameters.get("weight_derivation", "geometric")
        if configured_mode != "geometric":
            raise ValidatorContractViolation(
                "The configured AHP weight derivation is unsupported."
            )
        try:
            import numpy as np
            from pyDecision.algorithm import ahp_method  # type: ignore[import-untyped]
        except ImportError as error:
            raise ValidatorExecutionError(
                code="provider.pydecision_unavailable",
                safe_detail="The configured weighting provider is unavailable.",
                retryable=True,
            ) from error

        dataset = np.asarray(
            [[float(value) for value in row] for row in prepared.values],
            dtype=float,
        )
        try:
            provider_weights, provider_ratio = ahp_method(
                dataset, wd="geometric"
            )
        except Exception as error:
            raise ValidatorExecutionError(
                code="provider.ahp_execution_failed",
                safe_detail="The configured AHP provider could not process the matrix.",
                retryable=False,
            ) from error

        weights = tuple(self._decimal(value, "weight") for value in provider_weights)
        if len(weights) != len(prepared.criterion_ids):
            raise ValidatorContractViolation(
                "The AHP provider returned an unexpected weight vector length."
            )
        if any(weight < 0 for weight in weights):
            raise ValidatorContractViolation(
                "The AHP provider returned a negative weight."
            )
        total = sum(weights, Decimal(0))
        if total <= 0:
            raise ValidatorContractViolation(
                "The AHP provider returned a nonpositive weight total."
            )
        normalized = tuple(_stored_decimal(weight / total) for weight in weights)
        # Decimal division can leave a final representational remainder. Make
        # the last value close the vector exactly without changing ordering.
        if normalized:
            normalized = (
                *normalized[:-1],
                _stored_decimal(
                    Decimal(1) - sum(normalized[:-1], Decimal(0))
                ),
            )
        ratio = (
            Decimal(0)
            if len(prepared.criterion_ids) < 3
            else self._decimal(provider_ratio, "consistency ratio")
        )
        ratio = _stored_decimal(ratio)
        if ratio < 0:
            raise ValidatorContractViolation(
                "The AHP provider returned a negative consistency ratio."
            )
        return WeightingExecutionResult(
            criterion_ids=prepared.criterion_ids,
            crisp_weights=normalized,
            consistency_ratio=ratio,
            diagnostics_json={
                "provider": "pydecision",
                "method": "ahp",
                "weight_derivation": "geometric",
                "consistency_ratio_available": True,
            },
        )

    @staticmethod
    def _decimal(value: object, label: str) -> Decimal:
        try:
            converted = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as error:
            raise ValidatorContractViolation(
                f"The AHP provider returned a nonnumeric {label}."
            ) from error
        if not converted.is_finite():
            raise ValidatorContractViolation(
                f"The AHP provider returned a nonfinite {label}."
            )
        return converted


class StaticWeightingRunnerRegistry:
    """Small deterministic registry for configured provider adapters."""

    def __init__(self, *runners) -> None:
        self._runners = {
            runner.metadata.validator_implementation_id: runner
            for runner in runners
        }

    def get(self, implementation_id: str):
        try:
            return self._runners[implementation_id]
        except KeyError as error:
            raise ValidatorContractViolation(
                "No weighting adapter is registered for this implementation."
            ) from error
