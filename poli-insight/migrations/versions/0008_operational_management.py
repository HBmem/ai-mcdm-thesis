"""Add auditable operational review and invitation import records.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "submission_review_decisions",
        sa.Column("decision_id", UUIDString(), nullable=False),
        sa.Column("submission_id", UUIDString(), nullable=False),
        sa.Column("validation_id", UUIDString(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column("decided_at", UTCDateTime(), nullable=False),
        sa.Column("decided_by", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "status IN ('needs_review', 'accepted', 'rejected')",
            name="ck_submission_review_decisions_status_allowed",
        ),
        sa.CheckConstraint(
            "status = 'accepted' OR reviewer_notes IS NOT NULL",
            name="ck_submission_review_decisions_notes_required",
        ),
        sa.ForeignKeyConstraint(
            ["submission_id"], ["submissions.submission_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["validation_id"],
            ["submission_validations.validation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("decision_id"),
    )
    op.create_index(
        "ix_submission_review_decisions_submission_time",
        "submission_review_decisions",
        ["submission_id", "decided_at"],
    )
    op.create_index(
        "ix_submission_review_decisions_status",
        "submission_review_decisions",
        ["status"],
    )

    op.create_table(
        "invitation_import_batches",
        sa.Column("batch_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("applied_at", UTCDateTime(), nullable=False),
        sa.Column("applied_by", sa.String(length=100), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=False),
        sa.CheckConstraint(
            "length(file_hash) = 64 AND file_hash = lower(file_hash)",
            name="ck_invitation_import_batches_file_hash",
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND imported_count >= 0 "
            "AND duplicate_count >= 0 AND invalid_count >= 0",
            name="ck_invitation_import_batches_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("batch_id"),
        sa.UniqueConstraint(
            "session_id",
            "file_hash",
            name="uq_invitation_import_batches_session_file",
        ),
    )
    op.create_index(
        "ix_invitation_import_batches_session_time",
        "invitation_import_batches",
        ["session_id", "applied_at"],
    )

    op.create_table(
        "invitation_import_records",
        sa.Column("record_id", UUIDString(), nullable=False),
        sa.Column("batch_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("invitation_id", UUIDString(), nullable=False),
        sa.Column("reference_hash", sa.String(length=64), nullable=False),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(reference_hash) = 64 AND reference_hash = lower(reference_hash)",
            name="ck_invitation_import_records_reference_hash",
        ),
        sa.CheckConstraint(
            "length(row_hash) = 64 AND row_hash = lower(row_hash)",
            name="ck_invitation_import_records_row_hash",
        ),
        sa.CheckConstraint(
            "source_row_number >= 2",
            name="ck_invitation_import_records_row_number",
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["invitation_import_batches.batch_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["session_invitations.invitation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("record_id"),
        sa.UniqueConstraint(
            "session_id",
            "reference_hash",
            name="uq_invitation_import_records_session_reference",
        ),
    )
    op.create_index(
        "ix_invitation_import_records_batch",
        "invitation_import_records",
        ["batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_invitation_import_records_batch",
        table_name="invitation_import_records",
    )
    op.drop_table("invitation_import_records")
    op.drop_index(
        "ix_invitation_import_batches_session_time",
        table_name="invitation_import_batches",
    )
    op.drop_table("invitation_import_batches")
    op.drop_index(
        "ix_submission_review_decisions_status",
        table_name="submission_review_decisions",
    )
    op.drop_index(
        "ix_submission_review_decisions_submission_time",
        table_name="submission_review_decisions",
    )
    op.drop_table("submission_review_decisions")
