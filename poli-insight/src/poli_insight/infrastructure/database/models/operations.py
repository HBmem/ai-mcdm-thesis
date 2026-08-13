"""SQLAlchemy rows for auditable operational review and imports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
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


class ParticipantSubmissionImportBatchRow(Base):
    __tablename__ = "participant_submission_import_batches"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "file_hash", "plan_hash",
            name="uq_participant_submission_import_batch_plan",
        ),
        CheckConstraint(
            "length(file_hash) = 64 AND file_hash = lower(file_hash) "
            "AND length(plan_hash) = 64 AND plan_hash = lower(plan_hash)",
            name="ck_participant_submission_import_batch_hashes",
        ),
        CheckConstraint(
            "row_count >= 0 AND created_participant_count >= 0 "
            "AND enrolled_count >= 0 AND draft_count >= 0 "
            "AND submitted_count >= 0 AND skipped_count >= 0 "
            "AND replaced_count >= 0 AND identity_count >= 0",
            name="ck_participant_submission_import_batch_counts",
        ),
        Index(
            "ix_participant_submission_import_batch_session_time",
            "session_id", "imported_at",
        ),
    )

    batch_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("scenario_snapshots.scenario_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "session_configuration_versions.configuration_version_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_participant_count: Mapped[int] = mapped_column(Integer, nullable=False)
    enrolled_count: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_count: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False)
    replaced_count: Mapped[int] = mapped_column(Integer, nullable=False)
    identity_count: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle_override: Mapped[bool] = mapped_column(Boolean, nullable=False)
    resubmission_override: Mapped[bool] = mapped_column(Boolean, nullable=False)
    identity_attested: Mapped[bool] = mapped_column(Boolean, nullable=False)
    terminal_status: Mapped[str] = mapped_column(String(30), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    imported_by: Mapped[str] = mapped_column(String(100), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)


class ParticipantImportReferenceRow(Base):
    __tablename__ = "participant_import_references"
    __table_args__ = (
        UniqueConstraint(
            "reference_digest",
            name="uq_participant_import_reference_digest",
        ),
        UniqueConstraint(
            "participant_id",
            name="uq_participant_import_reference_participant",
        ),
        CheckConstraint(
            "length(reference_digest) = 64 "
            "AND reference_digest = lower(reference_digest)",
            name="ck_participant_import_reference_digest",
        ),
        Index("ix_participant_import_reference_participant", "participant_id"),
    )

    reference_mapping_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participants.participant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    reference_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    first_batch_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("participant_submission_import_batches.batch_id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ParticipantSubmissionImportRecordRow(Base):
    __tablename__ = "participant_submission_import_records"
    __table_args__ = (
        CheckConstraint("source_row_number >= 2", name="ck_participant_submission_import_row"),
        CheckConstraint(
            "record_state IN ('enrolled', 'draft', 'submitted')",
            name="ck_participant_submission_import_state",
        ),
        Index("ix_participant_submission_import_record_batch", "batch_id"),
    )

    import_record_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participant_submission_import_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    reference_mapping_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participant_import_references.reference_mapping_id", ondelete="RESTRICT"), nullable=False
    )
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participants.participant_id", ondelete="RESTRICT"), nullable=False
    )
    submission_id: Mapped[UUID | None] = mapped_column(
        UUIDString(), ForeignKey("submissions.submission_id", ondelete="RESTRICT"), nullable=True
    )
    predecessor_submission_id: Mapped[UUID | None] = mapped_column(
        UUIDString(), ForeignKey("submissions.submission_id", ondelete="RESTRICT"), nullable=True
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    record_state: Mapped[str] = mapped_column(String(20), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class AdminImportConsentDispositionRow(Base):
    __tablename__ = "admin_import_consent_dispositions"
    __table_args__ = (
        CheckConstraint(
            "reason_code = 'not_applicable_admin_import'",
            name="ck_admin_import_consent_reason",
        ),
        Index("ix_admin_import_consent_participant", "participant_id"),
    )

    disposition_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participants.participant_id", ondelete="RESTRICT"), nullable=False
    )
    submission_id: Mapped[UUID | None] = mapped_column(
        UUIDString(), ForeignKey("submissions.submission_id", ondelete="RESTRICT"), nullable=True
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("session_configuration_versions.configuration_version_id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participant_submission_import_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    administrator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)


class ImportedIdentityAuthorityRow(Base):
    __tablename__ = "imported_identity_authorities"
    __table_args__ = (
        CheckConstraint(
            "retention_until > attested_at",
            name="ck_imported_identity_authority_retention",
        ),
        Index("ix_imported_identity_authority_retention", "retention_until"),
    )

    authority_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participants.participant_id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participant_submission_import_batches.batch_id", ondelete="RESTRICT"), nullable=False
    )
    administrator_id: Mapped[str] = mapped_column(String(100), nullable=False)
    processing_basis: Mapped[str] = mapped_column(Text, nullable=False)
    attested_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    retention_until: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
