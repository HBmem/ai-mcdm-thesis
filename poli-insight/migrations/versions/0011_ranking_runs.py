"""immutable algorithm-neutral ranking runs

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ranking_runs",
        sa.Column("ranking_run_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("source_processing_run_id", UUIDString(), nullable=False),
        sa.Column("configuration_version_id", UUIDString(), nullable=False),
        sa.Column("scenario_snapshot_id", UUIDString(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("roster_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("algorithm_implementation_id", UUIDString(), nullable=False),
        sa.Column("implementation_version", sa.String(100), nullable=False),
        sa.Column("adapter_version", sa.String(100), nullable=False),
        sa.Column("parameter_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("environment_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("completed_at", UTCDateTime(), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.CheckConstraint("run_number >= 1", name="ck_ranking_runs_number_positive"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_ranking_runs_status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND output_hash IS NOT NULL "
            "AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(status = 'failed' AND output_hash IS NULL "
            "AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_ranking_runs_terminal_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_processing_run_id"],
            ["processing_runs.processing_run_id"],
            ondelete="RESTRICT",
        ),
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
        sa.ForeignKeyConstraint(
            ["algorithm_implementation_id"],
            ["algorithm_implementations.algorithm_implementation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("ranking_run_id"),
        sa.UniqueConstraint(
            "session_id",
            "run_number",
            name="uq_ranking_runs_session_number",
        ),
    )
    op.create_index(
        "ix_ranking_runs_session_status", "ranking_runs", ["session_id", "status"]
    )
    op.create_index(
        "ix_ranking_runs_source", "ranking_runs", ["source_processing_run_id"]
    )
    op.create_index(
        "uq_ranking_runs_success_input",
        "ranking_runs",
        ["input_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'succeeded'"),
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "ranking_results",
        sa.Column("ranking_result_id", UUIDString(), nullable=False),
        sa.Column("ranking_run_id", UUIDString(), nullable=False),
        sa.Column("source_processing_matrix_id", UUIDString(), nullable=False),
        sa.Column("level", sa.String(50), nullable=False),
        sa.Column("stakeholder_group_id", UUIDString(), nullable=True),
        sa.Column("validation_id", UUIDString(), nullable=True),
        sa.Column("alternatives_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("metric_label", sa.String(100), nullable=False),
        sa.Column("diagnostics_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "level IN ('participant', 'stakeholder_group', 'session')",
            name="ck_ranking_results_level",
        ),
        sa.CheckConstraint(
            "(level = 'participant' AND validation_id IS NOT NULL) OR "
            "(level != 'participant' AND validation_id IS NULL)",
            name="ck_ranking_results_validation_identity",
        ),
        sa.CheckConstraint(
            "level != 'stakeholder_group' OR stakeholder_group_id IS NOT NULL",
            name="ck_ranking_results_group_identity",
        ),
        sa.ForeignKeyConstraint(
            ["ranking_run_id"], ["ranking_runs.ranking_run_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_processing_matrix_id"],
            ["processing_matrices.processing_matrix_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stakeholder_group_id"],
            ["session_stakeholder_groups.session_stakeholder_group_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["validation_id"],
            ["submission_validations.validation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("ranking_result_id"),
    )
    op.create_index(
        "ix_ranking_results_run_level", "ranking_results", ["ranking_run_id", "level"]
    )
    op.create_index(
        "uq_ranking_results_run_source",
        "ranking_results",
        ["ranking_run_id", "source_processing_matrix_id"],
        unique=True,
    )

    op.create_table(
        "ranking_run_artifacts",
        sa.Column("ranking_artifact_id", UUIDString(), nullable=False),
        sa.Column("ranking_run_id", UUIDString(), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "schema_version >= 1",
            name="ck_ranking_artifacts_schema_positive",
        ),
        sa.ForeignKeyConstraint(
            ["ranking_run_id"], ["ranking_runs.ranking_run_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("ranking_artifact_id"),
    )
    op.create_index(
        "ix_ranking_artifacts_run_type",
        "ranking_run_artifacts",
        ["ranking_run_id", "artifact_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_ranking_artifacts_run_type", table_name="ranking_run_artifacts")
    op.drop_table("ranking_run_artifacts")
    op.drop_index("uq_ranking_results_run_source", table_name="ranking_results")
    op.drop_index("ix_ranking_results_run_level", table_name="ranking_results")
    op.drop_table("ranking_results")
    op.drop_index("uq_ranking_runs_success_input", table_name="ranking_runs")
    op.drop_index("ix_ranking_runs_source", table_name="ranking_runs")
    op.drop_index("ix_ranking_runs_session_status", table_name="ranking_runs")
    op.drop_table("ranking_runs")
