"""Complete participant access, consent, and resume persistence.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_access_codes",
        sa.Column("access_code_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("invitation_id", UUIDString(), nullable=True),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("use_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("expires_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "length(trim(code_hash)) > 0", name="ck_session_access_codes_hash_nonempty"
        ),
        sa.CheckConstraint(
            "use_count >= 0", name="ck_session_access_codes_use_count_nonnegative"
        ),
        sa.CheckConstraint(
            "max_uses IS NULL OR max_uses >= 1",
            name="ck_session_access_codes_max_uses_positive",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_session_access_codes_expiration_order",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["session_invitations.invitation_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("access_code_id"),
        sa.UniqueConstraint(
            "session_id", "invitation_id", name="uq_session_access_codes_scope"
        ),
    )
    op.create_index(
        "ix_session_access_codes_session_active",
        "session_access_codes",
        ["session_id", "active"],
    )

    op.create_table(
        "participant_access_attempts",
        sa.Column("access_attempt_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("invitation_id", UUIDString(), nullable=True),
        sa.Column("access_code_id", UUIDString(), nullable=True),
        sa.Column("attempted_at", UTCDateTime(), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=80), nullable=False),
        sa.Column("rate_limit_key_hash", sa.String(length=64), nullable=True),
        sa.Column("network_metadata_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'rejected')",
            name="ck_participant_access_attempts_outcome_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["access_code_id"],
            ["session_access_codes.access_code_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["session_invitations.invitation_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("access_attempt_id"),
    )
    op.create_index(
        "ix_participant_access_attempts_session_time",
        "participant_access_attempts",
        ["session_id", "attempted_at"],
    )

    op.create_table(
        "participant_consents",
        sa.Column("participant_consent_id", UUIDString(), nullable=False),
        sa.Column("participant_id", UUIDString(), nullable=False),
        sa.Column("session_id", UUIDString(), nullable=False),
        sa.Column("configuration_version_id", UUIDString(), nullable=False),
        sa.Column("consent_version", sa.String(length=100), nullable=False),
        sa.Column("statement_hash", sa.String(length=64), nullable=False),
        sa.Column("accepted_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "length(statement_hash) = 64 AND statement_hash = lower(statement_hash)",
            name="ck_participant_consents_statement_hash",
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"], ["participants.participant_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["sessions.session_id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["session_configuration_versions.configuration_version_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("participant_consent_id"),
        sa.UniqueConstraint(
            "participant_id",
            "configuration_version_id",
            "consent_version",
            name="uq_participant_consents_version",
        ),
    )
    op.create_index(
        "ix_participant_consents_participant",
        "participant_consents",
        ["participant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_participant_consents_participant", table_name="participant_consents"
    )
    op.drop_table("participant_consents")
    op.drop_index(
        "ix_participant_access_attempts_session_time",
        table_name="participant_access_attempts",
    )
    op.drop_table("participant_access_attempts")
    op.drop_index(
        "ix_session_access_codes_session_active", table_name="session_access_codes"
    )
    op.drop_table("session_access_codes")
