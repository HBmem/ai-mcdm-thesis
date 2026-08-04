"""Bidirectional mappings for versioned validation evidence.

JSON documents are converted to a portable tagged representation before they
reach SQLAlchemy's JSON serializer, then restored when rows are reconstructed.
This preserves canonical hashes for values such as ``Decimal`` and UUID while
keeping database JSON documents backend-neutral.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID

from poli_insight.core.time import as_utc
from poli_insight.domain.content_hash import canonical_json_bytes
from poli_insight.domain.enum import (
    ActorType,
    MessageSeverity,
    ValidationStatus,
)
from poli_insight.domain.validation import (
    ParticipantCriterionWeight,
    SubmissionValidation,
    ValidationMessage,
    ValidationNormalizedAnswer,
)
from poli_insight.infrastructure.database.models.validation import (
    ParticipantCriterionWeightRow,
    SubmissionValidationRow,
    ValidationMessageRow,
    ValidationNormalizedAnswerRow,
)


class ImmutableValidationInputError(RuntimeError):
    """Raised when mapping a save would replace frozen validation inputs."""


class InvalidValidationTransitionError(RuntimeError):
    """Raised when persisted validation lifecycle state moves illegally."""


class ImmutableValidationOutputError(RuntimeError):
    """Raised when mapping a save would rewrite terminal validation evidence."""


def validation_to_row(
    validation: SubmissionValidation,
) -> SubmissionValidationRow:
    """Map a complete detached validation to a new ORM row graph."""

    validation.validate_integrity()
    return SubmissionValidationRow(
        validation_id=validation.validation_id,
        submission_id=validation.submission_id,
        answers_hash=validation.answers_hash,
        configuration_hash=validation.configuration_hash,
        validator_implementation_id=(
            validation.validator_implementation_id
        ),
        validator_version=validation.validator_version,
        parameter_json=_json_to_storage(validation.parameter_json),
        parameter_hash=validation.parameter_hash,
        status=validation.status.value,
        completion_ratio=validation.completion_ratio,
        consistency_ratio=validation.consistency_ratio,
        quality_metrics_json=_json_to_storage(
            validation.quality_metrics_json
        ),
        started_at=validation.started_at,
        completed_at=validation.completed_at,
        validated_by_actor_type=(
            validation.validated_by_actor_type.value
            if validation.validated_by_actor_type is not None
            else None
        ),
        validated_by_actor_id=validation.validated_by_actor_id,
        input_hash=validation.input_hash,
        output_hash=validation.output_hash,
        failure_code=validation.failure_code,
        failure_detail=validation.failure_detail,
        messages=[
            validation_message_to_row(message)
            for message in sorted(
                validation.messages,
                key=lambda item: (
                    item.display_order,
                    item.validation_message_id,
                ),
            )
        ],
        normalized_answers=[
            validation_normalized_answer_to_row(answer)
            for answer in sorted(
                validation.normalized_answers,
                key=lambda item: item.submission_answer_id,
            )
        ],
        criterion_weights=[
            participant_criterion_weight_to_row(weight)
            for weight in sorted(
                validation.criterion_weights,
                key=lambda item: item.criterion_id,
            )
        ],
    )


def validation_to_domain(
    row: SubmissionValidationRow,
) -> SubmissionValidation:
    """Reconstruct a detached validation and verify its persisted hashes."""

    return SubmissionValidation(
        validation_id=str(row.validation_id),
        submission_id=str(row.submission_id),
        answers_hash=row.answers_hash,
        configuration_hash=row.configuration_hash,
        validator_implementation_id=str(row.validator_implementation_id),
        validator_version=row.validator_version,
        parameter_json=_json_from_storage(row.parameter_json),
        parameter_hash=row.parameter_hash,
        status=ValidationStatus(row.status),
        input_hash=row.input_hash,
        completion_ratio=_required_decimal(
            row.completion_ratio,
            "completion_ratio",
        ),
        consistency_ratio=_optional_decimal(row.consistency_ratio),
        quality_metrics_json=_json_from_storage(row.quality_metrics_json),
        started_at=_optional_utc(row.started_at),
        completed_at=_optional_utc(row.completed_at),
        validated_by_actor_type=(
            ActorType(row.validated_by_actor_type)
            if row.validated_by_actor_type is not None
            else None
        ),
        validated_by_actor_id=row.validated_by_actor_id,
        output_hash=row.output_hash,
        failure_code=row.failure_code,
        failure_detail=row.failure_detail,
        messages=tuple(
            validation_message_to_domain(message_row)
            for message_row in sorted(
                row.messages,
                key=lambda item: (
                    item.display_order,
                    str(item.validation_message_id),
                ),
            )
        ),
        normalized_answers=tuple(
            validation_normalized_answer_to_domain(answer_row)
            for answer_row in sorted(
                row.normalized_answers,
                key=lambda item: str(item.submission_answer_id),
            )
        ),
        criterion_weights=tuple(
            participant_criterion_weight_to_domain(weight_row)
            for weight_row in sorted(
                row.criterion_weights,
                key=lambda item: str(item.criterion_id),
            )
        ),
    )


def validation_message_to_row(
    message: ValidationMessage,
) -> ValidationMessageRow:
    """Map one structured validation finding to its persistence row."""

    return ValidationMessageRow(
        validation_message_id=message.validation_message_id,
        validation_id=message.validation_id,
        severity=message.severity.value,
        code=message.code,
        question_definition_id=message.question_definition_id,
        safe_message=message.safe_message,
        parameters_json=_json_to_storage(message.parameters_json),
        display_order=message.display_order,
    )


def validation_message_to_domain(
    row: ValidationMessageRow,
) -> ValidationMessage:
    """Reconstruct one detached structured validation finding."""

    return ValidationMessage(
        validation_message_id=str(row.validation_message_id),
        validation_id=str(row.validation_id),
        severity=MessageSeverity(row.severity),
        code=row.code,
        question_definition_id=_optional_id(row.question_definition_id),
        safe_message=row.safe_message,
        parameters_json=_json_from_storage(row.parameters_json),
        display_order=row.display_order,
    )


def validation_normalized_answer_to_row(
    answer: ValidationNormalizedAnswer,
) -> ValidationNormalizedAnswerRow:
    """Map one normalized answer without copying authored raw evidence."""

    return ValidationNormalizedAnswerRow(
        validation_id=answer.validation_id,
        submission_answer_id=answer.submission_answer_id,
        normalized_value_json=_json_to_storage(
            answer.normalized_value_json
        ),
        normalizer_version=answer.normalizer_version,
        crisp_value=answer.crisp_value,
        fuzzy_lower=answer.fuzzy_lower,
        fuzzy_middle=answer.fuzzy_middle,
        fuzzy_upper=answer.fuzzy_upper,
    )


def validation_normalized_answer_to_domain(
    row: ValidationNormalizedAnswerRow,
) -> ValidationNormalizedAnswer:
    """Reconstruct one detached validator-produced normalized answer."""

    return ValidationNormalizedAnswer(
        validation_id=str(row.validation_id),
        submission_answer_id=str(row.submission_answer_id),
        normalized_value_json=_json_from_storage(
            row.normalized_value_json
        ),
        normalizer_version=row.normalizer_version,
        crisp_value=_optional_decimal(row.crisp_value),
        fuzzy_lower=_optional_decimal(row.fuzzy_lower),
        fuzzy_middle=_optional_decimal(row.fuzzy_middle),
        fuzzy_upper=_optional_decimal(row.fuzzy_upper),
    )


def participant_criterion_weight_to_row(
    weight: ParticipantCriterionWeight,
) -> ParticipantCriterionWeightRow:
    """Map one crisp or triangular-fuzzy participant criterion weight."""

    return ParticipantCriterionWeightRow(
        validation_id=weight.validation_id,
        criterion_id=weight.criterion_id,
        crisp_weight=weight.crisp_weight,
        fuzzy_lower=weight.fuzzy_lower,
        fuzzy_middle=weight.fuzzy_middle,
        fuzzy_upper=weight.fuzzy_upper,
        derivation_metadata_json=_json_to_storage(
            weight.derivation_metadata_json
        ),
    )


def participant_criterion_weight_to_domain(
    row: ParticipantCriterionWeightRow,
) -> ParticipantCriterionWeight:
    """Reconstruct one detached participant criterion weight."""

    return ParticipantCriterionWeight(
        validation_id=str(row.validation_id),
        criterion_id=str(row.criterion_id),
        crisp_weight=_optional_decimal(row.crisp_weight),
        fuzzy_lower=_optional_decimal(row.fuzzy_lower),
        fuzzy_middle=_optional_decimal(row.fuzzy_middle),
        fuzzy_upper=_optional_decimal(row.fuzzy_upper),
        derivation_metadata_json=_json_from_storage(
            row.derivation_metadata_json
        ),
    )


def apply_validation_aggregate(
    row: SubmissionValidationRow,
    validation: SubmissionValidation,
) -> None:
    """Apply one legal lifecycle transition while preserving all evidence."""

    validation.validate_integrity()
    persisted = validation_to_domain(row)
    _require_unchanged_input(persisted, validation)
    _validate_status_transition(persisted.status, validation.status)

    if persisted.is_terminal:
        if persisted != validation:
            raise ImmutableValidationOutputError(
                "Terminal validation evidence cannot be rewritten."
            )
        return

    if persisted.status == validation.status:
        if persisted != validation:
            raise InvalidValidationTransitionError(
                "Validation state cannot change without a lifecycle "
                "transition."
            )
        return

    row.status = validation.status.value
    row.completion_ratio = validation.completion_ratio
    row.consistency_ratio = validation.consistency_ratio
    row.quality_metrics_json = _json_to_storage(
        validation.quality_metrics_json
    )
    row.started_at = validation.started_at
    row.completed_at = validation.completed_at
    row.validated_by_actor_type = (
        validation.validated_by_actor_type.value
        if validation.validated_by_actor_type is not None
        else None
    )
    row.validated_by_actor_id = validation.validated_by_actor_id
    row.output_hash = validation.output_hash
    row.failure_code = validation.failure_code
    row.failure_detail = validation.failure_detail

    if validation.is_terminal:
        if row.messages or row.normalized_answers or row.criterion_weights:
            raise ImmutableValidationOutputError(
                "Running validation unexpectedly contains persisted outputs."
            )
        row.messages = [
            validation_message_to_row(message)
            for message in validation.messages
        ]
        row.normalized_answers = [
            validation_normalized_answer_to_row(answer)
            for answer in validation.normalized_answers
        ]
        row.criterion_weights = [
            participant_criterion_weight_to_row(weight)
            for weight in validation.criterion_weights
        ]


def _require_unchanged_input(
    persisted: SubmissionValidation,
    replacement: SubmissionValidation,
) -> None:
    immutable_fields = (
        ("validation ID", persisted.validation_id, replacement.validation_id),
        ("submission", persisted.submission_id, replacement.submission_id),
        ("answers hash", persisted.answers_hash, replacement.answers_hash),
        (
            "configuration hash",
            persisted.configuration_hash,
            replacement.configuration_hash,
        ),
        (
            "validator implementation",
            persisted.validator_implementation_id,
            replacement.validator_implementation_id,
        ),
        (
            "validator version",
            persisted.validator_version,
            replacement.validator_version,
        ),
        (
            "parameters",
            _copy_json(persisted.parameter_json),
            _copy_json(replacement.parameter_json),
        ),
        (
            "parameter hash",
            persisted.parameter_hash,
            replacement.parameter_hash,
        ),
        ("input hash", persisted.input_hash, replacement.input_hash),
    )
    for field_name, current, candidate in immutable_fields:
        if current != candidate:
            raise ImmutableValidationInputError(
                f"Validation {field_name} cannot be replaced during save."
            )


def _validate_status_transition(
    persisted: ValidationStatus,
    replacement: ValidationStatus,
) -> None:
    terminal_statuses = {
        ValidationStatus.VALID,
        ValidationStatus.VALID_WITH_WARNING,
        ValidationStatus.INVALID,
        ValidationStatus.ERROR,
    }
    allowed = {
        ValidationStatus.PENDING: {
            ValidationStatus.PENDING,
            ValidationStatus.RUNNING,
        },
        ValidationStatus.RUNNING: {
            ValidationStatus.RUNNING,
            *terminal_statuses,
        },
        **{status: {status} for status in terminal_statuses},
    }
    if replacement not in allowed[persisted]:
        raise InvalidValidationTransitionError(
            "Invalid persisted validation transition: "
            f"{persisted.value} -> {replacement.value}."
        )


def _copy_json(value: Mapping[str, Any]) -> dict[str, Any]:
    """Detach nested JSON data from mapped domain and ORM objects."""

    return deepcopy(dict(value))


def _json_to_storage(value: Mapping[str, Any]) -> dict[str, Any]:
    """Convert supported canonical values to database-native JSON values."""

    encoded = canonical_json_bytes(value).decode("utf-8")
    stored = json.loads(encoded)
    if not isinstance(stored, dict):
        raise TypeError("Validation JSON storage value must be an object.")
    return stored


def _json_from_storage(value: Mapping[str, Any]) -> dict[str, Any]:
    """Restore tagged canonical values from a persisted JSON object."""

    decoded = _decode_storage_value(deepcopy(dict(value)))
    if not isinstance(decoded, dict):
        raise TypeError("Persisted validation JSON value must be an object.")
    return decoded


def _decode_storage_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_storage_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    type_name = value.get("__poli_insight_type__")
    if type_name is not None:
        if set(value) != {"__poli_insight_type__", "value"}:
            raise ValueError("Malformed tagged validation JSON value.")
        tagged_value = value["value"]
        if not isinstance(tagged_value, str):
            raise ValueError("Tagged validation JSON value must contain text.")
        if type_name == "decimal":
            return Decimal(tagged_value)
        if type_name == "uuid":
            return UUID(tagged_value)
        if type_name == "datetime":
            return datetime.fromisoformat(
                tagged_value.replace("Z", "+00:00")
            )
        if type_name == "date":
            return date.fromisoformat(tagged_value)
        raise ValueError(
            f"Unsupported tagged validation JSON type {type_name!r}."
        )

    return {
        key: _decode_storage_value(item)
        for key, item in value.items()
    }


def _optional_id(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _optional_utc(value: datetime | None) -> datetime | None:
    return as_utc(value) if value is not None else None


def _required_decimal(value: Decimal | None, field_name: str) -> Decimal:
    if value is None:
        raise ValueError(f"Persisted validation is missing {field_name}.")
    return _canonical_decimal(value)


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    return _canonical_decimal(value) if value is not None else None


def _canonical_decimal(value: Decimal) -> Decimal:
    """Remove database scale padding before domain hash reconstruction."""

    decimal_value = Decimal(value)
    if decimal_value.is_zero():
        return Decimal("0")
    return decimal_value.normalize()
