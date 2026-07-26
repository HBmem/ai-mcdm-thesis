from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Float,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poli_insight.infrastructure.database.base import Base

class ScenarioSnapshotRow(Base):
    __tablename__ = "scenario_snapshots"

    scenario_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    scenario_version: Mapped[str] = mapped_column(
        String(50),
        primary_key=True,
    )

    scenario_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    config_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    config_snapshot_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    sessions: Mapped[list[SessionRow]] = relationship(
        "SessionRow",
        back_populates="snapshot",
        lazy="raise",
    )

class SessionRow(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scenario_id", "scenario_version"],
            [
                "scenario_snapshots.scenario_id",
                "scenario_snapshots.scenario_version",
            ],
            name="fk_sessions_scenario_snapshot",
            ondelete="RESTRICT",
        ),
    )

    session_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    scenario_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    scenario_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=True,
    )
    admin_notes: Mapped[str] = mapped_column(
        Text,
        nullable=True,
    )

    visibility: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    participation_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    preference_scale: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    weighting_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    ranking_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    aggregation_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    require_access_code: Mapped[bool] = mapped_column(
        nullable=False,
    )
    access_code_type: Mapped[str] = mapped_column(
        String(50),
        nullable=True,
    )
    allow_resubmissions: Mapped[bool] = mapped_column(
        nullable=False,
    )

    start_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    end_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    closed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    snapshot: Mapped[ScenarioSnapshotRow] = relationship(
        "ScenarioSnapshotRow",
        back_populates="sessions",
        lazy="raise",
    )

    stakeholder_groups: Mapped[
        list[SessionStakeholderGroupRow]
    ] = relationship(
        "SessionStakeholderGroupRow",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )

    participants: Mapped[
        list[ParticipantRow]
    ] = relationship(
        "ParticipantRow",
        back_populates="session",
        foreign_keys="ParticipantRow.session_id",
        lazy="raise",
    )

class SessionStakeholderGroupRow(Base):
    __tablename__ = "session_stakeholder_groups"

    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "sessions.session_id",
            name="fk_session_stakeholder_groups_session",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    stakeholder_group_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    stakeholder_group_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    default_voting_power: Mapped[float] = mapped_column(
        nullable=False,
    )
    current_voting_power: Mapped[float] = mapped_column(
        nullable=False,
    )
    normalized_voting_power: Mapped[float] = mapped_column(
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    updated_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    session: Mapped[SessionRow] = relationship(
        "SessionRow",
        back_populates="stakeholder_groups",
        lazy="raise",
    )

    participants: Mapped[
        list[ParticipantRow]
    ] = relationship(
        "ParticipantRow",
        back_populates="stakeholder_group",
        foreign_keys=(
            "[ParticipantRow.session_id, "
            "ParticipantRow.stakeholder_group_id]"
        ),
        viewonly=True,
        lazy="raise",
    )

class ParticipantRow(Base):
    __tablename__ = "participants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["session_id", "stakeholder_group_id"],
            [
                "session_stakeholder_groups.session_id",
                "session_stakeholder_groups.stakeholder_group_id",
            ],
            name="fk_participants_session_stakeholder_group",
            ondelete="RESTRICT",
        ),

        UniqueConstraint(
            "session_id",
            "user_id",
            name="uq_session_participants_session_user",
        ),
    
        UniqueConstraint(
            "session_id",
            "alias",
            name="uq_session_participants_session_alias",
        ),

        CheckConstraint(
            "access_status IN ('active', 'disabled', 'withdrawn')",
            name="ck_participants_access_status",
        ),

        CheckConstraint(
            "access_status <> 'disabled' "
            "OR (disabled_at IS NOT NULL AND disabled_by IS NOT NULL)",
            name="ck_session_participants_disabled_metadata",
        ),

        CheckConstraint(
            "updated_at >= created_at",
            name="ck_session_participants_update_time",
        ),

        Index(
            "ix_session_participants_session_status",
            "session_id",
            "access_status",
        ),

        Index(
            "ix_session_participants_session_group",
            "session_id",
            "stakeholder_group_id",
        ),
    )
    
    participant_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "sessions.session_id",
            name="fk_session_participants_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    # TODO: If a local users table is added, change this to: ForeignKey("users.user_id", ondelete="SET NULL")
    user_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
    )

    stakeholder_group_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    alias: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    access_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    disabled_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    session: Mapped[SessionRow] = relationship(
        "SessionRow",
        back_populates="participants",
        foreign_keys=[session_id],
        lazy="raise",
    )

    stakeholder_group: Mapped[SessionStakeholderGroupRow] = relationship(
        "SessionStakeholderGroupRow",
        back_populates="participants",
        foreign_keys=[
            session_id,
            stakeholder_group_id,
        ],
        viewonly=True,
        lazy="raise",
    )

    submissions: Mapped[list[SubmissionRow]] = relationship(
        "SubmissionRow",
        back_populates="participant",
        order_by="SubmissionRow.attempt_number",
        lazy="raise",
    )

class SubmissionRow(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "attempt_number",
            name="uq_submissions_participant_attempt",
        ),

        CheckConstraint(
            "attempt_number >= 1",
            name="ck_submissions_attempt_number",
        ),

        CheckConstraint(
            "status IN "
            "('draft', 'submitted', 'superseded', 'withdrawn')",
            name="ck_submissions_status",
        ),

        CheckConstraint(
            "status <> 'draft' OR submitted_at IS NULL",
            name="ck_submissions_draft_not_submitted",
        ),

        CheckConstraint(
            "status NOT IN ('submitted', 'superseded') "
            "OR (submitted_at IS NOT NULL AND submitted_by IS NOT NULL)",
            name="ck_submissions_submitted_metadata",
        ),

        CheckConstraint(
            "status <> 'superseded' OR superseded_at IS NOT NULL",
            name="ck_submissions_superseded_time",
        ),

        CheckConstraint(
            "status <> 'withdrawn' OR withdrawn_at IS NOT NULL",
            name="ck_submissions_withdrawn_time",
        ),

        CheckConstraint(
            "submitted_at IS NULL OR submitted_at >= started_at",
            name="ck_submissions_submission_time",
        ),

        Index(
            "uq_submissions_one_draft_per_participant",
            "participant_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
            sqlite_where=text("status = 'draft'"),
        ),

        Index(
            "uq_submissions_one_effective_per_participant",
            "participant_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
            sqlite_where=text("status = 'submitted'"),
        ),

        Index(
            "ix_submissions_participant_status",
            "participant_id",
            "status",
        ),
    )

    submission_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )

    participant_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "participants.participant_id",
            name="fk_submissions_participant",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )

    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    
    previous_submission_id: Mapped[str | None] = mapped_column(
        String(100),
        ForeignKey(
            "submissions.submission_id",
            name="fk_submissions_previous_submission",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    answers_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    last_saved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    withdrawn_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    updated_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    participant: Mapped[ParticipantRow] = relationship(
        "ParticipantRow",
        back_populates="submissions",
        lazy="raise",
    )

    previous_submission: Mapped[SubmissionRow | None] = relationship(
        "SubmissionRow",
        back_populates="replacement_attempts",
        foreign_keys=[previous_submission_id],
        remote_side="SubmissionRow.submission_id",
        lazy="raise",
    )

    replacement_attempts: Mapped[list[SubmissionRow]] = relationship(
        "SubmissionRow",
        back_populates="previous_submission",
        foreign_keys="SubmissionRow.previous_submission_id",
        lazy="raise",
    )

class SubmissionValidationRow(Base):
    __tablename__ = "submission_validations"
    __table_args__ = (
        CheckConstraint(
            "completion_ratio >= 0.0 "
            "AND completion_ratio <= 1.0",
            name="ck_submission_validations_completion_ratio",
        ),
        CheckConstraint(
            "consistency_ratio IS NULL "
            "OR consistency_ratio >= 0.0",
            name="ck_submission_validations_consistency_ratio",
        ),
        UniqueConstraint(
            "submission_id",
            "answers_hash",
            "weighting_method",
            "validator_version",
            name="uq_submission_validations_input_version",
        ),
        Index(
            "ix_submission_validations_submission",
            "submission_id",
        ),
    )

    validation_id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
    )
    
    submission_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey(
            "submissions.submission_id",
            name="fk_submission_validation_submissions",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    answers_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    weighting_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
        
    validator_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    completion_ratio: Mapped[float] = mapped_column(
        nullable=False,
    )

    weights_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    consistency_ratio: Mapped[float | None] = mapped_column(
        nullable=True,
    )

    is_valid: Mapped[bool] = mapped_column(
        nullable=False
    )

    errors_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    validated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    validated_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )