"""SQLAlchemy rows for auditable operational review and imports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


class SubmissionReviewDecisionRow(Base):
    """One immutable human review decision for a submission."""

    __tablename__ = "submission_review_decisions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('needs_review', 'accepted', 'rejected')",
            name="ck_submission_review_decisions_status_allowed",
        ),
        CheckConstraint(
            "status = 'accepted' OR reviewer_notes IS NOT NULL",
            name="ck_submission_review_decisions_notes_required",
        ),
        Index(
            "ix_submission_review_decisions_submission_time",
            "submission_id",
            "decided_at",
        ),
        Index("ix_submission_review_decisions_status", "status"),
    )

    decision_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    submission_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("submissions.submission_id", ondelete="RESTRICT"),
        nullable=False,
    )
    validation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey("submission_validations.validation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)


class InvitationImportBatchRow(Base):
    """One applied invitation CSV, identified by its exact content hash."""

    __tablename__ = "invitation_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "file_hash",
            name="uq_invitation_import_batches_session_file",
        ),
        CheckConstraint(
            "length(file_hash) = 64 AND file_hash = lower(file_hash)",
            name="ck_invitation_import_batches_file_hash",
        ),
        CheckConstraint(
            "row_count >= 0 AND imported_count >= 0 "
            "AND duplicate_count >= 0 AND invalid_count >= 0",
            name="ck_invitation_import_batches_counts_nonnegative",
        ),
        Index(
            "ix_invitation_import_batches_session_time",
            "session_id",
            "applied_at",
        ),
    )

    batch_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    invalid_count: Mapped[int] = mapped_column(Integer, nullable=False)
    applied_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    applied_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)


class InvitationImportRecordRow(Base):
    """A hashed source reference mapped to its created invitation."""

    __tablename__ = "invitation_import_records"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "reference_hash",
            name="uq_invitation_import_records_session_reference",
        ),
        CheckConstraint(
            "length(reference_hash) = 64 AND reference_hash = lower(reference_hash)",
            name="ck_invitation_import_records_reference_hash",
        ),
        CheckConstraint(
            "length(row_hash) = 64 AND row_hash = lower(row_hash)",
            name="ck_invitation_import_records_row_hash",
        ),
        CheckConstraint(
            "source_row_number >= 2",
            name="ck_invitation_import_records_row_number",
        ),
        Index("ix_invitation_import_records_batch", "batch_id"),
    )

    record_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("invitation_import_batches.batch_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    invitation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("session_invitations.invitation_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reference_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
