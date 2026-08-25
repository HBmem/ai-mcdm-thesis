"""submission validation matrices and versioned processing bundles

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("submission_validations") as batch_op:
        batch_op.add_column(
            sa.Column(
                "attempt_number",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.drop_constraint(
            "uq_submission_validations_input_identity", type_="unique"
        )
        batch_op.create_unique_constraint(
            "uq_submission_validations_input_attempt",
            ["input_hash", "attempt_number"],
        )
        batch_op.create_check_constraint(
            "ck_submission_validations_attempt_positive",
            "attempt_number >= 1",
        )
        batch_op.create_index(
            "uq_submission_validations_active_input",
            ["input_hash"],
            unique=True,
            sqlite_where=sa.text("status IN ('pending', 'running')"),
            postgresql_where=sa.text("status IN ('pending', 'running')"),
        )

    op.create_table(
        "validation_prepared_matrices",
        sa.Column("validation_id", UUIDString(), nullable=False),
        sa.Column("response_format", sa.String(50), nullable=False),
        sa.Column("value_shape", sa.String(50), nullable=False),
        sa.Column("criterion_ids_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("matrix_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("preparer_version", sa.String(100), nullable=False),
        sa.Column("matrix_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "response_format IN ('direct_rating', 'pairwise')",
            name="ck_validation_prepared_matrices_response_format",
        ),
        sa.CheckConstraint(
            "value_shape IN ('crisp', 'triangular_fuzzy')",
            name="ck_validation_prepared_matrices_value_shape",
        ),
        sa.CheckConstraint(
            "length(matrix_hash) = 64 AND matrix_hash = lower(matrix_hash)",
            name="ck_validation_prepared_matrices_hash_format",
        ),
        sa.ForeignKeyConstraint(
            ["validation_id"],
            ["submission_validations.validation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("validation_id"),
    )

    op.create_table(
        "processing_runs",
        sa.Column("processing_run_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("configuration_version_id", UUIDString(), nullable=False),
        sa.Column("scenario_snapshot_id", UUIDString(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("roster_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("environment_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("completed_at", UTCDateTime(), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.CheckConstraint("run_number >= 1", name="ck_processing_runs_number_positive"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled', 'awaiting_review', 'stale')",
            name="ck_processing_runs_status_allowed",
        ),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.session_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["session_configuration_versions.configuration_version_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["scenario_snapshot_id"],
            ["scenario_snapshots.scenario_snapshot_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("processing_run_id"),
        sa.UniqueConstraint("session_id", "run_number", name="uq_processing_runs_session_number"),
    )
    op.create_index("ix_processing_runs_session_status", "processing_runs", ["session_id", "status"])

    op.create_table(
        "processing_run_algorithms",
        sa.Column("processing_run_id", UUIDString(), nullable=False),
        sa.Column("algorithm_implementation_id", UUIDString(), nullable=False),
        sa.Column("parameter_json", sa.JSON(none_as_null=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["processing_run_id"], ["processing_runs.processing_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["algorithm_implementation_id"],
            ["algorithm_implementations.algorithm_implementation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("processing_run_id"),
    )

    op.create_table(
        "processing_run_submissions",
        sa.Column("processing_run_id", UUIDString(), nullable=False),
        sa.Column("submission_id", UUIDString(), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("stakeholder_group_id", UUIDString(), nullable=False),
        sa.Column("validation_id", UUIDString(), nullable=True),
        sa.Column("inclusion_status", sa.String(50), nullable=False),
        sa.Column("exclusion_reason", sa.String(200), nullable=True),
        sa.CheckConstraint(
            "inclusion_status IN ('pending_review', 'included', 'excluded_invalid', 'excluded_superseded', 'excluded_withdrawn', 'excluded_disabled', 'excluded_cutoff', 'excluded_moderator', 'excluded_error')",
            name="ck_processing_run_submissions_status",
        ),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.processing_run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.submission_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stakeholder_group_id"], ["session_stakeholder_groups.session_stakeholder_group_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["validation_id"], ["submission_validations.validation_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("processing_run_id", "submission_id"),
        sa.UniqueConstraint("processing_run_id", "participant_id", name="uq_processing_run_participant"),
    )

    op.create_table(
        "processing_matrices",
        sa.Column("processing_matrix_id", UUIDString(), nullable=False),
        sa.Column("processing_run_id", UUIDString(), nullable=False),
        sa.Column("level", sa.String(50), nullable=False),
        sa.Column("stakeholder_group_id", UUIDString(), nullable=True),
        sa.Column("validation_id", UUIDString(), nullable=True),
        sa.Column("criterion_ids_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("matrix_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("weights_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("diagnostics_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("matrix_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("level IN ('participant', 'stakeholder_group', 'session')", name="ck_processing_matrices_level"),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.processing_run_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stakeholder_group_id"], ["session_stakeholder_groups.session_stakeholder_group_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["validation_id"], ["submission_validations.validation_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("processing_matrix_id"),
    )
    op.create_index("ix_processing_matrices_run_level", "processing_matrices", ["processing_run_id", "level"])

    op.create_table(
        "run_artifacts",
        sa.Column("run_artifact_id", UUIDString(), nullable=False),
        sa.Column("processing_run_id", UUIDString(), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["processing_run_id"], ["processing_runs.processing_run_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("run_artifact_id"),
    )
    op.create_index("ix_run_artifacts_run_type", "run_artifacts", ["processing_run_id", "artifact_type"])


def downgrade() -> None:
    op.drop_index("ix_run_artifacts_run_type", table_name="run_artifacts")
    op.drop_table("run_artifacts")
    op.drop_index("ix_processing_matrices_run_level", table_name="processing_matrices")
    op.drop_table("processing_matrices")
    op.drop_table("processing_run_submissions")
    op.drop_table("processing_run_algorithms")
    op.drop_index("ix_processing_runs_session_status", table_name="processing_runs")
    op.drop_table("processing_runs")
    op.drop_table("validation_prepared_matrices")
    with op.batch_alter_table("submission_validations") as batch_op:
        batch_op.drop_index("uq_submission_validations_active_input")
        batch_op.drop_constraint("ck_submission_validations_attempt_positive", type_="check")
        batch_op.drop_constraint("uq_submission_validations_input_attempt", type_="unique")
        batch_op.create_unique_constraint(
            "uq_submission_validations_input_identity",
            [
                "submission_id",
                "answers_hash",
                "configuration_hash",
                "validator_implementation_id",
                "validator_version",
                "parameter_hash",
            ],
        )
        batch_op.drop_column("attempt_number")
