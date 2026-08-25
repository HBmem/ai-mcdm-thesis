"""Composition of preparation and provider-specific weighting execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

from poli_insight.application.ports.validator import (
    ValidationExecutionResult,
    ValidationRequest,
    ValidatorMetadata,
    WeightingAlgorithmRunner,
)
from poli_insight.application.validation.preparation import InputPreparationError
from poli_insight.core.ids import new_id
from poli_insight.domain.enum import MessageSeverity
from poli_insight.domain.validation import (
    ParticipantCriterionWeight,
    ValidationMessage,
)


class SubmissionValidationService:
    """Algorithm-independent validation pipeline around a weighting runner."""

    def __init__(
        self,
        preparer,
        runner: WeightingAlgorithmRunner,
        *,
        id_factory: Callable[[], str] = lambda: str(new_id()),
    ) -> None:
        self._preparer = preparer
        self._runner = runner
        self._id_factory = id_factory

    @property
    def metadata(self) -> ValidatorMetadata:
        return replace(
            self._runner.metadata,
            validator_version=(
                f"{self._runner.metadata.validator_version}+"
                f"adapter.{self._runner.metadata.adapter_version}+"
                f"{self._preparer.version}+matrix.1"
            ),
        )

    def validate(self, request: ValidationRequest) -> ValidationExecutionResult:
        request.ensure_compatible(self.metadata)
        try:
            prepared = self._preparer.prepare(request)
        except InputPreparationError as error:
            return ValidationExecutionResult(
                validation_id=request.validation_id,
                completion_ratio=error.completion_ratio,
                messages=tuple(
                    ValidationMessage(
                        validation_message_id=self._id_factory(),
                        validation_id=request.validation_id,
                        severity=MessageSeverity.ERROR,
                        code=finding.code,
                        safe_message=finding.safe_message,
                        question_definition_id=finding.question_definition_id,
                        display_order=index,
                    )
                    for index, finding in enumerate(error.findings)
                ),
                quality_metrics_json={
                    "prepared_matrix_required": True,
                    "structurally_complete": False,
                },
            )

        result = self._runner.execute(prepared, request.parameter_json)
        messages: list[ValidationMessage] = []
        threshold = request.configuration.consistency_threshold
        if (
            threshold is not None
            and result.consistency_ratio is not None
            and result.consistency_ratio > threshold
        ):
            messages.append(
                ValidationMessage(
                    validation_message_id=self._id_factory(),
                    validation_id=request.validation_id,
                    severity=MessageSeverity.WARNING,
                    code="consistency.threshold_exceeded",
                    safe_message=(
                        "The AHP consistency ratio exceeds the configured threshold."
                    ),
                    display_order=0,
                    parameters_json={
                        "ratio": result.consistency_ratio,
                        "threshold": threshold,
                    },
                )
            )
        weights = self._criterion_weights(request, result)
        return ValidationExecutionResult(
            validation_id=request.validation_id,
            completion_ratio=Decimal(1),
            messages=tuple(messages),
            normalized_answers=prepared.normalized_answers,
            prepared_matrix=prepared.matrix,
            criterion_weights=weights,
            consistency_ratio=result.consistency_ratio,
            quality_metrics_json={
                "prepared_matrix_required": True,
                "structurally_complete": True,
                "criterion_count": len(result.criterion_ids),
                "preparer_version": prepared.matrix.preparer_version,
                "algorithm_version": self._runner.metadata.validator_version,
                "adapter_version": self._runner.metadata.adapter_version,
                "diagnostics": dict(result.diagnostics_json),
                "consistency_ratio": result.consistency_ratio,
            },
        )

    @staticmethod
    def _criterion_weights(request, result):
        common_metadata = {
            "algorithm_implementation_id": (
                request.algorithm_config.algorithm_implementation_id
            ),
        }
        if result.crisp_weights:
            return tuple(
                ParticipantCriterionWeight(
                    validation_id=request.validation_id,
                    criterion_id=criterion_id,
                    crisp_weight=weight,
                    derivation_metadata_json={
                        **common_metadata,
                        "normalized_weight": weight,
                    },
                )
                for criterion_id, weight in zip(
                    result.criterion_ids,
                    result.crisp_weights,
                    strict=True,
                )
            )
        return tuple(
            ParticipantCriterionWeight(
                validation_id=request.validation_id,
                criterion_id=criterion_id,
                fuzzy_lower=weight[0],
                fuzzy_middle=weight[1],
                fuzzy_upper=weight[2],
                derivation_metadata_json={
                    **common_metadata,
                    "normalized_fuzzy_weight": list(weight),
                },
            )
            for criterion_id, weight in zip(
                result.criterion_ids,
                result.fuzzy_weights,
                strict=True,
            )
        )


class SubmissionValidationRegistry:
    """Build validation pipelines from replaceable weighting runners."""

    def __init__(self, preparer, runner_registry, *, id_factory=None) -> None:
        self._preparer = preparer
        self._runner_registry = runner_registry
        self._id_factory = id_factory

    def for_implementation(self, implementation_id: str):
        options = {}
        if self._id_factory is not None:
            options["id_factory"] = self._id_factory
        return SubmissionValidationService(
            self._preparer,
            self._runner_registry.get(implementation_id),
            **options,
        )
