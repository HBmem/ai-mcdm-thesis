"""Application port for replaceable submission-validation adapters.

The contract deliberately uses domain objects and stable application DTOs.
Implementations may call PyDecision or another provider internally, but
provider-specific matrices, exceptions, and numeric container types must not
cross this boundary.

Invalid participant input is a successful validator execution represented by
structured error messages in :class:`ValidationExecutionResult`. Operational
or provider failures are represented by :class:`ValidatorExecutionError`.
"""

from __future__ import annotations

import re
from collections.abc import Hashable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from poli_insight.domain.content_hash import canonical_json_bytes
from poli_insight.domain.enum import (
    ActorType,
    AlgorithmRole,
    MessageSeverity,
    ScenarioSnapshotStatus,
    ValidationStatus,
)
from poli_insight.domain.scenario import ScenarioSnapshot
from poli_insight.domain.session import (
    SessionAlgorithmConfig,
    SessionConfigurationVersion,
)
from poli_insight.domain.submission import Submission
from poli_insight.domain.validation import (
    ParticipantCriterionWeight,
    SubmissionValidation,
    ValidationMessage,
    ValidationNormalizedAnswer,
    ValidationPreparedMatrix,
)

JsonObject = Mapping[str, Any]
_STABLE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]*")


class ValidatorContractViolation(ValueError):
    """Raised when a validator request, result, or descriptor is inconsistent."""


class ValidatorExecutionError(RuntimeError):
    """A sanitized operational failure raised by a validator adapter.

    ``safe_detail`` may be persisted in validation failure evidence. Adapter
    implementations must therefore avoid secrets, participant-authored raw
    values, stack traces, and unreviewed provider exception text.
    """

    def __init__(
        self,
        *,
        code: str,
        safe_detail: str,
        retryable: bool = False,
    ) -> None:
        _require_stable_code(code, "Validator execution error code")
        _require_text(safe_detail, "Validator execution error detail")
        if not isinstance(retryable, bool):
            raise ValidatorContractViolation(
                "Validator execution error retryable must be a boolean."
            )
        self.code = code
        self.safe_detail = safe_detail
        self.retryable = retryable
        super().__init__(f"{code}: {safe_detail}")


@dataclass(frozen=True, slots=True)
class ValidatorMetadata:
    """Stable identity and compatibility metadata for one adapter."""

    validator_implementation_id: str
    validator_version: str
    adapter_version: str
    parameter_schema_version: int
    capabilities_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(
            self.validator_implementation_id,
            "Validator implementation ID",
        )
        _require_text(self.validator_version, "Validator version")
        _require_text(self.adapter_version, "Validator adapter version")
        _require_positive_integer(
            self.parameter_schema_version,
            "Validator parameter schema version",
        )
        _validate_json(
            self.capabilities_json,
            "Validator capabilities",
        )


@dataclass(frozen=True, slots=True)
class ValidationRequest:
    """Complete immutable input required by a validation adapter.

    The running validation carries the frozen hashes and parameters that will
    be persisted. The remaining aggregates provide the actual authored input,
    question contract, scales, and criterion identities needed to validate it.
    """

    validation: SubmissionValidation
    submission: Submission
    configuration: SessionConfigurationVersion
    scenario_snapshot: ScenarioSnapshot
    algorithm_config: SessionAlgorithmConfig

    def __post_init__(self) -> None:
        self._validate_validation_state()
        self._validate_submission_binding()
        self._validate_scenario_binding()
        self._validate_algorithm_binding()

    @property
    def validation_id(self) -> str:
        return self.validation.validation_id

    @property
    def parameter_json(self) -> JsonObject:
        return self.validation.parameter_json

    def ensure_compatible(self, metadata: ValidatorMetadata) -> None:
        """Verify that a selected adapter exactly matches the frozen request."""

        if (
            metadata.validator_implementation_id
            != self.validation.validator_implementation_id
        ):
            raise ValidatorContractViolation(
                "Selected validator implementation does not match the frozen "
                "validation input."
            )
        if metadata.validator_version != self.validation.validator_version:
            raise ValidatorContractViolation(
                "Selected validator version does not match the frozen "
                "validation input."
            )
        if (
            metadata.parameter_schema_version
            != self.algorithm_config.parameter_schema_version
        ):
            raise ValidatorContractViolation(
                "Validator parameter schema version is incompatible with the "
                "session algorithm configuration."
            )

    def _validate_validation_state(self) -> None:
        self.validation.validate_integrity()
        if self.validation.status != ValidationStatus.RUNNING:
            raise ValidatorContractViolation(
                "A validator request requires a running validation attempt."
            )

    def _validate_submission_binding(self) -> None:
        self.submission.validate_against_configuration(self.configuration)
        if not self.submission.is_finalized:
            raise ValidatorContractViolation(
                "A validator request requires a finalized submission."
            )
        if self.submission.submission_id != self.validation.submission_id:
            raise ValidatorContractViolation(
                "Validation and submission identities do not match."
            )
        if self.submission.answers_hash != self.validation.answers_hash:
            raise ValidatorContractViolation(
                "Submission content does not match the frozen answers hash."
            )
        if (
            self.configuration.config_hash
            != self.validation.configuration_hash
        ):
            raise ValidatorContractViolation(
                "Configuration content does not match the frozen configuration "
                "hash."
            )
        if not self.configuration.is_activated:
            raise ValidatorContractViolation(
                "Validation requires an activated session configuration."
            )

    def _validate_scenario_binding(self) -> None:
        expected_snapshot_id = self.configuration.scenario_snapshot_id
        if self.submission.scenario_snapshot_id != expected_snapshot_id:
            raise ValidatorContractViolation(
                "Submission and configuration reference different scenario "
                "snapshots."
            )
        if self.scenario_snapshot.scenario_snapshot_id != expected_snapshot_id:
            raise ValidatorContractViolation(
                "Loaded scenario snapshot does not match the validation input."
            )
        if self.scenario_snapshot.status != ScenarioSnapshotStatus.READY:
            raise ValidatorContractViolation(
                "Validation requires a ready scenario snapshot."
            )
        if self.configuration.scale_id not in {
            scale.scale_id for scale in self.scenario_snapshot.scales
        }:
            raise ValidatorContractViolation(
                "Validation configuration references an unknown scenario "
                "scale."
            )

    def _validate_algorithm_binding(self) -> None:
        self.algorithm_config.validate_integrity()
        if self.algorithm_config.role != AlgorithmRole.WEIGHTING:
            raise ValidatorContractViolation(
                "Validation requires the configured weighting algorithm."
            )
        if (
            self.algorithm_config.configuration_version_id
            != self.configuration.configuration_version_id
        ):
            raise ValidatorContractViolation(
                "Validation algorithm belongs to a different session "
                "configuration."
            )
        if (
            self.algorithm_config.algorithm_implementation_id
            != self.validation.validator_implementation_id
        ):
            raise ValidatorContractViolation(
                "Validation algorithm implementation does not match the frozen "
                "validation input."
            )
        if self.algorithm_config.parameter_hash != self.validation.parameter_hash:
            raise ValidatorContractViolation(
                "Validation algorithm parameters do not match the frozen "
                "validation input."
            )


@dataclass(frozen=True, slots=True)
class ValidationExecutionResult:
    """Provider-neutral successful execution output from a validator.

    A result may describe valid, warning-level, or invalid participant input.
    It must not be used for operational failures; adapters raise
    :class:`ValidatorExecutionError` for those failures instead.
    """

    validation_id: str
    completion_ratio: Decimal
    messages: tuple[ValidationMessage, ...] = field(default_factory=tuple)
    normalized_answers: tuple[ValidationNormalizedAnswer, ...] = field(
        default_factory=tuple
    )
    prepared_matrix: ValidationPreparedMatrix | None = None
    criterion_weights: tuple[ParticipantCriterionWeight, ...] = field(
        default_factory=tuple
    )
    quality_metrics_json: JsonObject = field(default_factory=dict)
    consistency_ratio: Decimal | None = None

    def __post_init__(self) -> None:
        _require_text(self.validation_id, "Validation result ID")
        _require_ratio(
            self.completion_ratio,
            "Validation result completion ratio",
        )
        if self.consistency_ratio is not None:
            _require_nonnegative_decimal(
                self.consistency_ratio,
                "Validation result consistency ratio",
            )
        _validate_json(
            self.quality_metrics_json,
            "Validation result quality metrics",
        )
        self._validate_children()

    @property
    def status(self) -> ValidationStatus:
        """Derive the domain status from the highest message severity."""

        severities = {message.severity for message in self.messages}
        if MessageSeverity.ERROR in severities:
            return ValidationStatus.INVALID
        if MessageSeverity.WARNING in severities:
            return ValidationStatus.VALID_WITH_WARNING
        return ValidationStatus.VALID

    def apply_to(
        self,
        validation: SubmissionValidation,
        *,
        actor_type: ActorType,
        actor_id: str,
        at: datetime,
    ) -> SubmissionValidation:
        """Complete the matching running domain attempt with this result."""

        if validation.validation_id != self.validation_id:
            raise ValidatorContractViolation(
                "Validation result belongs to a different validation attempt."
            )
        return validation.complete(
            completion_ratio=self.completion_ratio,
            messages=self.messages,
            normalized_answers=self.normalized_answers,
            prepared_matrix=self.prepared_matrix,
            criterion_weights=self.criterion_weights,
            quality_metrics_json=self.quality_metrics_json,
            consistency_ratio=self.consistency_ratio,
            actor_type=actor_type,
            actor_id=actor_id,
            at=at,
            status=self.status,
        )

    def _validate_children(self) -> None:
        for message in self.messages:
            if message.validation_id != self.validation_id:
                raise ValidatorContractViolation(
                    "Validator output belongs to a different validation."
                )
        for answer in self.normalized_answers:
            if answer.validation_id != self.validation_id:
                raise ValidatorContractViolation(
                    "Validator output belongs to a different validation."
                )
        for weight in self.criterion_weights:
            if weight.validation_id != self.validation_id:
                raise ValidatorContractViolation(
                    "Validator output belongs to a different validation."
                )
        if (
            self.prepared_matrix is not None
            and self.prepared_matrix.validation_id != self.validation_id
        ):
            raise ValidatorContractViolation(
                "Prepared matrix belongs to a different validation."
            )
        _require_unique(
            (message.validation_message_id for message in self.messages),
            "Validation result message IDs",
        )
        _require_unique(
            (message.display_order for message in self.messages),
            "Validation result message display orders",
        )
        _require_unique(
            (
                answer.submission_answer_id
                for answer in self.normalized_answers
            ),
            "Validation result normalized-answer IDs",
        )
        _require_unique(
            (weight.criterion_id for weight in self.criterion_weights),
            "Validation result criterion IDs",
        )


@dataclass(frozen=True, slots=True)
class PreparedComparisonMatrix:
    """Algorithm-independent prepared input and its answer evidence."""

    matrix: ValidationPreparedMatrix
    normalized_answers: tuple[ValidationNormalizedAnswer, ...]

    @property
    def criterion_ids(self) -> tuple[str, ...]:
        return self.matrix.criterion_ids

    @property
    def values(self) -> tuple[tuple[Decimal, ...], ...]:
        raw_values = self.matrix.matrix_json.get("values")
        if not isinstance(raw_values, (list, tuple)):
            raise ValidatorContractViolation("Prepared matrix values are missing.")
        try:
            return tuple(
                tuple(
                    item if isinstance(item, Decimal) else Decimal(str(item))
                    for item in row
                )
                for row in raw_values
            )
        except (TypeError, ValueError, ArithmeticError) as error:
            raise ValidatorContractViolation(
                "Prepared matrix contains non-decimal crisp values."
            ) from error


@dataclass(frozen=True, slots=True)
class WeightingExecutionResult:
    """Provider-neutral output from a configured weighting algorithm."""

    criterion_ids: tuple[str, ...]
    crisp_weights: tuple[Decimal, ...] = field(default_factory=tuple)
    fuzzy_weights: tuple[tuple[Decimal, Decimal, Decimal], ...] = field(
        default_factory=tuple
    )
    diagnostics_json: JsonObject = field(default_factory=dict)
    consistency_ratio: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.criterion_ids:
            raise ValidatorContractViolation(
                "Weighting output requires criterion identities."
            )
        if bool(self.crisp_weights) == bool(self.fuzzy_weights):
            raise ValidatorContractViolation(
                "Weighting output must contain exactly one numeric weight shape."
            )
        weights_length = (
            len(self.crisp_weights)
            if self.crisp_weights
            else len(self.fuzzy_weights)
        )
        if len(self.criterion_ids) != weights_length:
            raise ValidatorContractViolation(
                "Weighting output must contain one weight per criterion."
            )
        _require_unique(self.criterion_ids, "Weighting output criterion IDs")
        if self.crisp_weights:
            for weight in self.crisp_weights:
                _require_nonnegative_decimal(weight, "Weighting output weight")
            total = sum(self.crisp_weights, Decimal(0))
            if abs(total - Decimal(1)) > Decimal("1e-9"):
                raise ValidatorContractViolation(
                    "Crisp weighting output must be normalized to one."
                )
        else:
            for lower, middle, upper in self.fuzzy_weights:
                for weight in (lower, middle, upper):
                    _require_nonnegative_decimal(
                        weight,
                        "Fuzzy weighting output value",
                    )
                if not lower <= middle <= upper:
                    raise ValidatorContractViolation(
                        "Fuzzy weights must satisfy lower <= middle <= upper."
                    )
            middle_total = sum(
                (weight[1] for weight in self.fuzzy_weights),
                Decimal(0),
            )
            if abs(middle_total - Decimal(1)) > Decimal("1e-9"):
                raise ValidatorContractViolation(
                    "Fuzzy middle weights must be normalized to one."
                )
        if self.consistency_ratio is not None:
            _require_nonnegative_decimal(
                self.consistency_ratio, "Weighting consistency ratio"
            )
        _validate_json(self.diagnostics_json, "Weighting diagnostics")


class SubmissionInputPreparer(Protocol):
    """Prepare valid authored answers without executing weighting math."""

    @property
    def version(self) -> str: ...

    def prepare(self, request: ValidationRequest) -> PreparedComparisonMatrix: ...


class WeightingAlgorithmRunner(Protocol):
    """Execute one provider-specific weighting implementation."""

    @property
    def metadata(self) -> ValidatorMetadata: ...

    def execute(
        self,
        prepared: PreparedComparisonMatrix,
        parameters: JsonObject,
    ) -> WeightingExecutionResult: ...


class WeightingRunnerRegistry(Protocol):
    """Resolve runners using immutable algorithm implementation identity."""

    def get(self, implementation_id: str) -> WeightingAlgorithmRunner: ...


class Validator(Protocol):
    """Structural interface implemented by every validation adapter."""

    @property
    def metadata(self) -> ValidatorMetadata:
        """Return exact implementation and parameter compatibility metadata."""
        ...

    def validate(
        self,
        request: ValidationRequest,
    ) -> ValidationExecutionResult:
        """Validate one immutable request without persistence side effects.

        Implementations must be deterministic for the same request unless a
        configured parameter explicitly introduces randomness. They must not
        mutate domain inputs, access repositories, commit transactions, or
        return provider-specific objects. Expected participant-data problems
        belong in structured result messages. Operational failures must be
        translated to :class:`ValidatorExecutionError`. Implementations should
        begin by calling ``request.ensure_compatible(self.metadata)``.
        """
        ...


class ValidatorRegistry(Protocol):
    """Resolve a complete validation pipeline for a weighting implementation."""

    def for_implementation(self, implementation_id: str) -> Validator: ...


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidatorContractViolation(f"{field_name} cannot be empty.")
    if value != value.strip():
        raise ValidatorContractViolation(
            f"{field_name} cannot contain leading or trailing whitespace."
        )


def _require_stable_code(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if _STABLE_CODE_PATTERN.fullmatch(value) is None:
        raise ValidatorContractViolation(
            f"{field_name} must be a lowercase stable code."
        )


def _require_positive_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidatorContractViolation(
            f"{field_name} must be a positive integer."
        )


def _require_ratio(value: Decimal, field_name: str) -> None:
    _require_decimal(value, field_name)
    if not Decimal(0) <= value <= Decimal(1):
        raise ValidatorContractViolation(
            f"{field_name} must be between zero and one."
        )


def _require_nonnegative_decimal(value: Decimal, field_name: str) -> None:
    _require_decimal(value, field_name)
    if value < 0:
        raise ValidatorContractViolation(
            f"{field_name} must be greater than or equal to zero."
        )


def _require_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise ValidatorContractViolation(f"{field_name} must be a Decimal.")
    if not value.is_finite():
        raise ValidatorContractViolation(f"{field_name} must be finite.")


def _validate_json(value: object, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValidatorContractViolation(f"{field_name} must be a JSON object.")
    try:
        canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise ValidatorContractViolation(
            f"{field_name} must be canonicalizable JSON: {error}"
        ) from error


def _require_unique(
    values: Iterable[Hashable],
    field_name: str,
) -> None:
    seen: set[Hashable] = set()
    for value in values:
        if value in seen:
            raise ValidatorContractViolation(f"{field_name} must be unique.")
        seen.add(value)
