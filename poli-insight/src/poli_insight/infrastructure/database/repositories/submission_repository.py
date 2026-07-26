from __future__ import annotations

import json

from collections.abc import Sequence
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from poli_insight.application.utils import _as_utc
from poli_insight.domain.enums import SubmissionStatus
from poli_insight.domain.submissions import Submission
from poli_insight.infrastructure.database.orm_models import SubmissionRow

class SQLAlchemySubmissionRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(
        self,
        submission: Submission,
    ) -> None:
        self._database_session.add(
            SubmissionRow(
                submission_id=submission.submission_id,
                participant_id=submission.participant_id,
                attempt_number=submission.attempt_number,
                previous_submission_id=submission.previous_submission_id,
                status=submission.status.value,
                answers_json=json.dumps(
                    submission.answers,
                    sort_keys=True,
                    separators=(",",":"),
                    ensure_ascii=False,
                    allow_nan=False
                ),
                started_at=submission.started_at,
                last_saved_at=submission.last_saved_at,
                submitted_at=submission.submitted_at,
                submitted_by=submission.submitted_by,
                superseded_at=submission.superseded_at,
                withdrawn_at=submission.withdrawn_at,
                withdrawn_by=submission.withdrawn_by,
                created_at=submission.created_at,
                created_by=submission.created_by,
                updated_at=submission.updated_at,
                updated_by=submission.updated_by,
            )
        )

    def get(
        self,
        submission_id: str,
    ) -> Submission | None:
        statement = (
            select(SubmissionRow)
            .where(
                SubmissionRow.submission_id == submission_id
            )
        )

        submission_row = (
            self._database_session.execute(statement)
            .scalar_one_or_none()
        )

        if submission_row is None:
            return None

        return self._to_domain(
            submission_row
        )

    def save(
        self,
        submission: Submission,
    ) -> None:
        row = self._database_session.get(
            SubmissionRow,
            submission.submission_id
        )

        if row is None:
            raise LookupError(
                f"Submission {submission.submission_id!r} does not exists."
            )

        row.status=submission.status.value
        row.answers_json=json.dumps(
            submission.answers,
            sort_keys=True,
            separators=(",",":"),
            ensure_ascii=False,
            allow_nan=False
        )

        row.started_at=submission.started_at
        row.last_saved_at=submission.last_saved_at
        row.submitted_at=submission.submitted_at
        row.submitted_by=submission.submitted_by
        row.superseded_at=submission.superseded_at
        row.withdrawn_at=submission.withdrawn_at
        row.withdrawn_by=submission.withdrawn_by
    
        row.updated_at=submission.updated_at
        row.updated_by=submission.updated_by

    def flush(
        self
    ) -> None:
        self.database_session.flush()

    # Should not be necessary since old submissions are saved but i worked on it for practice
    def delete(
        self,
        submission_id: str,
    ) -> bool:
        row = self._database_session.get(
            SubmissionRow,
            submission_id
        )

        if row is None:
            return False

        self._database_session.delete(row)
        return True

    def get_draft(
        self,
        participant_id: str,
    ) -> Submission | None:
        statement = (
            select(SubmissionRow)
            .where(
                SubmissionRow.participant_id == participant_id,
                SubmissionRow.status == SubmissionStatus.DRAFT.value,
            )
        )

        submission_row = (
            self._database_session.execute(statement)
            .scalar_one_or_none()
        )

        if submission_row is None:
            return None

        return self._to_domain(submission_row)
    
    def get_effective(
        self,
        participant_id: str,
    ) -> Submission | None:
        statement = (
            select(SubmissionRow)
            .where(
                SubmissionRow.participant_id == participant_id,
                SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
            )
        )

        submission_row = (
            self._database_session.execute(statement)
            .scalar_one_or_none()
        )

        if submission_row is None:
            return None

        return self._to_domain(submission_row)

    def next_attempt_number(
        self,
        participant_id: str,
    ) -> int:
        current_max = self._database_session.scalar(
            select(
                func.max(SubmissionRow.attempt_number)
            )
            .where(
                SubmissionRow.participant_id == participant_id
            )
        )

        return int(current_max or 0) + 1

    def list_current_for_participants(
        self,
        participant_ids: set[str],
    ) -> Sequence[Submission]:
        if not participant_ids:
            return ()

        statement = (
            select(SubmissionRow)
            .where(
                SubmissionRow.participant_id.in_(participant_ids),
                SubmissionRow.status.in_(
                    [
                        SubmissionStatus.DRAFT.value,
                        SubmissionStatus.SUBMITTED.value,
                    ]
                ),
            )
            .order_by(
                SubmissionRow.participant_id.asc(),
                SubmissionRow.attempt_number.desc()
            )
        )

        rows = self._database_session.scalars(
            statement
        ).all()

        return tuple(
            self._to_domain(row)
            for row in rows
        )
    
    @staticmethod
    def _to_domain(
        row: SubmissionRow,
    ) -> Submission:
        return Submission(
            submission_id=row.submission_id,
            participant_id=row.participant_id,
            attempt_number=row.attempt_number,
            previous_submission_id=row.previous_submission_id,
            status=SubmissionStatus(row.status),
            answers=json.loads(row.answers_json),
            started_at=_as_utc(row.started_at),
            last_saved_at=_as_utc(row.last_saved_at),
            submitted_at=_as_utc(row.submitted_at),
            submitted_by=row.submitted_by,
            superseded_at=_as_utc(row.superseded_at),
            withdrawn_at=_as_utc(row.withdrawn_at),
            withdrawn_by=row.withdrawn_by,
            created_at=_as_utc(row.created_at),
            created_by=row.created_by,
            updated_at=_as_utc(row.updated_at),
            updated_by=row.updated_by,
        )
