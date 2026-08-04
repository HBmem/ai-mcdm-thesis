"""Operational review decisions kept separate from reproducible validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from poli_insight.core.time import is_aware_datetime
from poli_insight.domain.enum import SubmissionReviewStatus


class OperationalRuleViolation(ValueError):
    """Raised when an operational state transition is not allowed."""


_DECISIONS = frozenset(
    {
        SubmissionReviewStatus.NEEDS_REVIEW,
        SubmissionReviewStatus.ACCEPTED,
        SubmissionReviewStatus.REJECTED,
    }
)


@dataclass(frozen=True, slots=True)
class SubmissionReviewDecision:
    """One immutable operator decision for a finalized submission."""

    decision_id: str
    submission_id: str
    status: SubmissionReviewStatus
    decided_at: datetime
    decided_by: str
    correlation_id: str
    reviewer_notes: str | None = None
    validation_id: str | None = None

    def __post_init__(self) -> None:
        for label, value in (
            ("Decision ID", self.decision_id),
            ("Submission ID", self.submission_id),
            ("Reviewer", self.decided_by),
            ("Correlation ID", self.correlation_id),
        ):
            if not value.strip():
                raise OperationalRuleViolation(f"{label} cannot be empty.")
        if self.status not in _DECISIONS:
            raise OperationalRuleViolation(
                "A persisted review must be needs review, accepted, or rejected."
            )
        if not is_aware_datetime(self.decided_at):
            raise OperationalRuleViolation(
                "Review decision time must include timezone information."
            )
        if self.validation_id is not None and not self.validation_id.strip():
            raise OperationalRuleViolation(
                "Validation ID cannot be blank when provided."
            )
        if self.reviewer_notes is not None and not self.reviewer_notes.strip():
            raise OperationalRuleViolation(
                "Reviewer notes cannot be blank when provided."
            )
        if self.status in {
            SubmissionReviewStatus.REJECTED,
            SubmissionReviewStatus.NEEDS_REVIEW,
        } and self.reviewer_notes is None:
            raise OperationalRuleViolation(
                "Reviewer notes are required for rejected or needs-review decisions."
            )


def validate_review_transition(
    previous: SubmissionReviewDecision | None,
    replacement_status: SubmissionReviewStatus,
) -> None:
    """Enforce terminal acceptance/rejection and explicit pending decisions."""

    if replacement_status not in _DECISIONS:
        raise OperationalRuleViolation(
            "Review decision must be needs review, accepted, or rejected."
        )
    if previous is None:
        return
    if previous.status in {
        SubmissionReviewStatus.ACCEPTED,
        SubmissionReviewStatus.REJECTED,
    }:
        raise OperationalRuleViolation(
            f"A {previous.status.value} submission review is final."
        )
