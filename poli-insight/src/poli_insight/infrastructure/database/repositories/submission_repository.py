"""SQLAlchemy repository for submission aggregates and attempt sequencing.

Submission answers are always loaded and persisted through their owning
submission. Comments have an independent lifecycle and are deliberately not
loaded or modified here. The caller owns the transaction; this repository may
flush changes but never commits or rolls back.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Load, Session as DatabaseSession, selectinload

from poli_insight.application.ports.submission_repository import (
    SubmissionAttemptPlan,
)
from poli_insight.domain.enum import SubmissionStatus
from poli_insight.domain.submission import Submission
from poli_insight.infrastructure.database.mappers.submission import (
    apply_submission_aggregate,
    submission_to_domain,
    submission_to_row,
)
from poli_insight.infrastructure.database.models.participation import (
    ParticipantRow,
)
from poli_insight.infrastructure.database.models.submission import (
    SubmissionRow,
)


class SubmissionNotFoundError(LookupError):
    """Raised when a submission requested for persistence does not exist."""


class SubmissionAttemptOwnerNotFoundError(LookupError):
    """Raised when an attempt namespace has no matching participant."""


class InvalidSubmissionAttemptHistoryError(RuntimeError):
    """Raised when persisted attempt lineage is internally inconsistent."""


def _submission_load_options() -> tuple[Load, ...]:
    """Load answer children without exposing unrelated comment rows."""

    return (selectinload(SubmissionRow.answers),)


class SqlAlchemySubmissionRepository:
    """Persist complete submissions and allocate attempts race-safely."""

    def __init__(self, database_session: DatabaseSession) -> None:
        self._database_session = database_session

    def add(self, submission: Submission) -> None:
        """Add a new submission and its answers without committing."""

        self._database_session.add(submission_to_row(submission))

    def get(self, submission_id: str) -> Submission | None:
        """Load a complete submission without taking a row lock."""

        row = self._load_by_id(submission_id, for_update=False)
        return None if row is None else submission_to_domain(row)

    def get_for_update(self, submission_id: str) -> Submission | None:
        """Load and lock a submission for an aggregate lifecycle change."""

        row = self._load_by_id(submission_id, for_update=True)
        return None if row is None else submission_to_domain(row)

    def get_draft(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> Submission | None:
        """Load the participant's draft in the requested configuration."""

        statement = (
            select(SubmissionRow)
            .options(*_submission_load_options())
            .where(
                SubmissionRow.participant_id == participant_id,
                SubmissionRow.configuration_version_id
                == configuration_version_id,
                SubmissionRow.status == SubmissionStatus.DRAFT.value,
            )
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else submission_to_domain(row)

    def get_effective_submission(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> Submission | None:
        """Load the current submitted, nonsuperseded, nonwithdrawn attempt."""

        statement = (
            select(SubmissionRow)
            .options(*_submission_load_options())
            .where(
                SubmissionRow.participant_id == participant_id,
                SubmissionRow.configuration_version_id
                == configuration_version_id,
                SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
            )
        )
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else submission_to_domain(row)

    def list_attempt_history(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> tuple[Submission, ...]:
        """Load all attempts in deterministic ascending attempt order."""

        rows = self._load_attempt_rows(
            participant_id,
            configuration_version_id,
        )
        self._validate_attempt_rows(rows)
        return tuple(submission_to_domain(row) for row in rows)

    def lock_attempt_plan(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> SubmissionAttemptPlan:
        """Lock the participant namespace and plan a draft or next attempt."""

        self._lock_attempt_owner(
            participant_id,
            configuration_version_id,
        )
        rows = self._load_attempt_rows(
            participant_id,
            configuration_version_id,
        )
        self._validate_attempt_rows(rows)
        attempts = tuple(submission_to_domain(row) for row in rows)

        draft = next(
            (
                submission
                for submission in attempts
                if submission.status == SubmissionStatus.DRAFT
            ),
            None,
        )
        if draft is not None:
            previous_submission = (
                attempts[-2] if len(attempts) > 1 else None
            )
            return SubmissionAttemptPlan(
                participant_id=participant_id,
                configuration_version_id=configuration_version_id,
                draft=draft,
                next_attempt_number=None,
                previous_submission=previous_submission,
            )

        previous_submission = attempts[-1] if attempts else None
        return SubmissionAttemptPlan(
            participant_id=participant_id,
            configuration_version_id=configuration_version_id,
            draft=None,
            next_attempt_number=(
                1
                if previous_submission is None
                else previous_submission.attempt_number + 1
            ),
            previous_submission=previous_submission,
        )

    def save(self, submission: Submission) -> None:
        """Synchronize a submission aggregate without committing."""

        row = self._load_by_id(submission.submission_id, for_update=True)
        if row is None:
            raise SubmissionNotFoundError(
                f"Submission {submission.submission_id!r} does not exist."
            )

        removed_answers = apply_submission_aggregate(row, submission)
        for answer_row in removed_answers:
            self._database_session.delete(answer_row)
        self._database_session.flush()

    def _load_by_id(
        self,
        submission_id: str,
        *,
        for_update: bool,
    ) -> SubmissionRow | None:
        statement = (
            select(SubmissionRow)
            .options(*_submission_load_options())
            .where(SubmissionRow.submission_id == submission_id)
        )
        if for_update and self._uses_postgresql():
            statement = statement.with_for_update()
        return self._database_session.execute(statement).scalar_one_or_none()

    def _load_attempt_rows(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> tuple[SubmissionRow, ...]:
        statement = (
            select(SubmissionRow)
            .options(*_submission_load_options())
            .where(
                SubmissionRow.participant_id == participant_id,
                SubmissionRow.configuration_version_id
                == configuration_version_id,
            )
            .order_by(
                SubmissionRow.attempt_number,
                SubmissionRow.submission_id,
            )
        )
        return tuple(self._database_session.scalars(statement).all())

    def _lock_attempt_owner(
        self,
        participant_id: str,
        configuration_version_id: str,
    ) -> None:
        if self._uses_sqlite():
            # SQLite has no row-level FOR UPDATE. A no-op update acquires its
            # write reservation before attempt state is inspected, serializing
            # competing planners until the surrounding transaction ends.
            statement = (
                update(ParticipantRow)
                .where(
                    ParticipantRow.participant_id == participant_id,
                    ParticipantRow.configuration_version_id
                    == configuration_version_id,
                )
                .values(participant_id=ParticipantRow.participant_id)
            )
            result = self._database_session.execute(statement)
            owner_exists = result.rowcount == 1
        else:
            statement = select(ParticipantRow.participant_id).where(
                ParticipantRow.participant_id == participant_id,
                ParticipantRow.configuration_version_id
                == configuration_version_id,
            )
            if self._uses_postgresql():
                statement = statement.with_for_update()
            owner_exists = (
                self._database_session.execute(statement).scalar_one_or_none()
                is not None
            )

        if not owner_exists:
            raise SubmissionAttemptOwnerNotFoundError(
                "No participant is pinned to submission attempt scope "
                f"({participant_id!r}, {configuration_version_id!r})."
            )

    @staticmethod
    def _validate_attempt_rows(rows: tuple[SubmissionRow, ...]) -> None:
        draft_count = sum(
            row.status == SubmissionStatus.DRAFT.value for row in rows
        )
        submitted_count = sum(
            row.status == SubmissionStatus.SUBMITTED.value for row in rows
        )
        if draft_count > 1:
            raise InvalidSubmissionAttemptHistoryError(
                "Persisted attempt history contains more than one draft."
            )
        if submitted_count > 1:
            raise InvalidSubmissionAttemptHistoryError(
                "Persisted attempt history contains more than one effective "
                "submission."
            )

        previous_row: SubmissionRow | None = None
        for expected_number, row in enumerate(rows, start=1):
            if row.attempt_number != expected_number:
                raise InvalidSubmissionAttemptHistoryError(
                    "Persisted submission attempts must be contiguous and "
                    "start at one."
                )
            expected_previous_id = (
                None
                if previous_row is None
                else str(previous_row.submission_id)
            )
            actual_previous_id = (
                None
                if row.previous_submission_id is None
                else str(row.previous_submission_id)
            )
            if actual_previous_id != expected_previous_id:
                raise InvalidSubmissionAttemptHistoryError(
                    "Persisted submission predecessor chain is inconsistent."
                )
            if (
                row.status == SubmissionStatus.DRAFT.value
                and expected_number != len(rows)
            ):
                raise InvalidSubmissionAttemptHistoryError(
                    "Only the latest submission attempt may remain a draft."
                )
            previous_row = row

    def _uses_postgresql(self) -> bool:
        bind = self._database_session.get_bind()
        return bind.dialect.name == "postgresql"

    def _uses_sqlite(self) -> bool:
        bind = self._database_session.get_bind()
        return bind.dialect.name == "sqlite"
