"""Application use case for validating one immutable submitted response."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.ports.validator import (
    ValidationRequest,
    Validator,
    ValidatorContractViolation,
    ValidatorExecutionError,
    ValidatorMetadata,
    ValidatorRegistry,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.audit import AuditEvent
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AlgorithmRole,
    AuditAction,
    SubmissionStatus,
    ValidationStatus,
)
from poli_insight.domain.session import (
    Session,
    SessionAlgorithmConfig,
    SessionConfigurationVersion,
    SessionRuleViolation,
)
from poli_insight.domain.submission import (
    Submission,
    SubmissionRuleViolation,
)
from poli_insight.domain.validation import (
    SubmissionValidation,
    ValidationRuleViolation,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]

_CONTRACT_FAILURE_CODE = "validator.contract_violation"
_UNEXPECTED_FAILURE_CODE = "validator.unexpected_error"
_CONTRACT_FAILURE_DETAIL = (
    "The validator returned an incompatible validation result."
)
_UNEXPECTED_FAILURE_DETAIL = (
    "The validator could not complete because of an unexpected execution "
    "error."
)
_INTERRUPTED_FAILURE_CODE = "validator.interrupted"
_INTERRUPTED_FAILURE_DETAIL = (
    "A previous validation attempt stopped before producing a terminal result."
)


class ValidateSubmissionError(ValueError):
    """Expected application failure before or while storing validation."""


@dataclass(frozen=True, slots=True)
class ValidateSubmissionCommand:
    """Select a submitted attempt and its frozen validation configuration."""

    submission_id: str
    session_algorithm_config_id: str
    actor_id: str
    actor_type: ActorType = ActorType.SYSTEM
    correlation_id: str = field(default_factory=lambda: str(new_id()))
    request_id: str | None = None
    causation_event_id: str | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("submission_id", self.submission_id),
            (
                "session_algorithm_config_id",
                self.session_algorithm_config_id,
            ),
            ("actor_id", self.actor_id),
            ("correlation_id", self.correlation_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValidateSubmissionError(
                    f"{field_name} cannot be empty."
                )
            if value != value.strip():
                raise ValidateSubmissionError(
                    f"{field_name} cannot contain surrounding whitespace."
                )


@dataclass(frozen=True, slots=True)
class ValidateSubmissionResult:
    """Application-facing summary of terminal validation evidence."""

    validation_id: str
    submission_id: str
    status: ValidationStatus
    input_hash: str
    output_hash: str
    message_count: int
    normalized_answer_count: int
    criterion_weight_count: int
    failure_code: str | None
    reused: bool = False


@dataclass(frozen=True, slots=True)
class _PreparedValidation:
    validation: SubmissionValidation
    request: ValidationRequest
    submission: Submission
    metadata: ValidatorMetadata
    validator: Validator


class ValidateSubmission:
    """Validate one exact submitted attempt and retain immutable evidence."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        validator: Validator | ValidatorRegistry,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
        stale_after: timedelta = timedelta(minutes=30),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._validator = validator
        self._clock = clock
        self._id_factory = id_factory
        if stale_after <= timedelta(0):
            raise ValueError("stale_after must be positive.")
        self._stale_after = stale_after

    def execute(
        self,
        command: ValidateSubmissionCommand,
    ) -> ValidateSubmissionResult:
        prepared_or_existing = self._prepare(command)
        if isinstance(prepared_or_existing, SubmissionValidation):
            return _to_result(prepared_or_existing, reused=True)

        prepared = prepared_or_existing
        terminal, retryable = self._execute_validator(prepared, command)
        self._store_outcome(
            terminal,
            prepared=prepared,
            command=command,
            retryable=retryable,
        )
        return _to_result(terminal, reused=False)

    def _prepare(
        self,
        command: ValidateSubmissionCommand,
    ) -> _PreparedValidation | SubmissionValidation:
        started_at = self._clock()
        validation_id = self._id_factory()

        with self._unit_of_work_factory() as unit_of_work:
            submission = unit_of_work.submissions.get_for_update(
                command.submission_id
            )
            if submission is None:
                raise ValidateSubmissionError(
                    f"Submission {command.submission_id!r} does not exist."
                )
            _require_submitted_attempt(submission)

            session = unit_of_work.session.get(submission.session_id)
            if session is None:
                raise ValidateSubmissionError(
                    "The submission's session no longer exists."
                )
            configuration = _configuration_for_submission(
                session,
                submission,
            )
            algorithm_config = _weighting_algorithm(
                configuration,
                command.session_algorithm_config_id,
            )
            validator = self._resolve_validator(
                algorithm_config.algorithm_implementation_id
            )
            metadata = validator.metadata
            snapshot = unit_of_work.scenarios.get_by_id(
                configuration.scenario_snapshot_id
            )
            if snapshot is None:
                raise ValidateSubmissionError(
                    "The frozen scenario snapshot no longer exists."
                )

            try:
                pending = SubmissionValidation.for_submission(
                    validation_id=validation_id,
                    submission=submission,
                    configuration=configuration,
                    validator_implementation_id=(
                        algorithm_config.algorithm_implementation_id
                    ),
                    validator_version=metadata.validator_version,
                    parameter_json=algorithm_config.parameter_json,
                )
            except (
                SessionRuleViolation,
                SubmissionRuleViolation,
                ValidationRuleViolation,
                ValidatorContractViolation,
            ) as error:
                raise ValidateSubmissionError(str(error)) from error

            attempts = unit_of_work.validations.list_by_input_identity(
                submission_id=pending.submission_id,
                answers_hash=pending.answers_hash,
                configuration_hash=pending.configuration_hash,
                validator_implementation_id=(
                    pending.validator_implementation_id
                ),
                validator_version=pending.validator_version,
                parameter_hash=pending.parameter_hash,
            )
            reusable = next(
                (
                    item
                    for item in reversed(attempts)
                    if item.status
                    in {
                        ValidationStatus.VALID,
                        ValidationStatus.VALID_WITH_WARNING,
                        ValidationStatus.INVALID,
                    }
                ),
                None,
            )
            if reusable is not None:
                return reusable
            active = next((item for item in attempts if not item.is_terminal), None)
            if active is not None:
                if (
                    active.status != ValidationStatus.RUNNING
                    or active.started_at is None
                    or active.started_at > started_at - self._stale_after
                ):
                    raise ValidateSubmissionError(
                        "An equivalent validation attempt is already pending or "
                        "running."
                    )
                interrupted = active.fail(
                    failure_code=_INTERRUPTED_FAILURE_CODE,
                    failure_detail=_INTERRUPTED_FAILURE_DETAIL,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    at=started_at,
                    quality_metrics_json={"retryable": True},
                )
                unit_of_work.validations.save(interrupted)
                unit_of_work.audit_events.add(
                    _build_validated_event(
                        before=active,
                        after=interrupted,
                        submission=submission,
                        metadata=metadata,
                        command=command,
                        retryable=True,
                        event_id=self._id_factory(),
                    )
                )
            if attempts:
                pending = SubmissionValidation.for_submission(
                    validation_id=validation_id,
                    submission=submission,
                    configuration=configuration,
                    validator_implementation_id=(
                        algorithm_config.algorithm_implementation_id
                    ),
                    validator_version=metadata.validator_version,
                    parameter_json=algorithm_config.parameter_json,
                    attempt_number=max(item.attempt_number for item in attempts) + 1,
                )
            running = pending.start(at=started_at)
            request = ValidationRequest(
                validation=running,
                submission=submission,
                configuration=configuration,
                scenario_snapshot=snapshot,
                algorithm_config=algorithm_config,
            )
            try:
                request.ensure_compatible(metadata)
            except ValidatorContractViolation as error:
                raise ValidateSubmissionError(str(error)) from error

            unit_of_work.validations.add(running)
            unit_of_work.commit()

        return _PreparedValidation(
            validation=running,
            request=request,
            submission=submission,
            metadata=metadata,
            validator=validator,
        )

    def _execute_validator(
        self,
        prepared: _PreparedValidation,
        command: ValidateSubmissionCommand,
    ) -> tuple[SubmissionValidation, bool]:
        started_at = prepared.validation.started_at
        if started_at is None:
            raise AssertionError("Running validation is missing started_at.")

        try:
            execution_result = prepared.validator.validate(prepared.request)
        except ValidatorExecutionError as error:
            completed_at = _not_before(self._clock(), started_at)
            return (
                prepared.validation.fail(
                    failure_code=error.code,
                    failure_detail=error.safe_detail,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    at=completed_at,
                    quality_metrics_json={"retryable": error.retryable},
                ),
                error.retryable,
            )
        except (ValidatorContractViolation, ValidationRuleViolation):
            completed_at = _not_before(self._clock(), started_at)
            return (
                prepared.validation.fail(
                    failure_code=_CONTRACT_FAILURE_CODE,
                    failure_detail=_CONTRACT_FAILURE_DETAIL,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    at=completed_at,
                ),
                False,
            )
        except Exception:  # noqa: BLE001 - provider details must not escape
            completed_at = _not_before(self._clock(), started_at)
            return (
                prepared.validation.fail(
                    failure_code=_UNEXPECTED_FAILURE_CODE,
                    failure_detail=_UNEXPECTED_FAILURE_DETAIL,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    at=completed_at,
                ),
                False,
            )

        completed_at = _not_before(self._clock(), started_at)
        try:
            terminal = execution_result.apply_to(
                prepared.validation,
                actor_type=command.actor_type,
                actor_id=command.actor_id,
                at=completed_at,
            )
            return terminal, False
        except (ValidatorContractViolation, ValidationRuleViolation):
            return (
                prepared.validation.fail(
                    failure_code=_CONTRACT_FAILURE_CODE,
                    failure_detail=_CONTRACT_FAILURE_DETAIL,
                    actor_type=command.actor_type,
                    actor_id=command.actor_id,
                    at=completed_at,
                ),
                False,
            )

    def _store_outcome(
        self,
        terminal: SubmissionValidation,
        *,
        prepared: _PreparedValidation,
        command: ValidateSubmissionCommand,
        retryable: bool,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            persisted = unit_of_work.validations.get_for_update(
                terminal.validation_id
            )
            if persisted is None:
                raise ValidateSubmissionError(
                    "The running validation attempt no longer exists."
                )
            if persisted != prepared.validation:
                raise ValidateSubmissionError(
                    "The running validation attempt changed during execution."
                )

            unit_of_work.validations.save(terminal)
            unit_of_work.audit_events.add(
                _build_validated_event(
                    before=persisted,
                    after=terminal,
                    submission=prepared.submission,
                    metadata=prepared.metadata,
                    command=command,
                    retryable=retryable,
                    event_id=self._id_factory(),
                )
            )
            unit_of_work.commit()

    def _resolve_validator(self, implementation_id: str) -> Validator:
        resolver = getattr(self._validator, "for_implementation", None)
        if callable(resolver):
            resolved = resolver(implementation_id)
            return resolved
        return self._validator  # type: ignore[return-value]


def _require_submitted_attempt(submission: Submission) -> None:
    if submission.status == SubmissionStatus.DRAFT:
        raise ValidateSubmissionError(
            "A draft submission cannot be validated."
        )
    if submission.status == SubmissionStatus.SUPERSEDED:
        raise ValidateSubmissionError(
            "A superseded submission cannot start a new validation."
        )
    if submission.status == SubmissionStatus.WITHDRAWN:
        raise ValidateSubmissionError(
            "A withdrawn submission cannot be validated."
        )
    if submission.status != SubmissionStatus.SUBMITTED:
        raise ValidateSubmissionError(
            f"Unsupported submission status {submission.status.value!r}."
        )


def _not_before(value: datetime, minimum: datetime) -> datetime:
    """Protect terminal evidence from a wall-clock adjustment during work."""

    return max(value, minimum)


def _configuration_for_submission(
    session: Session,
    submission: Submission,
) -> SessionConfigurationVersion:
    if session.session_id != submission.session_id:
        raise ValidateSubmissionError(
            "Loaded session does not own the submitted attempt."
        )
    configuration = next(
        (
            candidate
            for candidate in session.configurations
            if candidate.configuration_version_id
            == submission.configuration_version_id
        ),
        None,
    )
    if configuration is None:
        raise ValidateSubmissionError(
            "The submission's frozen configuration no longer exists."
        )
    try:
        submission.validate_against_configuration(configuration)
    except SubmissionRuleViolation as error:
        raise ValidateSubmissionError(str(error)) from error
    return configuration


def _weighting_algorithm(
    configuration: SessionConfigurationVersion,
    algorithm_config_id: str,
) -> SessionAlgorithmConfig:
    algorithm = next(
        (
            candidate
            for candidate in configuration.algorithm_configs
            if candidate.session_algorithm_config_id == algorithm_config_id
        ),
        None,
    )
    if algorithm is None:
        raise ValidateSubmissionError(
            "The requested validation algorithm is outside the frozen "
            "configuration."
        )
    if algorithm.role != AlgorithmRole.WEIGHTING:
        raise ValidateSubmissionError(
            "The requested algorithm configuration is not a weighting method."
        )
    return algorithm


def _to_result(
    validation: SubmissionValidation,
    *,
    reused: bool,
) -> ValidateSubmissionResult:
    if not validation.is_terminal or validation.output_hash is None:
        raise AssertionError("Validation result must be terminal and hashed.")
    return ValidateSubmissionResult(
        validation_id=validation.validation_id,
        submission_id=validation.submission_id,
        status=validation.status,
        input_hash=validation.input_hash,
        output_hash=validation.output_hash,
        message_count=len(validation.messages),
        normalized_answer_count=len(validation.normalized_answers),
        criterion_weight_count=len(validation.criterion_weights),
        failure_code=validation.failure_code,
        reused=reused,
    )


def _validation_projection(
    validation: SubmissionValidation,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "validation_id": validation.validation_id,
        "submission_id": validation.submission_id,
        "status": validation.status.value,
        "input_hash": validation.input_hash,
        "output_hash": validation.output_hash,
        "completion_ratio": str(validation.completion_ratio),
        "consistency_ratio": (
            str(validation.consistency_ratio)
            if validation.consistency_ratio is not None
            else None
        ),
        "started_at": (
            validation.started_at.isoformat()
            if validation.started_at is not None
            else None
        ),
        "completed_at": (
            validation.completed_at.isoformat()
            if validation.completed_at is not None
            else None
        ),
        "message_count": len(validation.messages),
        "normalized_answer_count": len(validation.normalized_answers),
        "criterion_weight_count": len(validation.criterion_weights),
        "failure_code": validation.failure_code,
    }


def _build_validated_event(
    *,
    before: SubmissionValidation,
    after: SubmissionValidation,
    submission: Submission,
    metadata: ValidatorMetadata,
    command: ValidateSubmissionCommand,
    retryable: bool,
    event_id: str,
) -> AuditEvent:
    if after.completed_at is None:
        raise AssertionError("Terminal validation is missing completed_at.")
    before_json = _validation_projection(before)
    after_json = _validation_projection(after)
    source_metadata = {
        "schema_version": 1,
        "use_case": "validate_submission",
        "validator_adapter_version": metadata.adapter_version,
        "parameter_schema_version": metadata.parameter_schema_version,
        "retryable_failure": retryable,
    }
    hash_input = {
        "audit_event_id": event_id,
        "occurred_at": after.completed_at,
        "session_id": submission.session_id,
        "actor_type": command.actor_type.value,
        "actor_id": command.actor_id,
        "action": AuditAction.VALIDATED.value,
        "entity_type": "submission_validation",
        "entity_id": after.validation_id,
        "correlation_id": command.correlation_id,
        "request_id": command.request_id,
        "causation_event_id": command.causation_event_id,
        "before_json": before_json,
        "after_json": after_json,
        "source_metadata_json": source_metadata,
    }
    return AuditEvent(
        audit_event_id=event_id,
        occurred_at=after.completed_at,
        session_id=submission.session_id,
        actor_type=command.actor_type,
        actor_id=command.actor_id,
        action=AuditAction.VALIDATED,
        entity_type="submission_validation",
        entity_id=after.validation_id,
        correlation_id=command.correlation_id,
        request_id=command.request_id,
        causation_event_id=command.causation_event_id,
        before_json=before_json,
        after_json=after_json,
        source_metadata_json=source_metadata,
        event_hash=hash_json(hash_input),
    )
