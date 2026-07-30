"""SQLAlchemy rows for sessions and immutable configuration versions."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poli_insight.domain.enum import (
    AccessCodeMode,
    AlgorithmRole,
    Discoverability,
    EnrollmentMode,
    MissingGroupPolicy,
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    SessionStatus,
    StakeholderSelectionMode,
)
from poli_insight.domain.session import DEFAULT_ALLOCATION_TOTAL_UNITS
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


NUMERIC_PRECISION = 38
NUMERIC_SCALE = 18


def _enum_sql_values(enum_type: type[StrEnum]) -> str:
    """Return trusted enum values formatted for a SQL CHECK constraint."""

    return ", ".join(f"'{member.value}'" for member in enum_type)


class SessionRow(Base):
    """Mutable operational shell for one decision session."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint(
            "public_slug",
            name="uq_sessions_public_slug",
        ),
        ForeignKeyConstraint(
            ["session_id", "active_configuration_version_id"],
            [
                "session_configuration_versions.session_id",
                "session_configuration_versions.configuration_version_id",
            ],
            name="fk_sessions_active_config_same_session",
            ondelete="RESTRICT",
            use_alter=True,
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_values(SessionStatus)})",
            name="ck_sessions_status_allowed",
        ),
        CheckConstraint(
            f"discoverability IN ({_enum_sql_values(Discoverability)})",
            name="ck_sessions_discoverability_allowed",
        ),
        CheckConstraint(
            f"enrollment_mode IN ({_enum_sql_values(EnrollmentMode)})",
            name="ck_sessions_enrollment_mode_allowed",
        ),
        CheckConstraint(
            f"access_code_mode IN ({_enum_sql_values(AccessCodeMode)})",
            name="ck_sessions_access_code_mode_allowed",
        ),
        CheckConstraint(
            "stakeholder_selection_mode IN "
            f"({_enum_sql_values(StakeholderSelectionMode)})",
            name="ck_sessions_stakeholder_selection_allowed",
        ),
        CheckConstraint(
            "closes_at IS NULL OR opens_at IS NULL OR closes_at > opens_at",
            name="ck_sessions_schedule_order",
        ),
        CheckConstraint(
            "updated_at >= created_at",
            name="ck_sessions_update_not_before_create",
        ),
        CheckConstraint(
            "status <> 'scheduled' OR opens_at IS NOT NULL",
            name="ck_sessions_scheduled_has_opens_at",
        ),
        CheckConstraint(
            "status NOT IN ('open', 'paused', 'closed') "
            "OR opened_at IS NOT NULL",
            name="ck_sessions_active_history_has_opened_at",
        ),
        CheckConstraint(
            "status <> 'paused' OR paused_at IS NOT NULL",
            name="ck_sessions_paused_has_timestamp",
        ),
        CheckConstraint(
            "status <> 'closed' OR closed_at IS NOT NULL",
            name="ck_sessions_closed_has_timestamp",
        ),
        CheckConstraint(
            "status <> 'canceled' OR canceled_at IS NOT NULL",
            name="ck_sessions_canceled_has_timestamp",
        ),
        CheckConstraint(
            "status <> 'archived' OR "
            "(archived_at IS NOT NULL "
            "AND (closed_at IS NOT NULL OR canceled_at IS NOT NULL))",
            name="ck_sessions_archived_has_history",
        ),
        CheckConstraint(
            "access_code_mode <> 'per_invitation_code' "
            "OR enrollment_mode = 'invitation_only'",
            name="ck_sessions_invitation_code_requires_invite",
        ),
        CheckConstraint(
            "length(trim(public_slug)) > 0",
            name="ck_sessions_public_slug_nonempty",
        ),
        CheckConstraint(
            "length(trim(title)) > 0",
            name="ck_sessions_title_nonempty",
        ),
        CheckConstraint(
            "length(trim(identity_policy)) > 0",
            name="ck_sessions_identity_policy_nonempty",
        ),
        Index("ix_sessions_scenario_snapshot_id", "scenario_snapshot_id"),
        Index("ix_sessions_status", "status"),
        Index("ix_sessions_opens_at", "opens_at"),
        Index("ix_sessions_closes_at", "closes_at"),
        Index(
            "ix_sessions_active_configuration_id",
            "active_configuration_version_id",
        ),
    )

    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_sessions_scenario_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    public_slug: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    admin_notes: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    discoverability: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    enrollment_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    access_code_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    identity_policy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    stakeholder_selection_mode: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    opens_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    closes_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    opened_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    canceled_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    active_configuration_version_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
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

    configurations: Mapped[list[SessionConfigurationVersionRow]] = relationship(
        back_populates="session",
        primaryjoin=(
            "SessionRow.session_id == "
            "SessionConfigurationVersionRow.session_id"
        ),
        foreign_keys="SessionConfigurationVersionRow.session_id",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="SessionConfigurationVersionRow.version_number",
    )


class AlgorithmImplementationRow(Base):
    """Versioned registry entry for an executable algorithm adapter."""

    __tablename__ = "algorithm_implementations"
    __table_args__ = (
        UniqueConstraint(
            "algorithm_implementation_id",
            "role",
            name="uq_algorithm_impl_id_role",
        ),
        UniqueConstraint(
            "stable_key",
            "provider",
            "library_name",
            "library_version",
            "implementation_version",
            "adapter_version",
            name="uq_algorithm_impl_version_identity",
        ),
        CheckConstraint(
            f"role IN ({_enum_sql_values(AlgorithmRole)})",
            name="ck_algorithm_impl_role_allowed",
        ),
        CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_algorithm_impl_status_allowed",
        ),
        CheckConstraint(
            "length(trim(stable_key)) > 0",
            name="ck_algorithm_impl_stable_key_nonempty",
        ),
        CheckConstraint(
            "length(trim(provider)) > 0",
            name="ck_algorithm_impl_provider_nonempty",
        ),
        CheckConstraint(
            "length(trim(implementation_version)) > 0",
            name="ck_algorithm_impl_version_nonempty",
        ),
        Index("ix_algorithm_impl_stable_role", "stable_key", "role"),
        Index("ix_algorithm_impl_status", "status"),
    )

    algorithm_implementation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    stable_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    conceptual_method: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    library_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    library_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    implementation_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    adapter_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    parameter_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    capabilities_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )


class SessionConfigurationVersionRow(Base):
    """Immutable calculation and submission rules for one session version."""

    __tablename__ = "session_configuration_versions"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "configuration_version_id",
            name="uq_session_configs_session_id",
        ),
        UniqueConstraint(
            "session_id",
            "version_number",
            name="uq_session_configs_session_version",
        ),
        UniqueConstraint(
            "session_id",
            "config_hash",
            name="uq_session_configs_session_hash",
        ),
        CheckConstraint(
            f"response_format IN ({_enum_sql_values(ResponseFormat)})",
            name="ck_session_configs_response_format_allowed",
        ),
        CheckConstraint(
            "response_target_type IN "
            f"({_enum_sql_values(ResponseTargetType)})",
            name="ck_session_configs_target_type_allowed",
        ),
        CheckConstraint(
            "missing_group_policy IN "
            f"({_enum_sql_values(MissingGroupPolicy)})",
            name="ck_session_configs_missing_group_allowed",
        ),
        CheckConstraint(
            "version_number >= 1",
            name="ck_session_configs_version_positive",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_session_configs_schema_version_positive",
        ),
        CheckConstraint(
            "minimum_valid_submissions >= 1",
            name="ck_session_configs_minimum_valid_positive",
        ),
        CheckConstraint(
            "allocation_total_units > 0",
            name="ck_session_configs_allocation_total_positive",
        ),
        CheckConstraint(
            "(NOT allow_resubmissions "
            "AND max_submissions_per_participant = 1) "
            "OR (allow_resubmissions "
            "AND max_submissions_per_participant >= 2)",
            name="ck_session_configs_resubmission_limit",
        ),
        CheckConstraint(
            "consistency_threshold IS NULL OR "
            "(consistency_threshold >= 0 AND consistency_threshold <= 1)",
            name="ck_session_configs_consistency_range",
        ),
        CheckConstraint(
            "length(config_hash) = 64 AND config_hash = lower(config_hash)",
            name="ck_session_configs_hash_format",
        ),
        CheckConstraint(
            "(activated_at IS NULL AND activated_by IS NULL) OR "
            "(activated_at IS NOT NULL AND activated_by IS NOT NULL)",
            name="ck_session_configs_activation_pair",
        ),
        CheckConstraint(
            "activated_at IS NULL OR activated_at >= created_at",
            name="ck_session_configs_activation_order",
        ),
        Index(
            "ix_session_configs_session_activated",
            "session_id",
            "activated_at",
        ),
        Index("ix_session_configs_snapshot_id", "scenario_snapshot_id"),
        Index("ix_session_configs_scale_id", "scale_id"),
    )

    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "sessions.session_id",
            name="fk_session_configs_session_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_session_configs_snapshot_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    response_format: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    response_target_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    scale_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_scales.scale_id",
            name="fk_session_configs_scale_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    allow_resubmissions: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    max_submissions_per_participant: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    allow_incomplete_submission: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    minimum_valid_submissions: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    missing_group_policy: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    required_group_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    consistency_threshold: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    configuration_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    config_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    allocation_total_units: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=DEFAULT_ALLOCATION_TOTAL_UNITS,
        server_default=str(DEFAULT_ALLOCATION_TOTAL_UNITS),
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    activated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    activated_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    session: Mapped[SessionRow] = relationship(
        back_populates="configurations",
        primaryjoin=(
            "SessionConfigurationVersionRow.session_id == "
            "SessionRow.session_id"
        ),
        foreign_keys=[session_id],
        lazy="raise",
    )
    stakeholder_groups: Mapped[list[SessionStakeholderGroupRow]] = relationship(
        back_populates="configuration",
        foreign_keys="SessionStakeholderGroupRow.configuration_version_id",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="SessionStakeholderGroupRow.display_order",
    )
    algorithm_configs: Mapped[list[SessionAlgorithmConfigRow]] = relationship(
        back_populates="configuration",
        foreign_keys="SessionAlgorithmConfigRow.configuration_version_id",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by=(
            "SessionAlgorithmConfigRow.role, "
            "SessionAlgorithmConfigRow.execution_order"
        ),
    )
    question_definitions: Mapped[list[ResponseQuestionDefinitionRow]] = relationship(
        back_populates="configuration",
        foreign_keys="ResponseQuestionDefinitionRow.configuration_version_id",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="ResponseQuestionDefinitionRow.display_order",
    )


class SessionAlgorithmConfigRow(Base):
    """Frozen algorithm selection and parameters for one configuration."""

    __tablename__ = "session_algorithm_configs"
    __table_args__ = (
        UniqueConstraint(
            "configuration_version_id",
            "session_algorithm_config_id",
            name="uq_session_algorithm_configs_config_id",
        ),
        UniqueConstraint(
            "configuration_version_id",
            "role",
            "execution_order",
            name="uq_session_algorithm_configs_role_order",
        ),
        ForeignKeyConstraint(
            ["algorithm_implementation_id", "role"],
            [
                "algorithm_implementations.algorithm_implementation_id",
                "algorithm_implementations.role",
            ],
            name="fk_session_algorithm_configs_impl_role",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"role IN ({_enum_sql_values(AlgorithmRole)})",
            name="ck_session_algorithm_configs_role_allowed",
        ),
        CheckConstraint(
            "execution_order >= 0",
            name="ck_session_algorithm_configs_order_nonnegative",
        ),
        CheckConstraint(
            "parameter_schema_version >= 1",
            name="ck_session_algorithm_configs_schema_positive",
        ),
        CheckConstraint(
            "length(parameter_hash) = 64 "
            "AND parameter_hash = lower(parameter_hash)",
            name="ck_session_algorithm_configs_hash_format",
        ),
        Index(
            "ix_session_algorithm_configs_impl_id",
            "algorithm_implementation_id",
        ),
    )

    session_algorithm_config_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "session_configuration_versions.configuration_version_id",
            name="fk_session_algorithm_configs_config_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    algorithm_implementation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    execution_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    parameter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    parameter_schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    parameter_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    configuration: Mapped[SessionConfigurationVersionRow] = relationship(
        back_populates="algorithm_configs",
        foreign_keys=[configuration_version_id],
        lazy="raise",
    )


class SessionStakeholderGroupRow(Base):
    """Exact stakeholder allocation belonging to one configuration version."""

    __tablename__ = "session_stakeholder_groups"
    __table_args__ = (
        UniqueConstraint(
            "configuration_version_id",
            "session_stakeholder_group_id",
            name="uq_session_groups_config_id",
        ),
        UniqueConstraint(
            "configuration_version_id",
            "group_key",
            name="uq_session_groups_config_key",
        ),
        UniqueConstraint(
            "configuration_version_id",
            "display_order",
            name="uq_session_groups_config_order",
        ),
        ForeignKeyConstraint(
            [
                "configuration_version_id",
                "within_group_algorithm_config_id",
            ],
            [
                "session_algorithm_configs.configuration_version_id",
                "session_algorithm_configs.session_algorithm_config_id",
            ],
            name="fk_session_groups_within_algorithm",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "allocation_units >= 0",
            name="ck_session_groups_allocation_nonnegative",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="ck_session_groups_order_nonnegative",
        ),
        CheckConstraint(
            "length(trim(group_key)) > 0",
            name="ck_session_groups_key_nonempty",
        ),
        CheckConstraint(
            "length(trim(name)) > 0",
            name="ck_session_groups_name_nonempty",
        ),
        Index(
            "ix_session_groups_config_active",
            "configuration_version_id",
            "is_active",
        ),
        Index(
            "ix_session_groups_within_algorithm_id",
            "within_group_algorithm_config_id",
        ),
    )

    session_stakeholder_group_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "session_configuration_versions.configuration_version_id",
            name="fk_session_groups_config_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    group_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    allocation_units: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    within_group_algorithm_config_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
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

    configuration: Mapped[SessionConfigurationVersionRow] = relationship(
        back_populates="stakeholder_groups",
        foreign_keys=[configuration_version_id],
        lazy="raise",
    )


class ResponseQuestionDefinitionRow(Base):
    """Queryable definition of one exact participant response target."""

    __tablename__ = "response_question_definitions"
    __table_args__ = (
        UniqueConstraint(
            "configuration_version_id",
            "question_key",
            name="uq_response_questions_config_key",
        ),
        UniqueConstraint(
            "configuration_version_id",
            "display_order",
            name="uq_response_questions_config_order",
        ),
        UniqueConstraint(
            "configuration_version_id",
            "left_criterion_id",
            "right_criterion_id",
            name="uq_response_questions_config_pair",
        ),
        CheckConstraint(
            f"question_type IN ({_enum_sql_values(QuestionType)})",
            name="ck_response_questions_type_allowed",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="ck_response_questions_order_nonnegative",
        ),
        CheckConstraint(
            "length(trim(question_key)) > 0",
            name="ck_response_questions_key_nonempty",
        ),
        CheckConstraint(
            "length(trim(prompt_snapshot)) > 0",
            name="ck_response_questions_prompt_nonempty",
        ),
        CheckConstraint(
            "(question_type = 'criterion_pair' "
            "AND criterion_id IS NULL "
            "AND left_criterion_id IS NOT NULL "
            "AND right_criterion_id IS NOT NULL "
            "AND left_criterion_id < right_criterion_id "
            "AND alternative_id IS NULL "
            "AND scale_id IS NOT NULL) "
            "OR (question_type = 'criterion_rating' "
            "AND criterion_id IS NOT NULL "
            "AND left_criterion_id IS NULL "
            "AND right_criterion_id IS NULL "
            "AND alternative_id IS NULL "
            "AND scale_id IS NOT NULL) "
            "OR (question_type = 'alternative_rating' "
            "AND criterion_id IS NULL "
            "AND left_criterion_id IS NULL "
            "AND right_criterion_id IS NULL "
            "AND alternative_id IS NOT NULL "
            "AND scale_id IS NOT NULL) "
            "OR (question_type = 'alternative_rank' "
            "AND criterion_id IS NULL "
            "AND left_criterion_id IS NULL "
            "AND right_criterion_id IS NULL "
            "AND alternative_id IS NOT NULL "
            "AND scale_id IS NULL)",
            name="ck_response_questions_target_shape",
        ),
        Index(
            "ix_response_questions_config_type",
            "configuration_version_id",
            "question_type",
        ),
        Index("ix_response_questions_criterion_id", "criterion_id"),
        Index("ix_response_questions_alternative_id", "alternative_id"),
    )

    question_definition_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "session_configuration_versions.configuration_version_id",
            name="fk_response_questions_config_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    question_key: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )
    question_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    criterion_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_criteria.criterion_id",
            name="fk_response_questions_criterion_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    left_criterion_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_criteria.criterion_id",
            name="fk_response_questions_left_criterion_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    right_criterion_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_criteria.criterion_id",
            name="fk_response_questions_right_criterion_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    alternative_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_alternatives.alternative_id",
            name="fk_response_questions_alternative_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    scale_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_scales.scale_id",
            name="fk_response_questions_scale_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    prompt_snapshot: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    configuration: Mapped[SessionConfigurationVersionRow] = relationship(
        back_populates="question_definitions",
        foreign_keys=[configuration_version_id],
        lazy="raise",
    )
