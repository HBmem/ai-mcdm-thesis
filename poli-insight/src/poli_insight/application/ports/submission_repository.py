"""Persistence port for submission aggregates and attempt sequencing.

Answers are children of :class:`~poli_insight.domain.submission.Submission`.
Application services load and persist the complete aggregate; this port does
not expose answer-row CRUD or transaction control.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from poli_insight.domain.enum import SubmissionStatus
from poli_insight.domain.submission import Submission


@dataclass(frozen=True, slots=True)
class SubmissionAttemptPlan:
    """Locked state used to create or resume one participant attempt.

    When ``draft`` is present, it is the attempt the caller must resume and
    ``next_attempt_number`` is ``None``. Otherwise, ``next_attempt_number`` is
    reserved by the repository lock until the surrounding unit of work ends,
    and ``previous_submission`` is the immediately preceding attempt, if any.
    """

    participant_id: str
    configuration_version_id: str
    draft: Submission | None
    next_attempt_number: int | None
    previous_submission: Submission | None

    def __post_init__(self) -> None:
        if not self.participant_id.strip():
            raise ValueError("participant_id cannot be empty.")
        if not self.configuration_version_id.strip():
            raise ValueError("configuration_version_id cannot be empty.")

        if self.draft is not None:
            if self.next_attempt_number is not None:
                raise ValueError(
                    "An existing draft cannot also allocate a next attempt."
                )
            if self.draft.status != SubmissionStatus.DRAFT:
                raise ValueError("draft must have draft submission status.")
            self._validate_submission_scope(self.draft, "draft")
            if self.previous_submission is None:
                if self.draft.previous_submission_id is not None:
                    raise ValueError(
                        "Later draft attempts require their previous submission."
                    )
            elif self.draft.previous_submission_id is None:
                raise ValueError(
                    "A first draft cannot have a previous submission."
                )
            else:
                self._validate_submission_scope(
                    self.previous_submission,
                    "previous submission",
                )
                if self.previous_submission.status == SubmissionStatus.DRAFT:
                    raise ValueError(
                        "A draft predecessor cannot precede another draft."
                    )
                self.draft.validate_predecessor(self.previous_submission)
            return

        if self.next_attempt_number is None:
            raise ValueError(
                "A plan without a draft requires next_attempt_number."
            )
        if (
            isinstance(self.next_attempt_number, bool)
            or not isinstance(self.next_attempt_number, int)
            or self.next_attempt_number < 1
        ):
            raise ValueError("next_attempt_number must be a positive integer.")

        if self.previous_submission is None:
            if self.next_attempt_number != 1:
                raise ValueError(
                    "The first attempt must use attempt number one."
                )
            return

        self._validate_submission_scope(
            self.previous_submission,
            "previous submission",
        )
        if self.previous_submission.status == SubmissionStatus.DRAFT:
            raise ValueError(
                "The previous submission must be a finalized attempt."
            )
        if (
            self.next_attempt_number
            != self.previous_submission.attempt_number + 1
        ):
            raise ValueError(
                "Next attempt number must immediately follow the previous "
                "submission."
            )

    @property
    def should_resume_draft(self) -> bool:
        return self.draft is not None

    def _validate_submission_scope(
        self,
        submission: Submission,
        label: str,
    ) -> None:
        if submission.participant_id != self.participant_id:
            raise ValueError(f"{label} belongs to a different participant.")
        if (
            submission.configuration_version_id
            != self.configuration_version_id
        ):
            raise ValueError(
                f"{label} belongs to a different configuration version."
            )


class SubmissionRepository(Protocol):
    """Persistence operations for submissions and their answer children."""

    def add(self, submission: Submission) -> None:
        """Add a new submission aggregate to the current transaction.

        The implementation persists the submission and every answer in the
        aggregate. It must not commit internally.
        """
        ...

    def get(self, submission_id: str) -> Submission | None:
        """Load one complete submission aggregate by identity."""
        ...

    def get_for_update(self, submission_id: str) -> Submission | None:
        """Load and lock an aggregate for finalization or lifecycle changes."""
        ...

    def get_draft(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> Submission | None:
        """Load the participant's draft for the configuration, if one exists."""
        ...

    def get_effective_submission(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> Submission | None:
        """Load the current submitted, nonwithdrawn, nonsuperseded attempt."""
        ...

    def list_attempt_history(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> Sequence[Submission]:
        """Load all attempts in ascending attempt-number order."""
        ...

    def list_effective_for_configuration(
        self,
        configuration_version_id: str,
    ) -> Sequence[Submission]:
        """Load every current submitted attempt for one configuration."""
        ...

    def lock_attempt_plan(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> SubmissionAttemptPlan:
        """Lock and inspect the participant's attempt namespace.

        The implementation must acquire a transaction-scoped lock on a stable
        parent row, normally the participant, before inspecting drafts or the
        maximum attempt number. PostgreSQL implementations should use
        ``SELECT ... FOR UPDATE`` on that parent row. SQLite implementations
        must serialize this operation through their write transaction.

        The caller must either resume the returned draft or add a submission
        using the returned attempt number before ending the same unit of work.
        A database unique constraint on ``(participant_id, attempt_number)``
        remains the final race-safety backstop.
        """
        ...

    def save(self, submission: Submission) -> None:
        """Persist replacement aggregate state and synchronize its answers.

        Implementations may insert, update, or remove answer rows only to match
        the supplied draft aggregate. Finalized answer rows must never be
        rewritten or deleted. This method must not commit internally.
        """
        ...
