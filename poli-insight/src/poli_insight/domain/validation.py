"""Versioned validation results for immutable participant submissions.

Validation is derivative evidence.  It never edits participant-authored
answers; instead, each attempt records the exact submission/configuration and
validator inputs, structured messages, normalized values, and any generated
criterion weights.  Instances are immutable and lifecycle methods return
replacement values so persistence and audit events can share one transaction.
"""

from __future__ import annotations

import re
from collections.abc import Hashable, Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Self

from poli_insight.domain.content_hash import canonical_json_bytes, hash_json
from poli_insight.domain.enum import (
    ActorType,
    MessageSeverity,
    ValidationStatus,
)
from poli_insight.domain.session import SessionConfigurationVersion
from poli_insight.domain.submission import Submission

JsonObject = Mapping[str, Any]
VALIDATION_INPUT_SCHEMA_VERSION = 1
VALIDATION_OUTPUT_SCHEMA_VERSION = 1
EXPECTED_WEIGHT_TOTAL = Decimal(1)
WEIGHT_TOTAL_TOLERANCE = Decimal("1e-9")

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_MESSAGE_CODE_PATTERN = re.compile(r"[a-z][a-z0-9_.-]*")
_TERMINAL_STATUSES = frozenset(
    {
        ValidationStatus.VALID,
        ValidationStatus.VALID_WITH_WARNING,
        ValidationStatus.INVALID,
        ValidationStatus.ERROR,
    }
)


class ValidationRuleViolation(ValueError):
    """Raised when an operation violates a validation business rule."""


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationRuleViolation(f"{field_name} cannot be empty.")
    if value != value.strip():
        raise ValidationRuleViolation(
            f"{field_name} cannot contain leading or trailing whitespace."
        )


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and (
        value.tzinfo is None or value.utcoffset() is None
    ):
        raise ValidationRuleViolation(
            f"{field_name} must include timezone information."
        )


def _require_sha256(value: str, field_name: str) -> None:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValidationRuleViolation(
            f"{field_name} must be a lowercase hexadecimal SHA-256 digest."
        )


def _require_nonnegative_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationRuleViolation(
            f"{field_name} must be a nonnegative integer."
        )


def _require_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal):
        raise ValidationRuleViolation(f"{field_name} must be a Decimal.")
    if not value.is_finite():
        raise ValidationRuleViolation(f"{field_name} must be finite.")


def _require_nonnegative_decimal(value: Decimal, field_name: str) -> None:
    _require_decimal(value, field_name)
    if value < 0:
        raise ValidationRuleViolation(
            f"{field_name} must be greater than or equal to zero."
        )


def _validate_json(value: object, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise ValidationRuleViolation(f"{field_name} must be a JSON object.")
    try:
        canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise ValidationRuleViolation(
            f"{field_name} must be canonicalizable JSON: {error}"
        ) from error


def _copy_json(value: JsonObject) -> dict[str, Any]:
    copied = deepcopy(dict(value))
    _validate_json(copied, "JSON value")
    return copied


@dataclass(frozen=True, slots=True)
class ValidationMessage:
    """One stable, safely displayable validation finding."""

    validation_message_id: str
    validation_id: str
    severity: MessageSeverity
    code: str
    safe_message: str
    display_order: int
    question_definition_id: str | None = None
    parameters_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.validation_message_id, "Validation message ID")
        _require_text(self.validation_id, "Message validation ID")
        _require_text(self.code, "Validation message code")
        if _MESSAGE_CODE_PATTERN.fullmatch(self.code) is None:
            raise ValidationRuleViolation(
                "Validation message code must be a lowercase stable code."
            )
        _require_text(self.safe_message, "Validation safe message")
        _require_optional_text(
            self.question_definition_id,
            "Message question definition ID",
        )
        _require_nonnegative_integer(
            self.display_order,
            "Validation message display order",
        )
        _validate_json(self.parameters_json, "Validation message parameters")

    def to_manifest(self) -> dict[str, object]:
        """Return the deterministic representation included in output hashes."""

        return {
            "validation_message_id": self.validation_message_id,
            "severity": self.severity.value,
            "code": self.code,
            "safe_message": self.safe_message,
            "display_order": self.display_order,
            "question_definition_id": self.question_definition_id,
            "parameters": dict(self.parameters_json),
        }


@dataclass(frozen=True, slots=True)
class ValidationNormalizedAnswer:
    """A validator-produced value derived from one authored answer.

    ``normalized_value_json`` is authoritative.  The optional crisp/fuzzy
    columns are query conveniences and must describe one numeric shape only.
    Categorical or ranking outputs may legitimately have no numeric columns.
    """

    validation_id: str
    submission_answer_id: str
    normalized_value_json: JsonObject
    normalizer_version: str
    crisp_value: Decimal | None = None
    fuzzy_lower: Decimal | None = None
    fuzzy_middle: Decimal | None = None
    fuzzy_upper: Decimal | None = None

    def __post_init__(self) -> None:
        _require_text(self.validation_id, "Normalized answer validation ID")
        _require_text(
            self.submission_answer_id,
            "Normalized answer submission answer ID",
        )
        _require_text(self.normalizer_version, "Normalizer version")
        _validate_json(
            self.normalized_value_json,
            "Normalized answer value",
        )
        self._validate_numeric_shape()

    @property
    def numeric_shape(self) -> str | None:
        if self.crisp_value is not None:
            return "crisp"
        if self.fuzzy_lower is not None:
            return "fuzzy"
        return None

    def _validate_numeric_shape(self) -> None:
        fuzzy_values = (
            self.fuzzy_lower,
            self.fuzzy_middle,
            self.fuzzy_upper,
        )
        populated_fuzzy = sum(value is not None for value in fuzzy_values)
        if self.crisp_value is not None and populated_fuzzy:
            raise ValidationRuleViolation(
                "A normalized answer cannot be both crisp and fuzzy."
            )
        if populated_fuzzy not in {0, 3}:
            raise ValidationRuleViolation(
                "A fuzzy normalized answer requires lower, middle, and upper "
                "values."
            )
        if self.crisp_value is not None:
            _require_decimal(self.crisp_value, "Normalized crisp value")
        if populated_fuzzy == 3:
            lower, middle, upper = fuzzy_values
            assert lower is not None
            assert middle is not None
            assert upper is not None
            for field_name, value in (
                ("Normalized fuzzy lower value", lower),
                ("Normalized fuzzy middle value", middle),
                ("Normalized fuzzy upper value", upper),
            ):
                _require_decimal(value, field_name)
            if not lower <= middle <= upper:
                raise ValidationRuleViolation(
                    "Normalized fuzzy values must satisfy lower <= middle <= "
                    "upper."
                )

    def to_manifest(self) -> dict[str, object]:
        return {
            "submission_answer_id": self.submission_answer_id,
            "normalized_value": dict(self.normalized_value_json),
            "normalizer_version": self.normalizer_version,
            "crisp_value": self.crisp_value,
            "fuzzy_lower": self.fuzzy_lower,
            "fuzzy_middle": self.fuzzy_middle,
            "fuzzy_upper": self.fuzzy_upper,
        }


@dataclass(frozen=True, slots=True)
class ValidationPreparedMatrix:
    """Provider-neutral matrix derived from one immutable submission."""

    validation_id: str
    response_format: str
    value_shape: str
    criterion_ids: tuple[str, ...]
    matrix_json: JsonObject
    preparer_version: str
    matrix_hash: str

    def __post_init__(self) -> None:
        _require_text(self.validation_id, "Prepared matrix validation ID")
        if self.response_format not in {"direct_rating", "pairwise"}:
            raise ValidationRuleViolation(
                "Prepared matrix response format must be direct_rating or pairwise."
            )
        if self.value_shape not in {"crisp", "triangular_fuzzy"}:
            raise ValidationRuleViolation(
                "Prepared matrix value shape must be crisp or triangular_fuzzy."
            )
        _require_text(self.preparer_version, "Prepared matrix preparer version")
        _require_sha256(self.matrix_hash, "Prepared matrix hash")
        if not self.criterion_ids:
            raise ValidationRuleViolation(
                "Prepared matrix requires at least one criterion."
            )
        _require_unique(self.criterion_ids, "Prepared matrix criterion IDs")
        for criterion_id in self.criterion_ids:
            _require_text(criterion_id, "Prepared matrix criterion ID")
        _validate_json(self.matrix_json, "Prepared matrix values")
        values = self.matrix_json.get("values")
        if not isinstance(values, (list, tuple)) or len(values) != len(
            self.criterion_ids
        ):
            raise ValidationRuleViolation(
                "Prepared matrix must contain one row per criterion."
            )
        if any(
            not isinstance(row, (list, tuple))
            or len(row) != len(self.criterion_ids)
            for row in values
        ):
            raise ValidationRuleViolation(
                "Prepared matrix must be square and match criterion order."
            )
        if self.matrix_hash != hash_json(self._unhashed_manifest()):
            raise ValidationRuleViolation(
                "Prepared matrix values do not match matrix_hash."
            )

    @classmethod
    def create(
        cls,
        *,
        validation_id: str,
        response_format: str,
        value_shape: str,
        criterion_ids: tuple[str, ...],
        matrix_json: JsonObject,
        preparer_version: str,
    ) -> Self:
        unhashed = {
            "response_format": response_format,
            "value_shape": value_shape,
            "criterion_ids": list(criterion_ids),
            "matrix": dict(matrix_json),
            "preparer_version": preparer_version,
        }
        return cls(
            validation_id=validation_id,
            response_format=response_format,
            value_shape=value_shape,
            criterion_ids=criterion_ids,
            matrix_json=_copy_json(matrix_json),
            preparer_version=preparer_version,
            matrix_hash=hash_json(unhashed),
        )

    def _unhashed_manifest(self) -> dict[str, object]:
        return {
            "response_format": self.response_format,
            "value_shape": self.value_shape,
            "criterion_ids": list(self.criterion_ids),
            "matrix": dict(self.matrix_json),
            "preparer_version": self.preparer_version,
        }

    def to_manifest(self) -> dict[str, object]:
        return {**self._unhashed_manifest(), "matrix_hash": self.matrix_hash}


@dataclass(frozen=True, slots=True)
class ParticipantCriterionWeight:
    """One normalized crisp or triangular-fuzzy criterion weight."""

    validation_id: str
    criterion_id: str
    crisp_weight: Decimal | None = None
    fuzzy_lower: Decimal | None = None
    fuzzy_middle: Decimal | None = None
    fuzzy_upper: Decimal | None = None
    derivation_metadata_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_text(self.validation_id, "Criterion weight validation ID")
        _require_text(self.criterion_id, "Criterion weight criterion ID")
        _validate_json(
            self.derivation_metadata_json,
            "Criterion weight derivation metadata",
        )
        self._validate_weight_shape()

    @property
    def weight_shape(self) -> str:
        return "crisp" if self.crisp_weight is not None else "fuzzy"

    def _validate_weight_shape(self) -> None:
        fuzzy_values = (
            self.fuzzy_lower,
            self.fuzzy_middle,
            self.fuzzy_upper,
        )
        populated_fuzzy = sum(value is not None for value in fuzzy_values)
        if self.crisp_weight is not None:
            if populated_fuzzy:
                raise ValidationRuleViolation(
                    "A criterion weight cannot be both crisp and fuzzy."
                )
            _require_nonnegative_decimal(
                self.crisp_weight,
                "Crisp criterion weight",
            )
            return
        if populated_fuzzy != 3:
            raise ValidationRuleViolation(
                "A criterion weight requires either one crisp value or all "
                "three fuzzy values."
            )
        lower, middle, upper = fuzzy_values
        assert lower is not None
        assert middle is not None
        assert upper is not None
        for field_name, value in (
            ("Fuzzy criterion lower weight", lower),
            ("Fuzzy criterion middle weight", middle),
            ("Fuzzy criterion upper weight", upper),
        ):
            _require_nonnegative_decimal(value, field_name)
        if not lower <= middle <= upper:
            raise ValidationRuleViolation(
                "Fuzzy criterion weights must satisfy lower <= middle <= "
                "upper."
            )

    def to_manifest(self) -> dict[str, object]:
        return {
            "criterion_id": self.criterion_id,
            "crisp_weight": self.crisp_weight,
            "fuzzy_lower": self.fuzzy_lower,
            "fuzzy_middle": self.fuzzy_middle,
            "fuzzy_upper": self.fuzzy_upper,
            "derivation_metadata": dict(self.derivation_metadata_json),
        }


@dataclass(frozen=True, slots=True)
class SubmissionValidation:
    """One immutable, reproducible validation attempt for one submission."""

    validation_id: str
    submission_id: str
    answers_hash: str
    configuration_hash: str
    validator_implementation_id: str
    validator_version: str
    parameter_json: JsonObject
    parameter_hash: str
    status: ValidationStatus
    input_hash: str
    attempt_number: int = 1

    completion_ratio: Decimal = Decimal(0)
    consistency_ratio: Decimal | None = None
    quality_metrics_json: JsonObject = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    validated_by_actor_type: ActorType | None = None
    validated_by_actor_id: str | None = None
    output_hash: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    messages: tuple[ValidationMessage, ...] = field(default_factory=tuple)
    normalized_answers: tuple[ValidationNormalizedAnswer, ...] = field(
        default_factory=tuple
    )
    prepared_matrix: ValidationPreparedMatrix | None = None
    criterion_weights: tuple[ParticipantCriterionWeight, ...] = field(
        default_factory=tuple
    )

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_input_integrity()
        self._validate_output_values()
        self._validate_children()
        self._validate_lifecycle_state()
        self.validate_integrity()

    @classmethod
    def create_pending(
        cls,
        *,
        validation_id: str,
        submission_id: str,
        answers_hash: str,
        configuration_hash: str,
        validator_implementation_id: str,
        validator_version: str,
        parameter_json: JsonObject,
        attempt_number: int = 1,
    ) -> Self:
        """Create a pending attempt and freeze its complete input identity."""

        parameters = _copy_json(parameter_json)
        parameter_hash = hash_json(parameters)
        input_hash = hash_json(
            _input_manifest(
                submission_id=submission_id,
                answers_hash=answers_hash,
                configuration_hash=configuration_hash,
                validator_implementation_id=validator_implementation_id,
                validator_version=validator_version,
                parameter_hash=parameter_hash,
            )
        )
        return cls(
            validation_id=validation_id,
            submission_id=submission_id,
            answers_hash=answers_hash,
            configuration_hash=configuration_hash,
            validator_implementation_id=validator_implementation_id,
            validator_version=validator_version,
            parameter_json=parameters,
            parameter_hash=parameter_hash,
            status=ValidationStatus.PENDING,
            input_hash=input_hash,
            attempt_number=attempt_number,
        )

    @classmethod
    def for_submission(
        cls,
        *,
        validation_id: str,
        submission: Submission,
        configuration: SessionConfigurationVersion,
        validator_implementation_id: str,
        validator_version: str,
        parameter_json: JsonObject,
        attempt_number: int = 1,
    ) -> Self:
        """Create a pending attempt bound to verified immutable inputs."""

        submission.validate_against_configuration(configuration)
        if not submission.is_finalized or submission.answers_hash is None:
            raise ValidationRuleViolation(
                "Validation requires a finalized submission with an answers "
                "hash."
            )
        return cls.create_pending(
            validation_id=validation_id,
            submission_id=submission.submission_id,
            answers_hash=submission.answers_hash,
            configuration_hash=configuration.config_hash,
            validator_implementation_id=validator_implementation_id,
            validator_version=validator_version,
            parameter_json=parameter_json,
            attempt_number=attempt_number,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL_STATUSES

    @property
    def is_usable_for_processing(self) -> bool:
        status_usable = self.status in {
            ValidationStatus.VALID,
            ValidationStatus.VALID_WITH_WARNING,
        }
        if not status_usable or self.completion_ratio != EXPECTED_WEIGHT_TOTAL:
            return False
        # Existing schema-v1 evidence predates persisted matrices. New
        # validation pipelines opt into the stricter contract explicitly.
        if not self.quality_metrics_json.get("prepared_matrix_required", False):
            return True
        if self.prepared_matrix is None or not self.criterion_weights:
            return False
        criterion_ids = set(self.prepared_matrix.criterion_ids)
        if {
            weight.criterion_id for weight in self.criterion_weights
        } != criterion_ids:
            return False
        crisp_weights = tuple(
            weight.crisp_weight for weight in self.criterion_weights
        )
        if all(weight is not None for weight in crisp_weights):
            return abs(
                sum(
                    (weight for weight in crisp_weights if weight is not None),
                    Decimal(0),
                )
                - EXPECTED_WEIGHT_TOTAL
            ) <= WEIGHT_TOTAL_TOLERANCE
        return all(
            weight.fuzzy_lower is not None
            and weight.fuzzy_middle is not None
            and weight.fuzzy_upper is not None
            for weight in self.criterion_weights
        )

    def start(self, *, at: datetime) -> Self:
        """Move a pending attempt to running without changing its inputs."""

        _require_aware_datetime(at, "Validation start time")
        if self.status != ValidationStatus.PENDING:
            raise ValidationRuleViolation(
                "Only a pending validation can be started."
            )
        return replace(
            self,
            status=ValidationStatus.RUNNING,
            started_at=at,
        )

    def complete(
        self,
        *,
        completion_ratio: Decimal,
        messages: tuple[ValidationMessage, ...] = (),
        normalized_answers: tuple[ValidationNormalizedAnswer, ...] = (),
        prepared_matrix: ValidationPreparedMatrix | None = None,
        criterion_weights: tuple[ParticipantCriterionWeight, ...] = (),
        quality_metrics_json: JsonObject | None = None,
        consistency_ratio: Decimal | None = None,
        actor_type: ActorType,
        actor_id: str,
        at: datetime,
        status: ValidationStatus | None = None,
    ) -> Self:
        """Finish a running validation with immutable structured outputs.

        When ``status`` is omitted it is derived from message severity: an
        error makes the result invalid, a warning yields
        ``valid_with_warnings``, and informational/no messages yield ``valid``.
        """

        self._require_running(actor_id=actor_id, at=at)
        ordered_messages = tuple(
            sorted(
                messages,
                key=lambda item: (
                    item.display_order,
                    item.validation_message_id,
                ),
            )
        )
        ordered_answers = tuple(
            sorted(
                normalized_answers,
                key=lambda item: item.submission_answer_id,
            )
        )
        ordered_weights = tuple(
            sorted(criterion_weights, key=lambda item: item.criterion_id)
        )
        resolved_status = status or _status_from_messages(ordered_messages)
        if resolved_status not in {
            ValidationStatus.VALID,
            ValidationStatus.VALID_WITH_WARNING,
            ValidationStatus.INVALID,
        }:
            raise ValidationRuleViolation(
                "A successful validation completion must be valid, valid with "
                "warnings, or invalid."
            )
        quality_metrics = _copy_json(quality_metrics_json or {})
        output_hash = hash_json(
            _output_manifest(
                status=resolved_status,
                completion_ratio=completion_ratio,
                consistency_ratio=consistency_ratio,
                quality_metrics_json=quality_metrics,
                messages=ordered_messages,
                normalized_answers=ordered_answers,
                prepared_matrix=prepared_matrix,
                criterion_weights=ordered_weights,
                failure_code=None,
                failure_detail=None,
            )
        )
        return replace(
            self,
            status=resolved_status,
            completion_ratio=completion_ratio,
            consistency_ratio=consistency_ratio,
            quality_metrics_json=quality_metrics,
            completed_at=at,
            validated_by_actor_type=actor_type,
            validated_by_actor_id=actor_id,
            output_hash=output_hash,
            messages=ordered_messages,
            normalized_answers=ordered_answers,
            prepared_matrix=prepared_matrix,
            criterion_weights=ordered_weights,
        )

    def fail(
        self,
        *,
        failure_code: str,
        failure_detail: str,
        actor_type: ActorType,
        actor_id: str,
        at: datetime,
        messages: tuple[ValidationMessage, ...] = (),
        quality_metrics_json: JsonObject | None = None,
        completion_ratio: Decimal = Decimal(0),
    ) -> Self:
        """Finish a running attempt as an execution error, without outputs."""

        self._require_running(actor_id=actor_id, at=at)
        _require_text(failure_code, "Validation failure code")
        _require_text(failure_detail, "Validation failure detail")
        ordered_messages = tuple(
            sorted(
                messages,
                key=lambda item: (
                    item.display_order,
                    item.validation_message_id,
                ),
            )
        )
        quality_metrics = _copy_json(quality_metrics_json or {})
        output_hash = hash_json(
            _output_manifest(
                status=ValidationStatus.ERROR,
                completion_ratio=completion_ratio,
                consistency_ratio=None,
                quality_metrics_json=quality_metrics,
                messages=ordered_messages,
                normalized_answers=(),
                prepared_matrix=None,
                criterion_weights=(),
                failure_code=failure_code,
                failure_detail=failure_detail,
            )
        )
        return replace(
            self,
            status=ValidationStatus.ERROR,
            completion_ratio=completion_ratio,
            consistency_ratio=None,
            quality_metrics_json=quality_metrics,
            completed_at=at,
            validated_by_actor_type=actor_type,
            validated_by_actor_id=actor_id,
            output_hash=output_hash,
            failure_code=failure_code,
            failure_detail=failure_detail,
            messages=ordered_messages,
            normalized_answers=(),
            prepared_matrix=None,
            criterion_weights=(),
        )

    def validate_integrity(self) -> None:
        """Recompute hashes and recheck all persisted validation evidence."""

        if hash_json(self.parameter_json) != self.parameter_hash:
            raise ValidationRuleViolation(
                "Validator parameters do not match parameter_hash."
            )
        expected_input_hash = hash_json(
            _input_manifest(
                submission_id=self.submission_id,
                answers_hash=self.answers_hash,
                configuration_hash=self.configuration_hash,
                validator_implementation_id=self.validator_implementation_id,
                validator_version=self.validator_version,
                parameter_hash=self.parameter_hash,
            )
        )
        if expected_input_hash != self.input_hash:
            raise ValidationRuleViolation(
                "Validation inputs do not match input_hash."
            )
        if self.is_terminal:
            assert self.output_hash is not None
            expected_output_hash = hash_json(
                _output_manifest(
                    status=self.status,
                    completion_ratio=self.completion_ratio,
                    consistency_ratio=self.consistency_ratio,
                    quality_metrics_json=self.quality_metrics_json,
                    messages=self.messages,
                    normalized_answers=self.normalized_answers,
                    prepared_matrix=self.prepared_matrix,
                    criterion_weights=self.criterion_weights,
                    failure_code=self.failure_code,
                    failure_detail=self.failure_detail,
                )
            )
            if expected_output_hash != self.output_hash:
                raise ValidationRuleViolation(
                    "Validation outputs do not match output_hash."
                )

    def _require_running(self, *, actor_id: str, at: datetime) -> None:
        _require_text(actor_id, "Validation actor ID")
        _require_aware_datetime(at, "Validation completion time")
        if self.status != ValidationStatus.RUNNING:
            raise ValidationRuleViolation(
                "Only a running validation can be completed."
            )
        if self.started_at is None:
            raise AssertionError("Running validation is missing started_at.")
        if at < self.started_at:
            raise ValidationRuleViolation(
                "Validation completion cannot precede its start."
            )

    def _validate_identity(self) -> None:
        for field_name, value in (
            ("Validation ID", self.validation_id),
            ("Validation submission ID", self.submission_id),
            (
                "Validator implementation ID",
                self.validator_implementation_id,
            ),
            ("Validator version", self.validator_version),
        ):
            _require_text(value, field_name)
        for field_name, optional_value in (
            ("Validation failure code", self.failure_code),
            ("Validation failure detail", self.failure_detail),
            ("Validation actor ID", self.validated_by_actor_id),
        ):
            _require_optional_text(optional_value, field_name)

    def _validate_input_integrity(self) -> None:
        if (
            isinstance(self.attempt_number, bool)
            or not isinstance(self.attempt_number, int)
            or self.attempt_number < 1
        ):
            raise ValidationRuleViolation(
                "Validation attempt number must be a positive integer."
            )
        _require_sha256(self.answers_hash, "Submission answers hash")
        _require_sha256(self.configuration_hash, "Configuration hash")
        _validate_json(self.parameter_json, "Validator parameters")
        _require_sha256(self.parameter_hash, "Validator parameter hash")
        _require_sha256(self.input_hash, "Validation input hash")

    def _validate_output_values(self) -> None:
        _require_decimal(self.completion_ratio, "Validation completion ratio")
        if not Decimal(0) <= self.completion_ratio <= Decimal(1):
            raise ValidationRuleViolation(
                "Validation completion ratio must be between zero and one."
            )
        if self.consistency_ratio is not None:
            _require_nonnegative_decimal(
                self.consistency_ratio,
                "Validation consistency ratio",
            )
        _validate_json(
            self.quality_metrics_json,
            "Validation quality metrics",
        )
        if self.output_hash is not None:
            _require_sha256(self.output_hash, "Validation output hash")
        _require_aware_datetime(self.started_at, "Validation start time")
        _require_aware_datetime(self.completed_at, "Validation completion time")
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValidationRuleViolation(
                "Validation completion cannot precede its start."
            )

    def _validate_children(self) -> None:
        for message in self.messages:
            if message.validation_id != self.validation_id:
                raise ValidationRuleViolation(
                    "Validation output belongs to a different validation."
                )
        for answer in self.normalized_answers:
            if answer.validation_id != self.validation_id:
                raise ValidationRuleViolation(
                    "Validation output belongs to a different validation."
                )
        for weight in self.criterion_weights:
            if weight.validation_id != self.validation_id:
                raise ValidationRuleViolation(
                    "Validation output belongs to a different validation."
                )
        if (
            self.prepared_matrix is not None
            and self.prepared_matrix.validation_id != self.validation_id
        ):
            raise ValidationRuleViolation(
                "Prepared matrix belongs to a different validation."
            )
        _require_unique(
            (message.validation_message_id for message in self.messages),
            "Validation message IDs",
        )
        _require_unique(
            (message.display_order for message in self.messages),
            "Validation message display orders",
        )
        _require_unique(
            (
                answer.submission_answer_id
                for answer in self.normalized_answers
            ),
            "Normalized submission answer IDs",
        )
        _require_unique(
            (weight.criterion_id for weight in self.criterion_weights),
            "Criterion weight criterion IDs",
        )
        _validate_weight_totals(self.criterion_weights)

    def _validate_lifecycle_state(self) -> None:
        if self.status == ValidationStatus.PENDING:
            self._require_no_execution_state()
            return
        if self.status == ValidationStatus.RUNNING:
            if self.started_at is None:
                raise ValidationRuleViolation(
                    "A running validation requires started_at."
                )
            if self.completed_at is not None:
                raise ValidationRuleViolation(
                    "A running validation cannot have completed_at."
                )
            self._require_no_terminal_state()
            return
        if self.status not in _TERMINAL_STATUSES:
            raise ValidationRuleViolation(
                f"Unsupported validation status: {self.status!r}."
            )
        if self.started_at is None or self.completed_at is None:
            raise ValidationRuleViolation(
                "A terminal validation requires start and completion times."
            )
        if (
            self.validated_by_actor_type is None
            or self.validated_by_actor_id is None
        ):
            raise ValidationRuleViolation(
                "A terminal validation requires validator actor metadata."
            )
        if self.output_hash is None:
            raise ValidationRuleViolation(
                "A terminal validation requires an output hash."
            )
        if self.status == ValidationStatus.ERROR:
            if self.failure_code is None or self.failure_detail is None:
                raise ValidationRuleViolation(
                    "An errored validation requires failure code and detail."
                )
            if self.normalized_answers or self.criterion_weights:
                raise ValidationRuleViolation(
                    "An errored validation cannot publish normalized answers "
                    "or criterion weights."
                )
            return
        if self.failure_code is not None or self.failure_detail is not None:
            raise ValidationRuleViolation(
                "A non-error validation cannot contain execution failure "
                "metadata."
            )
        self._validate_status_message_consistency()

    def _require_no_execution_state(self) -> None:
        if self.started_at is not None:
            raise ValidationRuleViolation(
                "A pending validation cannot have started_at."
            )
        self._require_no_terminal_state()

    def _require_no_terminal_state(self) -> None:
        if (
            self.completed_at is not None
            or self.validated_by_actor_type is not None
            or self.validated_by_actor_id is not None
            or self.output_hash is not None
            or self.failure_code is not None
            or self.failure_detail is not None
            or self.messages
            or self.normalized_answers
            or self.prepared_matrix is not None
            or self.criterion_weights
            or self.consistency_ratio is not None
            or self.completion_ratio != 0
            or self.quality_metrics_json
        ):
            raise ValidationRuleViolation(
                "A nonterminal validation cannot contain terminal outputs."
            )

    def _validate_status_message_consistency(self) -> None:
        severities = {message.severity for message in self.messages}
        has_error = MessageSeverity.ERROR in severities
        has_warning = MessageSeverity.WARNING in severities
        if self.status == ValidationStatus.INVALID:
            if not has_error:
                raise ValidationRuleViolation(
                    "An invalid validation requires an error message."
                )
            return
        if has_error:
            raise ValidationRuleViolation(
                "A valid validation cannot contain an error message."
            )
        if self.status == ValidationStatus.VALID_WITH_WARNING:
            if not has_warning:
                raise ValidationRuleViolation(
                    "A valid-with-warnings result requires a warning message."
                )
            return
        if self.status == ValidationStatus.VALID and has_warning:
            raise ValidationRuleViolation(
                "A valid result with warning messages must use the "
                "valid_with_warnings status."
            )


def _input_manifest(
    *,
    submission_id: str,
    answers_hash: str,
    configuration_hash: str,
    validator_implementation_id: str,
    validator_version: str,
    parameter_hash: str,
) -> dict[str, object]:
    return {
        "schema_version": VALIDATION_INPUT_SCHEMA_VERSION,
        "submission_id": submission_id,
        "answers_hash": answers_hash,
        "configuration_hash": configuration_hash,
        "validator_implementation_id": validator_implementation_id,
        "validator_version": validator_version,
        "parameter_hash": parameter_hash,
    }


def _output_manifest(
    *,
    status: ValidationStatus,
    completion_ratio: Decimal,
    consistency_ratio: Decimal | None,
    quality_metrics_json: JsonObject,
    messages: tuple[ValidationMessage, ...],
    normalized_answers: tuple[ValidationNormalizedAnswer, ...],
    prepared_matrix: ValidationPreparedMatrix | None,
    criterion_weights: tuple[ParticipantCriterionWeight, ...],
    failure_code: str | None,
    failure_detail: str | None,
) -> dict[str, object]:
    manifest: dict[str, object] = {
        "schema_version": VALIDATION_OUTPUT_SCHEMA_VERSION,
        "status": status.value,
        "completion_ratio": completion_ratio,
        "consistency_ratio": consistency_ratio,
        "quality_metrics": dict(quality_metrics_json),
        "messages": [message.to_manifest() for message in messages],
        "normalized_answers": [
            answer.to_manifest() for answer in normalized_answers
        ],
        "criterion_weights": [
            weight.to_manifest() for weight in criterion_weights
        ],
        "failure_code": failure_code,
        "failure_detail": failure_detail,
    }
    # Preserve schema-v1 hashes created before prepared matrices were added.
    if prepared_matrix is not None:
        manifest["prepared_matrix"] = prepared_matrix.to_manifest()
    return manifest


def _status_from_messages(
    messages: tuple[ValidationMessage, ...],
) -> ValidationStatus:
    severities = {message.severity for message in messages}
    if MessageSeverity.ERROR in severities:
        return ValidationStatus.INVALID
    if MessageSeverity.WARNING in severities:
        return ValidationStatus.VALID_WITH_WARNING
    return ValidationStatus.VALID


def _require_unique(
    values: Iterable[Hashable],
    field_name: str,
) -> None:
    seen: set[Hashable] = set()
    for value in values:
        if value in seen:
            raise ValidationRuleViolation(f"{field_name} must be unique.")
        seen.add(value)


def _validate_weight_totals(
    weights: tuple[ParticipantCriterionWeight, ...],
) -> None:
    if not weights:
        return
    shapes = {weight.weight_shape for weight in weights}
    if len(shapes) != 1:
        raise ValidationRuleViolation(
            "A validation cannot mix crisp and fuzzy criterion weights."
        )
    if shapes == {"crisp"}:
        total = sum(
            (
                weight.crisp_weight
                for weight in weights
                if weight.crisp_weight is not None
            ),
            start=Decimal(0),
        )
        if abs(total - EXPECTED_WEIGHT_TOTAL) > WEIGHT_TOTAL_TOLERANCE:
            raise ValidationRuleViolation(
                "Crisp criterion weights must total one; "
                f"got {total}."
            )
        return

    lower_total = sum(
        (
            weight.fuzzy_lower
            for weight in weights
            if weight.fuzzy_lower is not None
        ),
        start=Decimal(0),
    )
    middle_total = sum(
        (
            weight.fuzzy_middle
            for weight in weights
            if weight.fuzzy_middle is not None
        ),
        start=Decimal(0),
    )
    upper_total = sum(
        (
            weight.fuzzy_upper
            for weight in weights
            if weight.fuzzy_upper is not None
        ),
        start=Decimal(0),
    )
    if abs(middle_total - EXPECTED_WEIGHT_TOTAL) > WEIGHT_TOTAL_TOLERANCE:
        raise ValidationRuleViolation(
            "Fuzzy criterion middle weights must total one; "
            f"got {middle_total}."
        )
    if lower_total > EXPECTED_WEIGHT_TOTAL + WEIGHT_TOTAL_TOLERANCE:
        raise ValidationRuleViolation(
            "Fuzzy criterion lower weights cannot total more than one."
        )
    if upper_total < EXPECTED_WEIGHT_TOTAL - WEIGHT_TOTAL_TOLERANCE:
        raise ValidationRuleViolation(
            "Fuzzy criterion upper weights cannot total less than one."
        )
