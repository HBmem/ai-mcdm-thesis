from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from poli_insight.domain.content_hash import hash_json
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
    ValidationRuleViolation,
)


STARTED_AT = datetime(2026, 7, 30, 12, tzinfo=UTC)
COMPLETED_AT = STARTED_AT + timedelta(seconds=2)


def _pending_validation() -> SubmissionValidation:
    return SubmissionValidation.create_pending(
        validation_id="validation-1",
        submission_id="submission-1",
        answers_hash=hash_json({"answers": [1, 2]}),
        configuration_hash=hash_json({"configuration": 1}),
        validator_implementation_id="validator-implementation-1",
        validator_version="1.2.0",
        parameter_json={"consistency_threshold": Decimal("0.1")},
    )


def _message(
    *,
    severity: MessageSeverity,
    code: str,
    display_order: int = 0,
) -> ValidationMessage:
    return ValidationMessage(
        validation_message_id=f"message-{display_order}",
        validation_id="validation-1",
        severity=severity,
        code=code,
        safe_message=f"Safe {severity.value} message.",
        display_order=display_order,
        parameters_json={"threshold": Decimal("0.1")},
    )


def _crisp_weights() -> tuple[ParticipantCriterionWeight, ...]:
    return (
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-a",
            crisp_weight=Decimal("0.4"),
        ),
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-b",
            crisp_weight=Decimal("0.6"),
        ),
    )


def test_complete_validation_freezes_and_hashes_structured_outputs() -> None:
    pending = _pending_validation()
    running = pending.start(at=STARTED_AT)
    normalized_answer = ValidationNormalizedAnswer(
        validation_id="validation-1",
        submission_answer_id="answer-1",
        normalized_value_json={"value": Decimal("0.75")},
        normalizer_version="normalizer-1",
        crisp_value=Decimal("0.75"),
    )

    completed = running.complete(
        completion_ratio=Decimal("1"),
        messages=(
            _message(
                severity=MessageSeverity.INFO,
                code="validation.complete",
            ),
        ),
        normalized_answers=(normalized_answer,),
        criterion_weights=_crisp_weights(),
        quality_metrics_json={"answered": 2, "expected": 2},
        consistency_ratio=Decimal("0.05"),
        actor_type=ActorType.SYSTEM,
        actor_id="submission-validator",
        at=COMPLETED_AT,
    )

    assert completed.status == ValidationStatus.VALID
    assert completed.is_terminal
    assert completed.is_usable_for_processing
    assert completed.input_hash == pending.input_hash
    assert completed.output_hash is not None
    completed.validate_integrity()
    with pytest.raises(FrozenInstanceError):
        setattr(completed, "status", ValidationStatus.INVALID)


def test_warning_and_invalid_statuses_are_distinct_from_execution_error() -> None:
    running = _pending_validation().start(at=STARTED_AT)

    warned = running.complete(
        completion_ratio=Decimal("1"),
        messages=(
            _message(
                severity=MessageSeverity.WARNING,
                code="consistency.threshold_near",
            ),
        ),
        actor_type=ActorType.SYSTEM,
        actor_id="submission-validator",
        at=COMPLETED_AT,
    )
    invalid = running.complete(
        completion_ratio=Decimal("0.5"),
        messages=(
            _message(
                severity=MessageSeverity.ERROR,
                code="answers.incomplete",
            ),
        ),
        actor_type=ActorType.SYSTEM,
        actor_id="submission-validator",
        at=COMPLETED_AT,
    )
    failed = running.fail(
        failure_code="validator.unavailable",
        failure_detail="Validator process did not return a result.",
        actor_type=ActorType.SYSTEM,
        actor_id="submission-validator",
        at=COMPLETED_AT,
    )

    assert warned.status == ValidationStatus.VALID_WITH_WARNING
    assert warned.is_usable_for_processing
    assert invalid.status == ValidationStatus.INVALID
    assert not invalid.is_usable_for_processing
    assert failed.status == ValidationStatus.ERROR
    assert failed.failure_code == "validator.unavailable"
    assert not failed.is_usable_for_processing


def test_explicit_status_must_agree_with_message_severity() -> None:
    running = _pending_validation().start(at=STARTED_AT)

    with pytest.raises(
        ValidationRuleViolation,
        match="warning messages",
    ):
        running.complete(
            status=ValidationStatus.VALID,
            completion_ratio=Decimal("1"),
            messages=(
                _message(
                    severity=MessageSeverity.WARNING,
                    code="consistency.warning",
                ),
            ),
            actor_type=ActorType.SYSTEM,
            actor_id="submission-validator",
            at=COMPLETED_AT,
        )


def test_crisp_weights_must_total_one() -> None:
    running = _pending_validation().start(at=STARTED_AT)
    invalid_total = (
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-a",
            crisp_weight=Decimal("0.2"),
        ),
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-b",
            crisp_weight=Decimal("0.3"),
        ),
    )

    with pytest.raises(
        ValidationRuleViolation,
        match="must total one",
    ):
        running.complete(
            completion_ratio=Decimal("1"),
            criterion_weights=invalid_total,
            actor_type=ActorType.SYSTEM,
            actor_id="submission-validator",
            at=COMPLETED_AT,
        )


def test_fuzzy_weights_require_ordered_triples_and_normalized_middle() -> None:
    running = _pending_validation().start(at=STARTED_AT)
    fuzzy_weights = (
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-a",
            fuzzy_lower=Decimal("0.2"),
            fuzzy_middle=Decimal("0.4"),
            fuzzy_upper=Decimal("0.7"),
        ),
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-b",
            fuzzy_lower=Decimal("0.3"),
            fuzzy_middle=Decimal("0.6"),
            fuzzy_upper=Decimal("0.8"),
        ),
    )

    completed = running.complete(
        completion_ratio=Decimal("1"),
        criterion_weights=fuzzy_weights,
        actor_type=ActorType.SYSTEM,
        actor_id="submission-validator",
        at=COMPLETED_AT,
    )

    assert completed.status == ValidationStatus.VALID
    assert {weight.weight_shape for weight in completed.criterion_weights} == {
        "fuzzy"
    }

    with pytest.raises(ValidationRuleViolation, match="lower <= middle"):
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-invalid",
            fuzzy_lower=Decimal("0.5"),
            fuzzy_middle=Decimal("0.4"),
            fuzzy_upper=Decimal("0.7"),
        )


def test_validation_rejects_mixed_crisp_and_fuzzy_weight_sets() -> None:
    running = _pending_validation().start(at=STARTED_AT)
    mixed_weights = (
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-a",
            crisp_weight=Decimal("0.4"),
        ),
        ParticipantCriterionWeight(
            validation_id="validation-1",
            criterion_id="criterion-b",
            fuzzy_lower=Decimal("0.4"),
            fuzzy_middle=Decimal("0.6"),
            fuzzy_upper=Decimal("0.8"),
        ),
    )

    with pytest.raises(ValidationRuleViolation, match="mix crisp and fuzzy"):
        running.complete(
            completion_ratio=Decimal("1"),
            criterion_weights=mixed_weights,
            actor_type=ActorType.SYSTEM,
            actor_id="submission-validator",
            at=COMPLETED_AT,
        )


def test_normalized_answer_numeric_shape_is_consistent() -> None:
    with pytest.raises(ValidationRuleViolation, match="both crisp and fuzzy"):
        ValidationNormalizedAnswer(
            validation_id="validation-1",
            submission_answer_id="answer-1",
            normalized_value_json={"value": Decimal("0.5")},
            normalizer_version="normalizer-1",
            crisp_value=Decimal("0.5"),
            fuzzy_lower=Decimal("0.4"),
            fuzzy_middle=Decimal("0.5"),
            fuzzy_upper=Decimal("0.6"),
        )


def test_output_children_must_belong_to_the_validation() -> None:
    running = _pending_validation().start(at=STARTED_AT)
    wrong_owner = ParticipantCriterionWeight(
        validation_id="validation-2",
        criterion_id="criterion-a",
        crisp_weight=Decimal("1"),
    )

    with pytest.raises(ValidationRuleViolation, match="different validation"):
        running.complete(
            completion_ratio=Decimal("1"),
            criterion_weights=(wrong_owner,),
            actor_type=ActorType.SYSTEM,
            actor_id="submission-validator",
            at=COMPLETED_AT,
        )


def test_lifecycle_requires_aware_and_monotonic_timestamps() -> None:
    pending = _pending_validation()

    with pytest.raises(ValidationRuleViolation, match="timezone"):
        pending.start(at=datetime(2026, 7, 30, 12))

    running = pending.start(at=STARTED_AT)
    with pytest.raises(ValidationRuleViolation, match="cannot precede"):
        running.complete(
            completion_ratio=Decimal("1"),
            actor_type=ActorType.SYSTEM,
            actor_id="submission-validator",
            at=STARTED_AT - timedelta(seconds=1),
        )


def test_integrity_check_detects_changed_terminal_output() -> None:
    completed = _pending_validation().start(at=STARTED_AT).complete(
        completion_ratio=Decimal("1"),
        actor_type=ActorType.SYSTEM,
        actor_id="submission-validator",
        at=COMPLETED_AT,
    )

    with pytest.raises(ValidationRuleViolation, match="output_hash"):
        replace(completed, quality_metrics_json={"tampered": True})
