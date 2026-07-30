"""SQLAlchemy rows for submissions, answers, and participant comments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poli_insight.domain.enum import (
    ResponseFormat,
    ResponseTargetType,
    SubmissionStatus,
)
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


NUMERIC_PRECISION = 38
NUMERIC_SCALE = 18
_COMMENT_MODERATION_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "redacted",
)


def _enum_sql_values(enum_type: type[StrEnum]) -> str:
    """Return trusted enum values formatted for a SQL CHECK constraint."""

    return ", ".join(f"'{member.value}'" for member in enum_type)


def _sql_values(values: tuple[str, ...]) -> str:
    """Return trusted local vocabulary values for a SQL CHECK constraint."""

    return ", ".join(f"'{value}'" for value in values)


class SubmissionRow(Base):
    """One immutable-after-finalization participant response attempt."""

    __tablename__ = "submissions"
    __table_args__ = (
        UniqueConstraint(
            "participant_id",
            "attempt_number",
            name="uq_submissions_participant_attempt",
        ),
        UniqueConstraint(
            "participant_id",
            "configuration_version_id",
            "submission_id",
            name="uq_submissions_participant_config_id",
        ),
        ForeignKeyConstraint(
            ["session_id", "participant_id"],
            ["participants.session_id", "participants.participant_id"],
            name="fk_submissions_session_participant",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["session_id", "configuration_version_id"],
            [
                "session_configuration_versions.session_id",
                "session_configuration_versions.configuration_version_id",
            ],
            name="fk_submissions_session_configuration",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["configuration_version_id", "session_stakeholder_group_id"],
            [
                "session_stakeholder_groups.configuration_version_id",
                "session_stakeholder_groups.session_stakeholder_group_id",
            ],
            name="fk_submissions_configuration_group",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            [
                "participant_id",
                "configuration_version_id",
                "previous_submission_id",
            ],
            [
                "submissions.participant_id",
                "submissions.configuration_version_id",
                "submissions.submission_id",
            ],
            name="fk_submissions_same_scope_predecessor",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_values(SubmissionStatus)})",
            name="ck_submissions_status_allowed",
        ),
        CheckConstraint(
            f"response_format IN ({_enum_sql_values(ResponseFormat)})",
            name="ck_submissions_response_format_allowed",
        ),
        CheckConstraint(
            "response_target_type IN "
            f"({_enum_sql_values(ResponseTargetType)})",
            name="ck_submissions_target_type_allowed",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_submissions_attempt_positive",
        ),
        CheckConstraint(
            "(attempt_number = 1 AND previous_submission_id IS NULL) "
            "OR (attempt_number > 1 AND previous_submission_id IS NOT NULL)",
            name="ck_submissions_predecessor_shape",
        ),
        CheckConstraint(
            "previous_submission_id IS NULL "
            "OR previous_submission_id <> submission_id",
            name="ck_submissions_predecessor_not_self",
        ),
        CheckConstraint(
            "answer_schema_version IS NULL OR answer_schema_version >= 1",
            name="ck_submissions_answer_schema_positive",
        ),
        CheckConstraint(
            "answers_hash IS NULL OR "
            "(length(answers_hash) = 64 AND answers_hash = lower(answers_hash))",
            name="ck_submissions_answers_hash_format",
        ),
        CheckConstraint(
            "(status = 'draft' "
            "AND answer_manifest_json IS NULL "
            "AND answer_schema_version IS NULL "
            "AND answers_hash IS NULL "
            "AND submitted_at IS NULL "
            "AND submitted_by IS NULL) "
            "OR (status <> 'draft' "
            "AND answer_manifest_json IS NOT NULL "
            "AND answer_schema_version IS NOT NULL "
            "AND answers_hash IS NOT NULL "
            "AND submitted_at IS NOT NULL "
            "AND submitted_by IS NOT NULL)",
            name="ck_submissions_finalization_state",
        ),
        CheckConstraint(
            "(status = 'superseded' "
            "AND superseded_at IS NOT NULL "
            "AND superseded_by IS NOT NULL) "
            "OR (status <> 'superseded' "
            "AND superseded_at IS NULL "
            "AND superseded_by IS NULL)",
            name="ck_submissions_supersession_state",
        ),
        CheckConstraint(
            "(status = 'withdrawn' "
            "AND withdrawn_at IS NOT NULL "
            "AND withdrawn_by IS NOT NULL "
            "AND withdrawal_reason IS NOT NULL) "
            "OR (status <> 'withdrawn' "
            "AND withdrawn_at IS NULL "
            "AND withdrawn_by IS NULL "
            "AND withdrawal_reason IS NULL)",
            name="ck_submissions_withdrawal_state",
        ),
        CheckConstraint(
            "started_at >= created_at",
            name="ck_submissions_start_order",
        ),
        CheckConstraint(
            "last_saved_at >= started_at",
            name="ck_submissions_save_order",
        ),
        CheckConstraint(
            "updated_at >= last_saved_at",
            name="ck_submissions_update_order",
        ),
        CheckConstraint(
            "submitted_at IS NULL OR submitted_at = last_saved_at",
            name="ck_submissions_submit_freezes_save_time",
        ),
        CheckConstraint(
            "superseded_at IS NULL OR "
            "(submitted_at IS NOT NULL AND superseded_at >= submitted_at)",
            name="ck_submissions_supersession_order",
        ),
        CheckConstraint(
            "withdrawn_at IS NULL OR "
            "(submitted_at IS NOT NULL AND withdrawn_at >= submitted_at)",
            name="ck_submissions_withdrawal_order",
        ),
        CheckConstraint(
            "length(trim(created_by)) > 0",
            name="ck_submissions_creator_nonempty",
        ),
        CheckConstraint(
            "length(trim(updated_by)) > 0",
            name="ck_submissions_updater_nonempty",
        ),
        CheckConstraint(
            "submitted_by IS NULL OR length(trim(submitted_by)) > 0",
            name="ck_submissions_submitter_nonempty",
        ),
        CheckConstraint(
            "superseded_by IS NULL OR length(trim(superseded_by)) > 0",
            name="ck_submissions_superseder_nonempty",
        ),
        CheckConstraint(
            "withdrawn_by IS NULL OR length(trim(withdrawn_by)) > 0",
            name="ck_submissions_withdrawer_nonempty",
        ),
        CheckConstraint(
            "withdrawal_reason IS NULL "
            "OR length(trim(withdrawal_reason)) > 0",
            name="ck_submissions_withdrawal_reason_nonempty",
        ),
        Index(
            "uq_submissions_participant_draft",
            "participant_id",
            unique=True,
            postgresql_where=text("status = 'draft'"),
            sqlite_where=text("status = 'draft'"),
        ),
        Index(
            "uq_submissions_participant_effective",
            "participant_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
            sqlite_where=text("status = 'submitted'"),
        ),
        Index("ix_submissions_session_status", "session_id", "status"),
        Index(
            "ix_submissions_participant_status",
            "participant_id",
            "status",
        ),
        Index(
            "ix_submissions_configuration_group",
            "configuration_version_id",
            "session_stakeholder_group_id",
        ),
        Index("ix_submissions_submitted_at", "submitted_at"),
        Index("ix_submissions_previous_id", "previous_submission_id"),
    )

    submission_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_submissions_scenario_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    session_stakeholder_group_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    previous_submission_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=SubmissionStatus.DRAFT.value,
        server_default=SubmissionStatus.DRAFT.value,
    )
    response_format: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    response_target_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    answer_manifest_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    answer_schema_version: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    answers_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    last_saved_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    submitted_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    superseded_by: Mapped[str | None] = mapped_column(
        String(100),
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
    client_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
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

    answers: Mapped[list[SubmissionAnswerRow]] = relationship(
        back_populates="submission",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="SubmissionAnswerRow.question_definition_id",
    )
    comments: Mapped[list[SubmissionCommentRow]] = relationship(
        back_populates="submission",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="SubmissionCommentRow.created_at",
    )


class SubmissionAnswerRow(Base):
    """Queryable answer evidence belonging to one submission attempt."""

    __tablename__ = "submission_answers"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "question_definition_id",
            name="uq_submission_answers_submission_question",
        ),
        CheckConstraint(
            "value_schema_version >= 1",
            name="ck_submission_answers_schema_positive",
        ),
        CheckConstraint(
            "length(raw_value_hash) = 64 "
            "AND raw_value_hash = lower(raw_value_hash)",
            name="ck_submission_answers_hash_format",
        ),
        CheckConstraint(
            "(selected_scale_value_id IS NOT NULL "
            "AND numeric_value IS NULL "
            "AND rank_value IS NULL) "
            "OR (selected_scale_value_id IS NULL "
            "AND numeric_value IS NOT NULL "
            "AND rank_value IS NULL) "
            "OR (selected_scale_value_id IS NULL "
            "AND numeric_value IS NULL "
            "AND rank_value IS NOT NULL)",
            name="ck_submission_answers_typed_value_shape",
        ),
        CheckConstraint(
            "rank_value IS NULL OR rank_value >= 1",
            name="ck_submission_answers_rank_positive",
        ),
        CheckConstraint(
            "response_time_ms IS NULL OR response_time_ms >= 0",
            name="ck_submission_answers_response_time_nonnegative",
        ),
        Index(
            "ix_submission_answers_question_id",
            "question_definition_id",
        ),
        Index(
            "ix_submission_answers_scale_value_id",
            "selected_scale_value_id",
        ),
    )

    submission_answer_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    submission_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submissions.submission_id",
            name="fk_submission_answers_submission_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    question_definition_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "response_question_definitions.question_definition_id",
            name="fk_submission_answers_question_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    raw_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    value_schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    raw_value_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    selected_scale_value_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_scale_values.scale_value_id",
            name="fk_submission_answers_scale_value_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    numeric_value: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    rank_value: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    answered_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    response_time_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    submission: Mapped[SubmissionRow] = relationship(
        back_populates="answers",
        foreign_keys=[submission_id],
        lazy="raise",
    )


class SubmissionCommentRow(Base):
    """Participant comment with explicit audience and moderation state."""

    __tablename__ = "submission_comments"
    __table_args__ = (
        CheckConstraint(
            "length(trim(comment_text)) > 0",
            name="ck_submission_comments_text_nonempty",
        ),
        CheckConstraint(
            "length(trim(audience)) > 0",
            name="ck_submission_comments_audience_nonempty",
        ),
        CheckConstraint(
            "moderation_status IN "
            f"({_sql_values(_COMMENT_MODERATION_STATUSES)})",
            name="ck_submission_comments_moderation_allowed",
        ),
        CheckConstraint(
            "criterion_id IS NULL OR alternative_id IS NULL",
            name="ck_submission_comments_single_target",
        ),
        CheckConstraint(
            "(moderation_status = 'redacted' "
            "AND redacted_text IS NOT NULL "
            "AND redacted_at IS NOT NULL "
            "AND redacted_by IS NOT NULL "
            "AND redaction_reason IS NOT NULL) "
            "OR (moderation_status <> 'redacted' "
            "AND redacted_text IS NULL "
            "AND redacted_at IS NULL "
            "AND redacted_by IS NULL "
            "AND redaction_reason IS NULL)",
            name="ck_submission_comments_redaction_state",
        ),
        CheckConstraint(
            "redacted_text IS NULL OR length(trim(redacted_text)) > 0",
            name="ck_submission_comments_redacted_text_nonempty",
        ),
        CheckConstraint(
            "redacted_by IS NULL OR length(trim(redacted_by)) > 0",
            name="ck_submission_comments_redactor_nonempty",
        ),
        CheckConstraint(
            "redaction_reason IS NULL "
            "OR length(trim(redaction_reason)) > 0",
            name="ck_submission_comments_redaction_reason_nonempty",
        ),
        CheckConstraint(
            "redacted_at IS NULL OR redacted_at >= created_at",
            name="ck_submission_comments_redaction_order",
        ),
        Index("ix_submission_comments_submission_id", "submission_id"),
        Index("ix_submission_comments_criterion_id", "criterion_id"),
        Index("ix_submission_comments_alternative_id", "alternative_id"),
        Index(
            "ix_submission_comments_moderation_status",
            "moderation_status",
        ),
    )

    submission_comment_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    submission_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submissions.submission_id",
            name="fk_submission_comments_submission_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    criterion_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_criteria.criterion_id",
            name="fk_submission_comments_criterion_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    alternative_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_alternatives.alternative_id",
            name="fk_submission_comments_alternative_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    comment_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    audience: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    moderation_status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    redacted_text: Mapped[str | None] = mapped_column(
        Text,
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
    redaction_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )

    submission: Mapped[SubmissionRow] = relationship(
        back_populates="comments",
        foreign_keys=[submission_id],
        lazy="raise",
    )
