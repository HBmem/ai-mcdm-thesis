"""Human review decisions for finalized participant submissions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.enum import (
    ActorType,
    AuditAction,
    SubmissionReviewStatus,
    SubmissionStatus,
)
from poli_insight.domain.operations import (
    OperationalRuleViolation,
    SubmissionReviewDecision,
    validate_review_transition,
)

UnitOfWorkFactory = Callable[[], UnitOfWork]
Clock = Callable[[], datetime]
IdFactory = Callable[[], str]


class ReviewSubmissionError(ValueError):
    """Safe application failure during operator review."""


@dataclass(frozen=True, slots=True)
class ReviewSubmissionCommand:
    session_id: str
    submission_id: str
    status: SubmissionReviewStatus
    actor_id: str
    reviewer_notes: str | None = None
    validation_id: str | None = None
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        for field_name, value in (
            ("Session ID", self.session_id),
            ("Submission ID", self.submission_id),
            ("Actor ID", self.actor_id),
            ("Correlation ID", self.correlation_id),
        ):
            if not value.strip():
                raise ReviewSubmissionError(f"{field_name} cannot be empty.")
        if self.reviewer_notes is not None and not self.reviewer_notes.strip():
            raise ReviewSubmissionError("Reviewer notes cannot be blank when provided.")


class ReviewSubmission:
    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        clock: Clock = utc_now,
        id_factory: IdFactory = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory

    def execute(self, command: ReviewSubmissionCommand) -> SubmissionReviewDecision:
        at = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            submission = unit_of_work.submissions.get_for_update(command.submission_id)
            if submission is None or submission.session_id != command.session_id:
                raise ReviewSubmissionError("Submission was not found.")
            if submission.status != SubmissionStatus.SUBMITTED:
                raise ReviewSubmissionError(
                    "Only the current submitted attempt can be reviewed."
                )
            previous = unit_of_work.submission_reviews.get_latest(
                submission.submission_id,
                for_update=True,
            )
            try:
                validate_review_transition(previous, command.status)
            except OperationalRuleViolation as error:
                raise ReviewSubmissionError(str(error)) from error

            validation_id = command.validation_id
            validation = None
            if validation_id is not None:
                validation = unit_of_work.validations.get(validation_id)
                if (
                    validation is None
                    or validation.submission_id != submission.submission_id
                ):
                    raise ReviewSubmissionError(
                        "The selected validation does not belong to this submission."
                    )
            elif command.status == SubmissionReviewStatus.ACCEPTED:
                attempts = unit_of_work.validations.list_for_submission(
                    submission.submission_id
                )
                terminal_attempts = tuple(item for item in attempts if item.is_terminal)
                validation = (
                    max(
                        terminal_attempts,
                        key=lambda item: (
                            item.completed_at or at,
                            item.validation_id,
                        ),
                    )
                    if terminal_attempts
                    else None
                )
                validation_id = None if validation is None else validation.validation_id

            if command.status == SubmissionReviewStatus.ACCEPTED and (
                validation is None or not validation.is_usable_for_processing
            ):
                raise ReviewSubmissionError(
                    "Acceptance requires a valid completed validation result."
                )

            try:
                decision = SubmissionReviewDecision(
                    decision_id=self._id_factory(),
                    submission_id=submission.submission_id,
                    validation_id=validation_id,
                    status=command.status,
                    reviewer_notes=(
                        command.reviewer_notes.strip()
                        if command.reviewer_notes is not None
                        else None
                    ),
                    decided_at=at,
                    decided_by=command.actor_id,
                    correlation_id=command.correlation_id,
                )
            except OperationalRuleViolation as error:
                raise ReviewSubmissionError(str(error)) from error

            unit_of_work.submission_reviews.add(decision)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=at,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=_audit_action(command.status),
                    entity_type="submission_review",
                    entity_id=decision.decision_id,
                    correlation_id=command.correlation_id,
                    use_case="review_submission",
                    before_json={
                        "status": (
                            SubmissionReviewStatus.PENDING.value
                            if previous is None
                            else previous.status.value
                        )
                    },
                    after_json={
                        "status": decision.status.value,
                        "submission_id": decision.submission_id,
                        "validation_id": decision.validation_id,
                    },
                    reason_text=decision.reviewer_notes,
                )
            )
            unit_of_work.commit()
        return decision


def _audit_action(status: SubmissionReviewStatus) -> AuditAction:
    if status == SubmissionReviewStatus.ACCEPTED:
        return AuditAction.APPROVED
    if status == SubmissionReviewStatus.REJECTED:
        return AuditAction.EXCLUDED
    return AuditAction.UPDATED
