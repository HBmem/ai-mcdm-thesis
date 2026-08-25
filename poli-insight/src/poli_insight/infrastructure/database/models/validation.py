"""SQLAlchemy rows for immutable, versioned submission validation evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
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
    ActorType,
    MessageSeverity,
    ValidationStatus,
)
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString

if TYPE_CHECKING:
    from poli_insight.infrastructure.database.models.scenario import (
        ScenarioCriterionRow,
    )
    from poli_insight.infrastructure.database.models.session import (
        AlgorithmImplementationRow,
        ResponseQuestionDefinitionRow,
    )
    from poli_insight.infrastructure.database.models.submission import (
        SubmissionAnswerRow,
        SubmissionRow,
    )


NUMERIC_PRECISION = 38
NUMERIC_SCALE = 18


def _enum_sql_values(enum_type: type[StrEnum]) -> str:
    """Return trusted enum values formatted for a SQL CHECK constraint."""

    return ", ".join(f"'{member.value}'" for member in enum_type)


class SubmissionValidationRow(Base):
    """One reproducible validation attempt for immutable submission content."""

    __tablename__ = "submission_validations"
    __table_args__ = (
        UniqueConstraint(
            "submission_id",
            "validation_id",
            name="uq_submission_validations_submission_id",
        ),
        UniqueConstraint(
            "input_hash",
            "attempt_number",
            name="uq_submission_validations_input_attempt",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_values(ValidationStatus)})",
            name="ck_submission_validations_status_allowed",
        ),
        CheckConstraint(
            "validated_by_actor_type IS NULL OR "
            "validated_by_actor_type IN "
            f"({_enum_sql_values(ActorType)})",
            name="ck_submission_validations_actor_type_allowed",
        ),
        CheckConstraint(
            "completion_ratio >= 0 AND completion_ratio <= 1",
            name="ck_submission_validations_completion_range",
        ),
        CheckConstraint(
            "attempt_number >= 1",
            name="ck_submission_validations_attempt_positive",
        ),
        CheckConstraint(
            "consistency_ratio IS NULL OR consistency_ratio >= 0",
            name="ck_submission_validations_consistency_nonnegative",
        ),
        CheckConstraint(
            "length(answers_hash) = 64 "
            "AND answers_hash = lower(answers_hash)",
            name="ck_submission_validations_answers_hash_format",
        ),
        CheckConstraint(
            "length(configuration_hash) = 64 "
            "AND configuration_hash = lower(configuration_hash)",
            name="ck_submission_validations_config_hash_format",
        ),
        CheckConstraint(
            "length(parameter_hash) = 64 "
            "AND parameter_hash = lower(parameter_hash)",
            name="ck_submission_validations_parameter_hash_format",
        ),
        CheckConstraint(
            "length(input_hash) = 64 AND input_hash = lower(input_hash)",
            name="ck_submission_validations_input_hash_format",
        ),
        CheckConstraint(
            "output_hash IS NULL OR "
            "(length(output_hash) = 64 "
            "AND output_hash = lower(output_hash))",
            name="ck_submission_validations_output_hash_format",
        ),
        CheckConstraint(
            "length(trim(validator_version)) > 0",
            name="ck_submission_validations_version_nonempty",
        ),
        CheckConstraint(
            "validated_by_actor_id IS NULL OR "
            "length(trim(validated_by_actor_id)) > 0",
            name="ck_submission_validations_actor_id_nonempty",
        ),
        CheckConstraint(
            "failure_code IS NULL OR length(trim(failure_code)) > 0",
            name="ck_submission_validations_failure_code_nonempty",
        ),
        CheckConstraint(
            "failure_detail IS NULL OR length(trim(failure_detail)) > 0",
            name="ck_submission_validations_failure_detail_nonempty",
        ),
        CheckConstraint(
            "completed_at IS NULL OR "
            "(started_at IS NOT NULL AND completed_at >= started_at)",
            name="ck_submission_validations_completion_order",
        ),
        CheckConstraint(
            "(status = 'pending' "
            "AND started_at IS NULL "
            "AND completed_at IS NULL "
            "AND validated_by_actor_type IS NULL "
            "AND validated_by_actor_id IS NULL "
            "AND output_hash IS NULL "
            "AND failure_code IS NULL "
            "AND failure_detail IS NULL "
            "AND completion_ratio = 0 "
            "AND consistency_ratio IS NULL) "
            "OR (status = 'running' "
            "AND started_at IS NOT NULL "
            "AND completed_at IS NULL "
            "AND validated_by_actor_type IS NULL "
            "AND validated_by_actor_id IS NULL "
            "AND output_hash IS NULL "
            "AND failure_code IS NULL "
            "AND failure_detail IS NULL "
            "AND completion_ratio = 0 "
            "AND consistency_ratio IS NULL) "
            "OR (status IN ('valid', 'valid_with_warnings', 'invalid') "
            "AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL "
            "AND validated_by_actor_type IS NOT NULL "
            "AND validated_by_actor_id IS NOT NULL "
            "AND output_hash IS NOT NULL "
            "AND failure_code IS NULL "
            "AND failure_detail IS NULL) "
            "OR (status = 'error' "
            "AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL "
            "AND validated_by_actor_type IS NOT NULL "
            "AND validated_by_actor_id IS NOT NULL "
            "AND output_hash IS NOT NULL "
            "AND failure_code IS NOT NULL "
            "AND failure_detail IS NOT NULL "
            "AND consistency_ratio IS NULL)",
            name="ck_submission_validations_lifecycle_state",
        ),
        Index(
            "ix_submission_validations_submission_status",
            "submission_id",
            "status",
        ),
        Index(
            "ix_submission_validations_implementation_id",
            "validator_implementation_id",
        ),
        Index(
            "ix_submission_validations_completed_at",
            "completed_at",
        ),
        Index(
            "ix_submission_validations_input_hash",
            "input_hash",
        ),
        Index(
            "uq_submission_validations_active_input",
            "input_hash",
            unique=True,
            sqlite_where=text("status IN ('pending', 'running')"),
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
    )

    validation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    submission_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submissions.submission_id",
            name="fk_submission_validations_submission_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    answers_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    configuration_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    validator_implementation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "algorithm_implementations.algorithm_implementation_id",
            name="fk_submission_validations_validator_impl_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    validator_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    parameter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    parameter_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ValidationStatus.PENDING.value,
        server_default=ValidationStatus.PENDING.value,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    completion_ratio: Mapped[Decimal] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=False,
        default=Decimal(0),
        server_default="0",
    )
    consistency_ratio: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    quality_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )
    validated_by_actor_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )
    validated_by_actor_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    input_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    output_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    failure_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    submission: Mapped[SubmissionRow] = relationship(
        "SubmissionRow",
        foreign_keys=[submission_id],
        lazy="raise",
    )
    validator_implementation: Mapped[AlgorithmImplementationRow] = relationship(
        "AlgorithmImplementationRow",
        foreign_keys=[validator_implementation_id],
        lazy="raise",
    )
    messages: Mapped[list[ValidationMessageRow]] = relationship(
        back_populates="validation",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="ValidationMessageRow.display_order",
    )
    normalized_answers: Mapped[list[ValidationNormalizedAnswerRow]] = relationship(
        back_populates="validation",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="ValidationNormalizedAnswerRow.submission_answer_id",
    )
    prepared_matrix: Mapped[ValidationPreparedMatrixRow | None] = relationship(
        back_populates="validation",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        uselist=False,
    )
    criterion_weights: Mapped[list[ParticipantCriterionWeightRow]] = relationship(
        back_populates="validation",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
        order_by="ParticipantCriterionWeightRow.criterion_id",
    )


class ValidationPreparedMatrixRow(Base):
    """One immutable provider-neutral matrix for a validation result."""

    __tablename__ = "validation_prepared_matrices"
    __table_args__ = (
        CheckConstraint(
            "response_format IN ('direct_rating', 'pairwise')",
            name="ck_validation_prepared_matrices_response_format",
        ),
        CheckConstraint(
            "value_shape IN ('crisp', 'triangular_fuzzy')",
            name="ck_validation_prepared_matrices_value_shape",
        ),
        CheckConstraint(
            "length(matrix_hash) = 64 AND matrix_hash = lower(matrix_hash)",
            name="ck_validation_prepared_matrices_hash_format",
        ),
    )

    validation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submission_validations.validation_id",
            name="fk_validation_prepared_matrices_validation_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    response_format: Mapped[str] = mapped_column(String(50), nullable=False)
    value_shape: Mapped[str] = mapped_column(String(50), nullable=False)
    criterion_ids_json: Mapped[list[str]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    matrix_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    preparer_version: Mapped[str] = mapped_column(String(100), nullable=False)
    matrix_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    validation: Mapped[SubmissionValidationRow] = relationship(
        back_populates="prepared_matrix",
        foreign_keys=[validation_id],
        lazy="raise",
    )


class ValidationMessageRow(Base):
    """One structured, safely displayable validation finding."""

    __tablename__ = "validation_messages"
    __table_args__ = (
        UniqueConstraint(
            "validation_id",
            "display_order",
            name="uq_validation_messages_validation_order",
        ),
        CheckConstraint(
            f"severity IN ({_enum_sql_values(MessageSeverity)})",
            name="ck_validation_messages_severity_allowed",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="ck_validation_messages_order_nonnegative",
        ),
        CheckConstraint(
            "length(trim(code)) > 0 AND code = lower(code)",
            name="ck_validation_messages_code_format",
        ),
        CheckConstraint(
            "length(trim(safe_message)) > 0",
            name="ck_validation_messages_safe_message_nonempty",
        ),
        Index(
            "ix_validation_messages_validation_severity",
            "validation_id",
            "severity",
        ),
        Index(
            "ix_validation_messages_question_id",
            "question_definition_id",
        ),
    )

    validation_message_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    validation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submission_validations.validation_id",
            name="fk_validation_messages_validation_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    severity: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )
    question_definition_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "response_question_definitions.question_definition_id",
            name="fk_validation_messages_question_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    safe_message: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    parameters_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    validation: Mapped[SubmissionValidationRow] = relationship(
        back_populates="messages",
        foreign_keys=[validation_id],
        lazy="raise",
    )
    question_definition: Mapped[ResponseQuestionDefinitionRow | None] = relationship(
        "ResponseQuestionDefinitionRow",
        foreign_keys=[question_definition_id],
        lazy="raise",
    )


class ValidationNormalizedAnswerRow(Base):
    """One versioned normalized value derived from an authored answer."""

    __tablename__ = "validation_normalized_answers"
    __table_args__ = (
        CheckConstraint(
            "length(trim(normalizer_version)) > 0",
            name="ck_validation_normalized_answers_version_nonempty",
        ),
        CheckConstraint(
            "(crisp_value IS NOT NULL "
            "AND fuzzy_lower IS NULL "
            "AND fuzzy_middle IS NULL "
            "AND fuzzy_upper IS NULL) "
            "OR (crisp_value IS NULL "
            "AND fuzzy_lower IS NOT NULL "
            "AND fuzzy_middle IS NOT NULL "
            "AND fuzzy_upper IS NOT NULL) "
            "OR (crisp_value IS NULL "
            "AND fuzzy_lower IS NULL "
            "AND fuzzy_middle IS NULL "
            "AND fuzzy_upper IS NULL)",
            name="ck_validation_normalized_answers_numeric_shape",
        ),
        CheckConstraint(
            "fuzzy_lower IS NULL OR "
            "(fuzzy_lower <= fuzzy_middle AND fuzzy_middle <= fuzzy_upper)",
            name="ck_validation_normalized_answers_fuzzy_order",
        ),
        Index(
            "ix_validation_normalized_answers_answer_id",
            "submission_answer_id",
        ),
    )

    validation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submission_validations.validation_id",
            name="fk_validation_normalized_answers_validation_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    submission_answer_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submission_answers.submission_answer_id",
            name="fk_validation_normalized_answers_answer_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    normalized_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    normalizer_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    crisp_value: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    fuzzy_lower: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    fuzzy_middle: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    fuzzy_upper: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )

    validation: Mapped[SubmissionValidationRow] = relationship(
        back_populates="normalized_answers",
        foreign_keys=[validation_id],
        lazy="raise",
    )
    submission_answer: Mapped[SubmissionAnswerRow] = relationship(
        "SubmissionAnswerRow",
        foreign_keys=[submission_answer_id],
        lazy="raise",
    )


class ParticipantCriterionWeightRow(Base):
    """One normalized crisp or triangular-fuzzy participant weight."""

    __tablename__ = "participant_criterion_weights"
    __table_args__ = (
        CheckConstraint(
            "(crisp_weight IS NOT NULL "
            "AND fuzzy_lower IS NULL "
            "AND fuzzy_middle IS NULL "
            "AND fuzzy_upper IS NULL) "
            "OR (crisp_weight IS NULL "
            "AND fuzzy_lower IS NOT NULL "
            "AND fuzzy_middle IS NOT NULL "
            "AND fuzzy_upper IS NOT NULL)",
            name="ck_participant_criterion_weights_value_shape",
        ),
        CheckConstraint(
            "crisp_weight IS NULL OR crisp_weight >= 0",
            name="ck_participant_criterion_weights_crisp_nonnegative",
        ),
        CheckConstraint(
            "fuzzy_lower IS NULL OR "
            "(fuzzy_lower >= 0 "
            "AND fuzzy_middle >= 0 "
            "AND fuzzy_upper >= 0)",
            name="ck_participant_criterion_weights_fuzzy_nonnegative",
        ),
        CheckConstraint(
            "fuzzy_lower IS NULL OR "
            "(fuzzy_lower <= fuzzy_middle AND fuzzy_middle <= fuzzy_upper)",
            name="ck_participant_criterion_weights_fuzzy_order",
        ),
        Index(
            "ix_participant_criterion_weights_criterion_id",
            "criterion_id",
        ),
    )

    validation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "submission_validations.validation_id",
            name="fk_participant_criterion_weights_validation_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    criterion_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_criteria.criterion_id",
            name="fk_participant_criterion_weights_criterion_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    crisp_weight: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    fuzzy_lower: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    fuzzy_middle: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    fuzzy_upper: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    derivation_metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    validation: Mapped[SubmissionValidationRow] = relationship(
        back_populates="criterion_weights",
        foreign_keys=[validation_id],
        lazy="raise",
    )
    criterion: Mapped[ScenarioCriterionRow] = relationship(
        "ScenarioCriterionRow",
        foreign_keys=[criterion_id],
        lazy="raise",
    )
