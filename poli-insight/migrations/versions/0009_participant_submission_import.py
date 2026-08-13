"""Add secure participant/submission import provenance.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "participant_submission_import_batches",
        sa.Column("batch_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("scenario_snapshot_id", UUIDString(), nullable=False),
        sa.Column("configuration_version_id", UUIDString(), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=False),
        sa.Column("plan_hash", sa.String(64), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_participant_count", sa.Integer(), nullable=False),
        sa.Column("enrolled_count", sa.Integer(), nullable=False),
        sa.Column("draft_count", sa.Integer(), nullable=False),
        sa.Column("submitted_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("replaced_count", sa.Integer(), nullable=False),
        sa.Column("identity_count", sa.Integer(), nullable=False),
        sa.Column("lifecycle_override", sa.Boolean(), nullable=False),
        sa.Column("resubmission_override", sa.Boolean(), nullable=False),
        sa.Column("identity_attested", sa.Boolean(), nullable=False),
        sa.Column("terminal_status", sa.String(30), nullable=False),
        sa.Column("imported_at", UTCDateTime(), nullable=False),
        sa.Column("imported_by", sa.String(100), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.CheckConstraint(
            "length(file_hash) = 64 AND file_hash = lower(file_hash) "
            "AND length(plan_hash) = 64 AND plan_hash = lower(plan_hash)",
            name="ck_participant_submission_import_batch_hashes",
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND created_participant_count >= 0 "
            "AND enrolled_count >= 0 AND draft_count >= 0 "
            "AND submitted_count >= 0 AND skipped_count >= 0 "
            "AND replaced_count >= 0 AND identity_count >= 0",
            name="ck_participant_submission_import_batch_counts",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["scenario_snapshot_id"], ["scenario_snapshots.scenario_snapshot_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["configuration_version_id"], ["session_configuration_versions.configuration_version_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("batch_id"),
        sa.UniqueConstraint("session_id", "file_hash", "plan_hash", name="uq_participant_submission_import_batch_plan"),
    )
    op.create_index(
        "ix_participant_submission_import_batch_session_time",
        "participant_submission_import_batches", ["session_id", "imported_at"],
    )
    op.create_table(
        "participant_import_references",
        sa.Column("reference_mapping_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("reference_digest", sa.String(64), nullable=False),
        sa.Column("first_batch_id", UUIDString(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "length(reference_digest) = 64 AND reference_digest = lower(reference_digest)",
            name="ck_participant_import_reference_digest",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["first_batch_id"], ["participant_submission_import_batches.batch_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("reference_mapping_id"),
        sa.UniqueConstraint("reference_digest", name="uq_participant_import_reference_digest"),
        sa.UniqueConstraint("participant_id", name="uq_participant_import_reference_participant"),
    )
    op.create_index("ix_participant_import_reference_participant", "participant_import_references", ["participant_id"])
    op.create_table(
        "participant_submission_import_records",
        sa.Column("import_record_id", UUIDString(), nullable=False),
        sa.Column("batch_id", UUIDString(), nullable=False),
        sa.Column("reference_mapping_id", UUIDString(), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("submission_id", UUIDString(), nullable=True),
        sa.Column("predecessor_submission_id", UUIDString(), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("record_state", sa.String(20), nullable=False),
        sa.Column("recorded_at", UTCDateTime(), nullable=False),
        sa.Column("imported_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("source_row_number >= 2", name="ck_participant_submission_import_row"),
        sa.CheckConstraint("record_state IN ('enrolled', 'draft', 'submitted')", name="ck_participant_submission_import_state"),
        sa.ForeignKeyConstraint(["batch_id"], ["participant_submission_import_batches.batch_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reference_mapping_id"], ["participant_import_references.reference_mapping_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.submission_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["predecessor_submission_id"], ["submissions.submission_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("import_record_id"),
    )
    op.create_index("ix_participant_submission_import_record_batch", "participant_submission_import_records", ["batch_id"])
    op.create_table(
        "admin_import_consent_dispositions",
        sa.Column("disposition_id", UUIDString(), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("submission_id", UUIDString(), nullable=True),
        sa.Column("configuration_version_id", UUIDString(), nullable=False),
        sa.Column("batch_id", UUIDString(), nullable=False),
        sa.Column("administrator_id", sa.String(100), nullable=False),
        sa.Column("reason_code", sa.String(50), nullable=False),
        sa.Column("recorded_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint("reason_code = 'not_applicable_admin_import'", name="ck_admin_import_consent_reason"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.submission_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["configuration_version_id"], ["session_configuration_versions.configuration_version_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["participant_submission_import_batches.batch_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("disposition_id"),
    )
    op.create_index("ix_admin_import_consent_participant", "admin_import_consent_dispositions", ["participant_id"])
    op.create_table(
        "imported_identity_authorities",
        sa.Column("authority_id", UUIDString(), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("batch_id", UUIDString(), nullable=False),
        sa.Column("administrator_id", sa.String(100), nullable=False),
        sa.Column("processing_basis", sa.Text(), nullable=False),
        sa.Column("attested_at", UTCDateTime(), nullable=False),
        sa.Column("retention_until", UTCDateTime(), nullable=False),
        sa.CheckConstraint("retention_until > attested_at", name="ck_imported_identity_authority_retention"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["participant_submission_import_batches.batch_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("authority_id"),
    )
    op.create_index("ix_imported_identity_authority_retention", "imported_identity_authorities", ["retention_until"])


def downgrade() -> None:
    op.drop_index("ix_imported_identity_authority_retention", table_name="imported_identity_authorities")
    op.drop_table("imported_identity_authorities")
    op.drop_index("ix_admin_import_consent_participant", table_name="admin_import_consent_dispositions")
    op.drop_table("admin_import_consent_dispositions")
    op.drop_index("ix_participant_submission_import_record_batch", table_name="participant_submission_import_records")
    op.drop_table("participant_submission_import_records")
    op.drop_index("ix_participant_import_reference_participant", table_name="participant_import_references")
    op.drop_table("participant_import_references")
    op.drop_index("ix_participant_submission_import_batch_session_time", table_name="participant_submission_import_batches")
    op.drop_table("participant_submission_import_batches")
