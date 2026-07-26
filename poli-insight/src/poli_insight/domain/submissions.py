from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Mapping, Self

from poli_insight.domain.enums import (
    SubmissionStatus,
    WeightingMethod,
)


class SubmissionRuleViolation(ValueError):
    """Raised when an operation violates a submission rule."""
    pass

class ValidationRunRuleViolation(ValueError):
    """Raise when an operation violates a validation run"""
    pass

def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and value.tzinfo is None:
        raise SubmissionRuleViolation(
            f"{field_name} must include timezone information."
        )


@dataclass
class Submission:
    """One submission attempt made by one participant."""

    submission_id: str
    participant_id: str
    attempt_number: int
    previous_submission_id: str | None

    status: SubmissionStatus
    answers: dict[str, Any]

    started_at: datetime
    last_saved_at: datetime | None
    submitted_at: datetime | None
    submitted_by: str | None
    superseded_at: datetime | None
    withdrawn_at: datetime | None
    withdrawn_by: str | None

    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_status()
        self._validate_timestamps()

    @classmethod
    def create_draft(
        cls,
        *,
        submission_id: str,
        participant_id: str,
        attempt_number: int,
        previous_submission_id: str | None,
        actor_id: str,
        now: datetime | None = None,
    ) -> Self:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        return cls(
            submission_id=submission_id,
            participant_id=participant_id,
            attempt_number=attempt_number,
            previous_submission_id=previous_submission_id,
            status=SubmissionStatus.DRAFT,
            answers={},
            started_at=timestamp,
            last_saved_at=None,
            submitted_at=None,
            submitted_by=None,
            superseded_at=None,
            withdrawn_at=None,
            withdrawn_by=None,
            created_at=timestamp,
            created_by=actor_id,
            updated_at=timestamp,
            updated_by=actor_id,
        )

    def save_answers(
        self,
        *,
        answers: Mapping[str, Any],
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status != SubmissionStatus.DRAFT:
            raise SubmissionRuleViolation(
                "Only a draft submission can be edited."
            )

        self.answers = dict(answers)
        self.last_saved_at = timestamp
        self._mark_updated(actor_id, timestamp)

    def submit(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status != SubmissionStatus.DRAFT:
            raise SubmissionRuleViolation(
                "Only a draft submission can be submitted."
            )

        self.status = SubmissionStatus.SUBMITTED
        self.submitted_at = timestamp
        self.submitted_by = actor_id
        self._mark_updated(actor_id, timestamp)

    def supersede(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status != SubmissionStatus.SUBMITTED:
            raise SubmissionRuleViolation(
                "Only a submitted submission can be superseded."
            )

        self.status = SubmissionStatus.SUPERSEDED
        self.superseded_at = timestamp
        self._mark_updated(actor_id, timestamp)

    def withdraw(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status == SubmissionStatus.SUPERSEDED:
            raise SubmissionRuleViolation(
                "A superseded submission cannot be withdrawn."
            )

        self.status = SubmissionStatus.WITHDRAWN
        self.withdrawn_at = timestamp
        self.withdrawn_by = actor_id
        self._mark_updated(actor_id, timestamp)

    @property
    def completion_duration_seconds(self) -> int | None:
        if self.submitted_at is None:
            return None

        return int(
            (self.submitted_at - self.started_at).total_seconds()
        )

    def _validate_identity(self) -> None:
        if not self.submission_id.strip():
            raise SubmissionRuleViolation(
                "Submission ID cannot be empty."
            )

        if not self.participant_id.strip():
            raise SubmissionRuleViolation(
                "Participant ID cannot be empty."
            )

        if self.attempt_number < 1:
            raise SubmissionRuleViolation(
                "Attempt number must be at least one."
            )

        if self.previous_submission_id == self.submission_id:
            raise SubmissionRuleViolation(
                "A submission cannot replace itself."
            )

    def _validate_status(self) -> None:
        if self.status in {
            SubmissionStatus.SUBMITTED,
            SubmissionStatus.SUPERSEDED,
        }:
            if self.submitted_at is None or self.submitted_by is None:
                raise SubmissionRuleViolation(
                    "Submitted attempts require submission metadata."
                )

        if (
            self.status == SubmissionStatus.SUPERSEDED
            and self.superseded_at is None
        ):
            raise SubmissionRuleViolation(
                "A superseded attempt requires superseded_at."
            )

        if (
            self.status == SubmissionStatus.WITHDRAWN
            and self.withdrawn_at is None
        ):
            raise SubmissionRuleViolation(
                "A withdrawn attempt requires withdrawn_at."
            )

    def _validate_timestamps(self) -> None:
        for field_name in (
            "started_at",
            "last_saved_at",
            "submitted_at",
            "superseded_at",
            "withdrawn_at",
            "created_at",
            "updated_at",
        ):
            _require_aware_datetime(
                getattr(self, field_name),
                field_name,
            )

        if (
            self.submitted_at is not None
            and self.submitted_at < self.started_at
        ):
            raise SubmissionRuleViolation(
                "submitted_at cannot precede started_at."
            )

    def _mark_updated(
        self,
        actor_id: str,
        timestamp: datetime,
    ) -> None:
        if not actor_id.strip():
            raise SubmissionRuleViolation(
                "Updating actor cannot be empty."
            )

        self.updated_at = timestamp
        self.updated_by = actor_id

@dataclass
class SubmissionValidation:
    validation_id: str
    submission_id: str
    answers_hash: str
    weighting_method: WeightingMethod
    validator_version: str

    completion_ratio: float
    weights: dict[str, float]
    consistency_ratio: float | None
    is_valid: bool
    errors: tuple[str, ...]

    validated_at: datetime
    validated_by: str