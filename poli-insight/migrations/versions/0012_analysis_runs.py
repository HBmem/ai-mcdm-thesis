"""immutable sensitivity and robustness analysis runs

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_runs",
        sa.Column("analysis_run_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("source_processing_run_id", UUIDString(), nullable=False),
        sa.Column("source_ranking_run_id", UUIDString(), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("analysis_type", sa.String(50), nullable=False),
        sa.Column("method", sa.String(80), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("source_processing_output_hash", sa.String(64), nullable=False),
        sa.Column("source_ranking_output_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("parameter_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("environment_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("completed_at", UTCDateTime(), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.CheckConstraint("run_number >= 1", name="ck_analysis_runs_number_positive"),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_analysis_runs_status"
        ),
        sa.CheckConstraint(
            "(method = 'one_at_a_time_weight_perturbation' AND analysis_type = 'sensitivity') OR "
            "(method IN ('criterion_removal', 'rank_reversal') AND analysis_type = 'robustness') OR "
            "(method = 'stakeholder_group_influence' AND analysis_type = 'stakeholder_comparison') OR "
            "(method = 'participant_influence' AND analysis_type = 'participant_impact')",
            name="ck_analysis_runs_method_type",
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND output_hash IS NOT NULL AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(status = 'failed' AND output_hash IS NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_analysis_runs_terminal_evidence",
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
            ["source_ranking_run_id"],
            ["ranking_runs.ranking_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("analysis_run_id"),
        sa.UniqueConstraint(
            "source_processing_run_id",
            "run_number",
            name="uq_analysis_runs_processing_number",
        ),
    )
    op.create_index(
        "ix_analysis_runs_session_method", "analysis_runs", ["session_id", "method"]
    )
    op.create_index(
        "ix_analysis_runs_ranking", "analysis_runs", ["source_ranking_run_id"]
    )
    op.create_index("ix_analysis_runs_correlation", "analysis_runs", ["correlation_id"])
    op.create_index(
        "uq_analysis_runs_success_input",
        "analysis_runs",
        ["input_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'succeeded'"),
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "analysis_cases",
        sa.Column("analysis_case_id", UUIDString(), nullable=False),
        sa.Column("analysis_run_id", UUIDString(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False),
        sa.Column("scope_id", sa.String(100), nullable=True),
        sa.Column("subject_type", sa.String(50), nullable=False),
        sa.Column("subject_id", sa.String(100), nullable=True),
        sa.Column("input_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("result_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("warnings_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_analysis_cases_sequence_positive"),
        sa.CheckConstraint(
            "status IN ('evaluated', 'not_evaluable')", name="ck_analysis_cases_status"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["analysis_runs.analysis_run_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("analysis_case_id"),
        sa.UniqueConstraint(
            "analysis_run_id", "sequence", name="uq_analysis_cases_run_sequence"
        ),
    )
    op.create_index(
        "ix_analysis_cases_run_scope",
        "analysis_cases",
        ["analysis_run_id", "scope_type", "scope_id"],
    )
    op.create_index(
        "ix_analysis_cases_run_subject",
        "analysis_cases",
        ["analysis_run_id", "subject_type", "subject_id"],
    )

    op.create_table(
        "analysis_artifacts",
        sa.Column("analysis_artifact_id", UUIDString(), nullable=False),
        sa.Column("analysis_run_id", UUIDString(), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "schema_version >= 1", name="ck_analysis_artifacts_schema_positive"
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id"], ["analysis_runs.analysis_run_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("analysis_artifact_id"),
    )
    op.create_index(
        "ix_analysis_artifacts_run_type",
        "analysis_artifacts",
        ["analysis_run_id", "artifact_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_artifacts_run_type", table_name="analysis_artifacts")
    op.drop_table("analysis_artifacts")
    op.drop_index("ix_analysis_cases_run_subject", table_name="analysis_cases")
    op.drop_index("ix_analysis_cases_run_scope", table_name="analysis_cases")
    op.drop_table("analysis_cases")
    op.drop_index("uq_analysis_runs_success_input", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_correlation", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_ranking", table_name="analysis_runs")
    op.drop_index("ix_analysis_runs_session_method", table_name="analysis_runs")
    op.drop_table("analysis_runs")
