"""SQLAlchemy rows for invitations, participants, identities, and grants."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from poli_insight.domain.enum import (
    InvitationStatus,
    ParticipantAccessStatus,
)
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


def _enum_sql_values(enum_type: type[StrEnum]) -> str:
    """Return trusted enum values formatted for a SQL CHECK constraint."""

    return ", ".join(f"'{member.value}'" for member in enum_type)


class SessionInvitationRow(Base):
    """One-time invitation pinned to a session configuration and group."""

    __tablename__ = "session_invitations"
    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_session_invitations_token_digest",
        ),
        UniqueConstraint(
            "session_id",
            "configuration_version_id",
            "invitation_id",
            name="uq_invitations_session_config_id",
        ),
        ForeignKeyConstraint(
            ["session_id", "configuration_version_id"],
            [
                "session_configuration_versions.session_id",
                "session_configuration_versions.configuration_version_id",
            ],
            name="fk_invitations_session_configuration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["configuration_version_id", "assigned_group_id"],
            [
                "session_stakeholder_groups.configuration_version_id",
                "session_stakeholder_groups.session_stakeholder_group_id",
            ],
            name="fk_invitations_assigned_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "invitation_id", "redeemed_participant_id"],
            [
                "participants.session_id",
                "participants.invitation_id",
                "participants.participant_id",
            ],
            name="fk_invitations_redeemed_participant",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_values(InvitationStatus)})",
            name="ck_invitations_status_allowed",
        ),
        CheckConstraint(
            "length(token_digest) = 64 "
            "AND token_digest = lower(token_digest)",
            name="ck_invitations_token_digest_format",
        ),
        CheckConstraint(
            "identity_lookup_hash IS NULL OR "
            "(length(identity_lookup_hash) = 64 "
            "AND identity_lookup_hash = lower(identity_lookup_hash))",
            name="ck_invitations_identity_hash_format",
        ),
        CheckConstraint(
            "identity_lookup_hash IS NULL OR identity_ciphertext IS NOT NULL",
            name="ck_invitations_identity_hash_has_ciphertext",
        ),
        CheckConstraint(
            "identity_ciphertext IS NULL OR length(identity_ciphertext) > 0",
            name="ck_invitations_identity_ciphertext_nonempty",
        ),
        CheckConstraint(
            "token_hint IS NULL OR length(trim(token_hint)) > 0",
            name="ck_invitations_token_hint_nonempty",
        ),
        CheckConstraint(
            "max_redemptions = 1",
            name="ck_invitations_one_time_redemption",
        ),
        CheckConstraint(
            "send_count >= 0",
            name="ck_invitations_send_count_nonnegative",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_invitations_expiration_order",
        ),
        CheckConstraint(
            "sent_at IS NULL OR sent_at >= created_at",
            name="ck_invitations_send_order",
        ),
        CheckConstraint(
            "redeemed_at IS NULL OR "
            "(redeemed_at >= created_at AND redeemed_at < expires_at)",
            name="ck_invitations_redemption_order",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_invitations_revocation_order",
        ),
        CheckConstraint(
            "(status = 'redeemed' "
            "AND redeemed_at IS NOT NULL "
            "AND redeemed_participant_id IS NOT NULL) "
            "OR (status <> 'redeemed' "
            "AND redeemed_at IS NULL "
            "AND redeemed_participant_id IS NULL)",
            name="ck_invitations_redemption_state",
        ),
        CheckConstraint(
            "(status = 'revoked' "
            "AND revoked_at IS NOT NULL "
            "AND revoked_by IS NOT NULL "
            "AND revocation_reason IS NOT NULL) "
            "OR (status <> 'revoked' "
            "AND revoked_at IS NULL "
            "AND revoked_by IS NULL "
            "AND revocation_reason IS NULL)",
            name="ck_invitations_revocation_state",
        ),
        CheckConstraint(
            "(status IN ('sent', 'delivery_failed', 'redeemed') "
            "AND sent_at IS NOT NULL AND send_count >= 1) "
            "OR (status = 'pending' "
            "AND sent_at IS NULL AND send_count = 0) "
            "OR (status IN ('expired', 'revoked') "
            "AND ((sent_at IS NULL AND send_count = 0) "
            "OR (sent_at IS NOT NULL AND send_count >= 1)))",
            name="ck_invitations_send_state",
        ),
        CheckConstraint(
            "length(trim(created_by)) > 0",
            name="ck_invitations_creator_nonempty",
        ),
        Index(
            "ix_invitations_session_status",
            "session_id",
            "status",
        ),
        Index("ix_invitations_expires_at", "expires_at"),
        Index(
            "ix_invitations_configuration_id",
            "configuration_version_id",
        ),
        Index("ix_invitations_assigned_group_id", "assigned_group_id"),
        Index("ix_invitations_identity_lookup_hash", "identity_lookup_hash"),
    )

    invitation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    assigned_group_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )
    token_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    token_hint: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    identity_lookup_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    identity_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=InvitationStatus.PENDING.value,
        server_default=InvitationStatus.PENDING.value,
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    max_redemptions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    sent_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    send_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    redeemed_participant_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )


class ParticipantRow(Base):
    """Analytical participant record without optional personal identity."""

    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "participant_id",
            name="uq_participants_session_id",
        ),
        UniqueConstraint(
            "session_id",
            "user_id",
            name="uq_participants_session_user",
        ),
        UniqueConstraint(
            "session_id",
            "alias",
            name="uq_participants_session_alias",
        ),
        UniqueConstraint(
            "invitation_id",
            name="uq_participants_invitation_id",
        ),
        UniqueConstraint(
            "session_id",
            "invitation_id",
            "participant_id",
            name="uq_participants_session_invitation_participant",
        ),
        ForeignKeyConstraint(
            ["session_id", "configuration_version_id"],
            [
                "session_configuration_versions.session_id",
                "session_configuration_versions.configuration_version_id",
            ],
            name="fk_participants_session_configuration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["configuration_version_id", "session_stakeholder_group_id"],
            [
                "session_stakeholder_groups.configuration_version_id",
                "session_stakeholder_groups.session_stakeholder_group_id",
            ],
            name="fk_participants_configuration_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "configuration_version_id", "invitation_id"],
            [
                "session_invitations.session_id",
                "session_invitations.configuration_version_id",
                "session_invitations.invitation_id",
            ],
            name="fk_participants_session_config_invitation",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            f"access_status IN ({_enum_sql_values(ParticipantAccessStatus)})",
            name="ck_participants_access_status_allowed",
        ),
        CheckConstraint(
            "alias IS NULL OR length(trim(alias)) > 0",
            name="ck_participants_alias_nonempty",
        ),
        CheckConstraint(
            "enrolled_at >= created_at",
            name="ck_participants_enrollment_order",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_participants_update_order",
        ),
        CheckConstraint(
            "joined_at IS NULL OR joined_at >= enrolled_at",
            name="ck_participants_join_order",
        ),
        CheckConstraint(
            "started_at IS NULL OR "
            "(joined_at IS NOT NULL AND started_at >= joined_at)",
            name="ck_participants_start_order",
        ),
        CheckConstraint(
            "submitted_at IS NULL OR "
            "(started_at IS NOT NULL AND submitted_at >= started_at)",
            name="ck_participants_submission_order",
        ),
        CheckConstraint(
            "completed_at IS NULL OR "
            "(submitted_at IS NOT NULL AND completed_at >= submitted_at)",
            name="ck_participants_completion_order",
        ),
        CheckConstraint(
            "disabled_at IS NULL OR disabled_at >= created_at",
            name="ck_participants_disable_order",
        ),
        CheckConstraint(
            "withdrawn_at IS NULL OR withdrawn_at >= created_at",
            name="ck_participants_withdrawal_order",
        ),
        CheckConstraint(
            "updated_at >= enrolled_at "
            "AND (joined_at IS NULL OR updated_at >= joined_at) "
            "AND (started_at IS NULL OR updated_at >= started_at) "
            "AND (submitted_at IS NULL OR updated_at >= submitted_at) "
            "AND (completed_at IS NULL OR updated_at >= completed_at) "
            "AND (disabled_at IS NULL OR updated_at >= disabled_at) "
            "AND (withdrawn_at IS NULL OR updated_at >= withdrawn_at)",
            name="ck_participants_update_after_events",
        ),
        CheckConstraint(
            "(access_status = 'active' "
            "AND disabled_at IS NULL "
            "AND disabled_by IS NULL "
            "AND disable_reason IS NULL "
            "AND withdrawn_at IS NULL "
            "AND withdrawn_by IS NULL "
            "AND withdrawal_reason IS NULL) "
            "OR (access_status = 'disabled' "
            "AND disabled_at IS NOT NULL "
            "AND disabled_by IS NOT NULL "
            "AND disable_reason IS NOT NULL "
            "AND withdrawn_at IS NULL "
            "AND withdrawn_by IS NULL "
            "AND withdrawal_reason IS NULL) "
            "OR (access_status = 'withdrawn' "
            "AND withdrawn_at IS NOT NULL "
            "AND withdrawn_by IS NOT NULL "
            "AND withdrawal_reason IS NOT NULL "
            "AND ((disabled_at IS NULL "
            "AND disabled_by IS NULL "
            "AND disable_reason IS NULL) "
            "OR (disabled_at IS NOT NULL "
            "AND disabled_by IS NOT NULL "
            "AND disable_reason IS NOT NULL)))",
            name="ck_participants_access_state",
        ),
        CheckConstraint(
            "length(trim(created_by)) > 0",
            name="ck_participants_creator_nonempty",
        ),
        CheckConstraint(
            "length(trim(updated_by)) > 0",
            name="ck_participants_updater_nonempty",
        ),
        Index(
            "ix_participants_session_access",
            "session_id",
            "access_status",
        ),
        Index(
            "ix_participants_configuration_group",
            "configuration_version_id",
            "session_stakeholder_group_id",
        ),
        Index("ix_participants_session_started", "session_id", "started_at"),
        Index(
            "ix_participants_session_completed",
            "session_id",
            "completed_at",
        ),
    )

    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "sessions.session_id",
            name="fk_participants_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    session_stakeholder_group_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )
    invitation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )
    alias: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    access_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ParticipantAccessStatus.ACTIVE.value,
        server_default=ParticipantAccessStatus.ACTIVE.value,
    )
    enrolled_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    disabled_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    disable_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    withdrawn_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    withdrawal_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )


class ParticipantIdentityRow(Base):
    """Encrypted optional PII stored separately from analytical records."""

    __tablename__ = "participant_identities"
    __table_args__ = (
        CheckConstraint(
            "length(trim(consent_version)) > 0",
            name="ck_participant_identities_consent_nonempty",
        ),
        CheckConstraint(
            "retention_until > consented_at",
            name="ck_participant_identities_retention_order",
        ),
        CheckConstraint(
            "display_name_ciphertext IS NULL "
            "OR length(display_name_ciphertext) > 0",
            name="ck_participant_identities_name_nonempty",
        ),
        CheckConstraint(
            "email_ciphertext IS NULL OR length(email_ciphertext) > 0",
            name="ck_participant_identities_email_nonempty",
        ),
        CheckConstraint(
            "additional_identity_ciphertext IS NULL "
            "OR length(additional_identity_ciphertext) > 0",
            name="ck_participant_identities_extra_nonempty",
        ),
        CheckConstraint(
            "(email_ciphertext IS NULL AND email_lookup_hash IS NULL) "
            "OR (email_ciphertext IS NOT NULL "
            "AND email_lookup_hash IS NOT NULL)",
            name="ck_participant_identities_email_pair",
        ),
        CheckConstraint(
            "email_lookup_hash IS NULL OR "
            "(length(email_lookup_hash) = 64 "
            "AND email_lookup_hash = lower(email_lookup_hash))",
            name="ck_participant_identities_email_hash_format",
        ),
        CheckConstraint(
            "(redacted_at IS NULL "
            "AND redacted_by IS NULL "
            "AND (display_name_ciphertext IS NOT NULL "
            "OR email_ciphertext IS NOT NULL "
            "OR additional_identity_ciphertext IS NOT NULL)) "
            "OR (redacted_at IS NOT NULL "
            "AND redacted_by IS NOT NULL "
            "AND redacted_at >= consented_at "
            "AND display_name_ciphertext IS NULL "
            "AND email_ciphertext IS NULL "
            "AND email_lookup_hash IS NULL "
            "AND additional_identity_ciphertext IS NULL)",
            name="ck_participant_identities_redaction_state",
        ),
        Index(
            "ix_participant_identities_email_lookup_hash",
            "email_lookup_hash",
        ),
        Index(
            "ix_participant_identities_retention_until",
            "retention_until",
        ),
    )

    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "participants.participant_id",
            name="fk_participant_identities_participant_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    consent_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    consented_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    retention_until: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    display_name_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    email_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    email_lookup_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    additional_identity_ciphertext: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    redacted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    redacted_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )


class ParticipantAccessGrantRow(Base):
    """Revocable digest of a participant login or resume credential."""

    __tablename__ = "participant_access_grants"
    __table_args__ = (
        UniqueConstraint(
            "token_digest",
            name="uq_participant_access_grants_token_digest",
        ),
        UniqueConstraint(
            "participant_id",
            "access_grant_id",
            name="uq_access_grants_participant_id",
        ),
        ForeignKeyConstraint(
            ["participant_id", "replaced_by_grant_id"],
            [
                "participant_access_grants.participant_id",
                "participant_access_grants.access_grant_id",
            ],
            name="fk_access_grants_same_participant_replacement",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            "length(token_digest) = 64 "
            "AND token_digest = lower(token_digest)",
            name="ck_access_grants_token_digest_format",
        ),
        CheckConstraint(
            "expires_at > issued_at",
            name="ck_access_grants_expiration_order",
        ),
        CheckConstraint(
            "last_used_at IS NULL OR "
            "(last_used_at >= issued_at AND last_used_at < expires_at)",
            name="ck_access_grants_last_use_order",
        ),
        CheckConstraint(
            "(revoked_at IS NULL "
            "AND revoked_by IS NULL "
            "AND revocation_reason IS NULL) "
            "OR (revoked_at IS NOT NULL "
            "AND revoked_by IS NOT NULL "
            "AND revocation_reason IS NOT NULL "
            "AND revoked_at >= issued_at "
            "AND (last_used_at IS NULL OR revoked_at >= last_used_at))",
            name="ck_access_grants_revocation_state",
        ),
        CheckConstraint(
            "replaced_by_grant_id IS NULL "
            "OR (revoked_at IS NOT NULL "
            "AND replaced_by_grant_id <> access_grant_id)",
            name="ck_access_grants_replacement_state",
        ),
        Index(
            "ix_access_grants_participant_active",
            "participant_id",
            "revoked_at",
            "expires_at",
        ),
        Index("ix_access_grants_expires_at", "expires_at"),
    )

    access_grant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "participants.participant_id",
            name="fk_access_grants_participant_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    token_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    issued_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    revoked_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    revocation_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    replaced_by_grant_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )


class SessionAccessCodeRow(Base):
    """Slow-hashed human access code scoped to a session or invitation."""

    __tablename__ = "session_access_codes"
    __table_args__ = (
        CheckConstraint(
            "length(trim(code_hash)) > 0",
            name="ck_session_access_codes_hash_nonempty",
        ),
        CheckConstraint(
            "use_count >= 0",
            name="ck_session_access_codes_use_count_nonnegative",
        ),
        CheckConstraint(
            "max_uses IS NULL OR max_uses >= 1",
            name="ck_session_access_codes_max_uses_positive",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="ck_session_access_codes_expiration_order",
        ),
        UniqueConstraint(
            "session_id",
            "invitation_id",
            name="uq_session_access_codes_scope",
        ),
        Index("ix_session_access_codes_session_active", "session_id", "active"),
    )

    access_code_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    invitation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey("session_invitations.invitation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="1"
    )
    use_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ParticipantAccessAttemptRow(Base):
    """Secret-free admission attempt retained for security operations."""

    __tablename__ = "participant_access_attempts"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('accepted', 'rejected')",
            name="ck_participant_access_attempts_outcome_allowed",
        ),
        Index(
            "ix_participant_access_attempts_session_time",
            "session_id",
            "attempted_at",
        ),
    )

    access_attempt_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    invitation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey("session_invitations.invitation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    access_code_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey("session_access_codes.access_code_id", ondelete="RESTRICT"),
        nullable=True,
    )
    attempted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    rate_limit_key_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    network_metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSON(none_as_null=True), nullable=False, default=dict
    )


class ParticipantConsentRow(Base):
    """Immutable acceptance evidence for a configured consent statement."""

    __tablename__ = "participant_consents"
    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "configuration_version_id",
            "consent_version",
            name="uq_participant_consents_version",
        ),
        CheckConstraint(
            "length(statement_hash) = 64 AND statement_hash = lower(statement_hash)",
            name="ck_participant_consents_statement_hash",
        ),
        Index("ix_participant_consents_participant", "participant_id"),
    )

    participant_consent_id: Mapped[UUID] = mapped_column(
        UUIDString(), primary_key=True
    )
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("participants.participant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
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
    consent_version: Mapped[str] = mapped_column(String(100), nullable=False)
    statement_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
