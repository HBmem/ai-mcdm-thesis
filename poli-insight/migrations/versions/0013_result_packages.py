"""immutable final result packages and participant releases

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUDIT_ACTIONS = (
    "created",
    "updated",
    "opened",
    "closed",
    "invited",
    "redeemed",
    "submitted",
    "validated",
    "included",
    "excluded",
    "processed",
    "analyzed",
    "approved",
    "published",
    "withdrawn",
    "redacted",
    "activated",
    "scheduled",
    "paused",
    "resumed",
    "canceled",
    "archived",
)


def _action_constraint(values: tuple[str, ...]) -> str:
    return "action IN (" + ", ".join(repr(value) for value in values) + ")"


def upgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("ck_audit_events_action_allowed", type_="check")
        batch_op.create_check_constraint(
            "ck_audit_events_action_allowed",
            _action_constraint((*_AUDIT_ACTIONS, "packaged")),
        )
    op.create_table(
        "result_package_runs",
        sa.Column("package_run_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("source_processing_run_id", UUIDString(), nullable=False),
        sa.Column("source_ranking_run_id", UUIDString(), nullable=False),
        sa.Column(
            "source_analysis_run_ids_json", sa.JSON(none_as_null=True), nullable=False
        ),
        sa.Column("variants_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("source_roster_hash", sa.String(64), nullable=False),
        sa.Column("source_processing_output_hash", sa.String(64), nullable=False),
        sa.Column("source_ranking_output_hash", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("environment_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(100), nullable=False),
        sa.Column("completed_at", UTCDateTime(), nullable=False),
        sa.Column("correlation_id", sa.String(100), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "run_number >= 1", name="ck_result_packages_number_positive"
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_result_packages_status"
        ),
        sa.CheckConstraint(
            "(status = 'succeeded' AND output_hash IS NOT NULL AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(status = 'failed' AND output_hash IS NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_result_packages_terminal_evidence",
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
        sa.PrimaryKeyConstraint("package_run_id"),
        sa.UniqueConstraint(
            "session_id", "run_number", name="uq_result_packages_number"
        ),
    )
    op.create_index(
        "ix_result_packages_session_status",
        "result_package_runs",
        ["session_id", "status"],
    )
    op.create_index(
        "ix_result_packages_ranking", "result_package_runs", ["source_ranking_run_id"]
    )
    op.create_index(
        "uq_result_packages_success_input",
        "result_package_runs",
        ["input_hash"],
        unique=True,
        sqlite_where=sa.text("status = 'succeeded'"),
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "result_package_artifacts",
        sa.Column("package_artifact_id", UUIDString(), nullable=False),
        sa.Column("package_run_id", UUIDString(), nullable=False),
        sa.Column("artifact_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("variant", sa.String(30), nullable=True),
        sa.Column("content_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "sequence >= 1 AND schema_version >= 1",
            name="ck_result_package_artifacts_positive",
        ),
        sa.CheckConstraint(
            "artifact_type IN ('input_manifest', 'common_section', 'variant_manifest')",
            name="ck_result_package_artifacts_type",
        ),
        sa.CheckConstraint(
            "(artifact_type = 'variant_manifest' AND variant IN ('anonymous', 'public')) OR "
            "(artifact_type != 'variant_manifest' AND variant IS NULL)",
            name="ck_result_package_artifacts_variant",
        ),
        sa.ForeignKeyConstraint(
            ["package_run_id"],
            ["result_package_runs.package_run_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("package_artifact_id"),
        sa.UniqueConstraint(
            "package_run_id", "sequence", name="uq_result_package_artifacts_sequence"
        ),
    )
    op.create_index(
        "ix_result_package_artifacts_variant",
        "result_package_artifacts",
        ["package_run_id", "variant"],
    )

    op.create_table(
        "result_package_subjects",
        sa.Column("package_subject_id", UUIDString(), nullable=False),
        sa.Column("package_run_id", UUIDString(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("subject_key", sa.String(100), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("alias_snapshot", sa.String(160), nullable=False),
        sa.Column("stakeholder_group_id", UUIDString(), nullable=False),
        sa.Column("stakeholder_group_label", sa.String(200), nullable=False),
        sa.Column("inclusion_status", sa.String(50), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("result_json", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_result_package_subjects_positive"),
        sa.CheckConstraint(
            "inclusion_status IN ('included', 'pending_review', 'excluded_invalid', "
            "'excluded_superseded', 'excluded_withdrawn', 'excluded_disabled', "
            "'excluded_cutoff', 'excluded_moderator', 'excluded_error')",
            name="ck_result_package_subjects_inclusion_status",
        ),
        sa.CheckConstraint(
            "(inclusion_status = 'included' AND exclusion_reason IS NULL) OR "
            "(inclusion_status = 'pending_review') OR "
            "(inclusion_status NOT IN ('included', 'pending_review') AND exclusion_reason IS NOT NULL)",
            name="ck_result_package_subjects_exclusion",
        ),
        sa.ForeignKeyConstraint(
            ["package_run_id"],
            ["result_package_runs.package_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["stakeholder_group_id"],
            ["session_stakeholder_groups.session_stakeholder_group_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("package_subject_id"),
        sa.UniqueConstraint(
            "package_run_id", "sequence", name="uq_result_package_subjects_sequence"
        ),
        sa.UniqueConstraint(
            "package_run_id", "subject_key", name="uq_result_package_subjects_key"
        ),
        sa.UniqueConstraint(
            "package_run_id",
            "participant_id",
            name="uq_result_package_subjects_participant",
        ),
    )
    op.create_index(
        "ix_result_package_subjects_lookup",
        "result_package_subjects",
        ["package_run_id", "participant_id"],
    )

    op.create_table(
        "participant_result_releases",
        sa.Column("release_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("package_run_id", UUIDString(), nullable=False),
        sa.Column("package_artifact_id", UUIDString(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("released_at", UTCDateTime(), nullable=False),
        sa.Column("released_by", sa.String(100), nullable=False),
        sa.Column("withdrawn_at", UTCDateTime(), nullable=True),
        sa.Column("withdrawn_by", sa.String(100), nullable=True),
        sa.Column("withdrawal_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "version_number >= 1", name="ck_participant_releases_positive"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'withdrawn')", name="ck_participant_releases_status"
        ),
        sa.CheckConstraint(
            "(status = 'active' AND withdrawn_at IS NULL AND withdrawn_by IS NULL AND withdrawal_reason IS NULL) OR "
            "(status = 'withdrawn' AND withdrawn_at IS NOT NULL AND withdrawn_by IS NOT NULL AND withdrawal_reason IS NOT NULL)",
            name="ck_participant_releases_withdrawal",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["package_run_id"],
            ["result_package_runs.package_run_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["package_artifact_id"],
            ["result_package_artifacts.package_artifact_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("release_id"),
        sa.UniqueConstraint(
            "session_id", "version_number", name="uq_participant_releases_version"
        ),
    )
    op.create_index(
        "uq_participant_releases_active",
        "participant_result_releases",
        ["session_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_participant_releases_active", table_name="participant_result_releases"
    )
    op.drop_table("participant_result_releases")
    op.drop_index(
        "ix_result_package_subjects_lookup", table_name="result_package_subjects"
    )
    op.drop_table("result_package_subjects")
    op.drop_index(
        "ix_result_package_artifacts_variant", table_name="result_package_artifacts"
    )
    op.drop_table("result_package_artifacts")
    op.drop_index("uq_result_packages_success_input", table_name="result_package_runs")
    op.drop_index("ix_result_packages_ranking", table_name="result_package_runs")
    op.drop_index("ix_result_packages_session_status", table_name="result_package_runs")
    op.drop_table("result_package_runs")
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("ck_audit_events_action_allowed", type_="check")
        batch_op.create_check_constraint(
            "ck_audit_events_action_allowed",
            _action_constraint(_AUDIT_ACTIONS),
        )
