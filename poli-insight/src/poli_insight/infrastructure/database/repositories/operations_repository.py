"""SQLAlchemy repositories for operational review and invitation imports."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from poli_insight.application.ports.operations_repository import (
    InvitationImportBatch,
    InvitationImportRecord,
)
from poli_insight.domain.enum import SubmissionReviewStatus
from poli_insight.domain.operations import SubmissionReviewDecision
from poli_insight.infrastructure.database.models.operations import (
    InvitationImportBatchRow,
    InvitationImportRecordRow,
    SubmissionReviewDecisionRow,
)


class SqlAlchemySubmissionReviewRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def get_latest(
        self,
        submission_id: str,
        *,
        for_update: bool = False,
    ) -> SubmissionReviewDecision | None:
        statement = (
            select(SubmissionReviewDecisionRow)
            .where(SubmissionReviewDecisionRow.submission_id == submission_id)
            .order_by(
                SubmissionReviewDecisionRow.decided_at.desc(),
                SubmissionReviewDecisionRow.decision_id.desc(),
            )
            .limit(1)
        )
        if (
            for_update
            and self._database_session.bind is not None
            and self._database_session.bind.dialect.name == "postgresql"
        ):
            statement = statement.with_for_update()
        row = self._database_session.scalar(statement)
        return None if row is None else _decision_to_domain(row)

    def add(self, decision: SubmissionReviewDecision) -> None:
        self._database_session.add(
            SubmissionReviewDecisionRow(
                decision_id=decision.decision_id,
                submission_id=decision.submission_id,
                validation_id=decision.validation_id,
                status=decision.status.value,
                reviewer_notes=decision.reviewer_notes,
                decided_at=decision.decided_at,
                decided_by=decision.decided_by,
                correlation_id=decision.correlation_id,
            )
        )


class SqlAlchemyInvitationImportRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def get_batch_by_file_hash(
        self,
        session_id: str,
        file_hash: str,
    ) -> InvitationImportBatch | None:
        row = self._database_session.scalar(
            select(InvitationImportBatchRow).where(
                InvitationImportBatchRow.session_id == session_id,
                InvitationImportBatchRow.file_hash == file_hash,
            )
        )
        return None if row is None else _batch_to_domain(row)

    def existing_reference_hashes(
        self,
        session_id: str,
        reference_hashes: tuple[str, ...],
    ) -> frozenset[str]:
        if not reference_hashes:
            return frozenset()
        statement = select(InvitationImportRecordRow.reference_hash).where(
            InvitationImportRecordRow.session_id == session_id,
            InvitationImportRecordRow.reference_hash.in_(reference_hashes),
        )
        return frozenset(self._database_session.scalars(statement))

    def add_batch(self, batch: InvitationImportBatch) -> None:
        self._database_session.add(
            InvitationImportBatchRow(
                batch_id=batch.batch_id,
                session_id=batch.session_id,
                file_hash=batch.file_hash,
                filename=batch.filename,
                row_count=batch.row_count,
                imported_count=batch.imported_count,
                duplicate_count=batch.duplicate_count,
                invalid_count=batch.invalid_count,
                applied_at=batch.applied_at,
                applied_by=batch.applied_by,
                correlation_id=batch.correlation_id,
            )
        )

    def add_record(self, record: InvitationImportRecord) -> None:
        # The record references a batch and invitation that are commonly added
        # in this same transaction. Flush those parents explicitly because no
        # ORM relationships are needed at this application boundary.
        self._database_session.flush()
        self._database_session.add(
            InvitationImportRecordRow(
                record_id=record.record_id,
                batch_id=record.batch_id,
                session_id=record.session_id,
                invitation_id=record.invitation_id,
                reference_hash=record.reference_hash,
                row_hash=record.row_hash,
                source_row_number=record.source_row_number,
            )
        )


def _decision_to_domain(row: SubmissionReviewDecisionRow) -> SubmissionReviewDecision:
    return SubmissionReviewDecision(
        decision_id=str(row.decision_id),
        submission_id=str(row.submission_id),
        validation_id=None if row.validation_id is None else str(row.validation_id),
        status=SubmissionReviewStatus(row.status),
        reviewer_notes=row.reviewer_notes,
        decided_at=row.decided_at,
        decided_by=row.decided_by,
        correlation_id=row.correlation_id,
    )


def _batch_to_domain(row: InvitationImportBatchRow) -> InvitationImportBatch:
    return InvitationImportBatch(
        batch_id=str(row.batch_id),
        session_id=str(row.session_id),
        file_hash=row.file_hash,
        filename=row.filename,
        row_count=row.row_count,
        imported_count=row.imported_count,
        duplicate_count=row.duplicate_count,
        invalid_count=row.invalid_count,
        applied_at=row.applied_at,
        applied_by=row.applied_by,
        correlation_id=row.correlation_id,
    )
