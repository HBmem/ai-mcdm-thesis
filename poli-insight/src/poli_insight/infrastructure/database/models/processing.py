"""SQLAlchemy rows for versioned validation bundles."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


class ProcessingRunRow(Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        UniqueConstraint("session_id", "run_number", name="uq_processing_runs_session_number"),
        CheckConstraint("run_number >= 1", name="ck_processing_runs_number_positive"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'canceled', 'awaiting_review', 'stale')",
            name="ck_processing_runs_status_allowed",
        ),
        Index("ix_processing_runs_session_status", "session_id", "status"),
    )

    processing_run_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("sessions.session_id", ondelete="RESTRICT"), nullable=False
    )
    configuration_version_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("session_configuration_versions.configuration_version_id", ondelete="RESTRICT"),
        nullable=False,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("scenario_snapshots.scenario_snapshot_id", ondelete="RESTRICT"), nullable=False
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    roster_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    environment_json: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    algorithm: Mapped[ProcessingRunAlgorithmRow] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise", uselist=False
    )
    submissions: Mapped[list[ProcessingRunSubmissionRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )
    matrices: Mapped[list[ProcessingMatrixRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )
    artifacts: Mapped[list[RunArtifactRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )


class ProcessingRunAlgorithmRow(Base):
    __tablename__ = "processing_run_algorithms"

    processing_run_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("processing_runs.processing_run_id", ondelete="RESTRICT"), primary_key=True
    )
    algorithm_implementation_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("algorithm_implementations.algorithm_implementation_id", ondelete="RESTRICT"), nullable=False
    )
    parameter_json: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=False)

    run: Mapped[ProcessingRunRow] = relationship(back_populates="algorithm", lazy="raise")


class ProcessingRunSubmissionRow(Base):
    __tablename__ = "processing_run_submissions"
    __table_args__ = (
        UniqueConstraint("processing_run_id", "participant_id", name="uq_processing_run_participant"),
        CheckConstraint(
            "inclusion_status IN ('pending_review', 'included', 'excluded_invalid', 'excluded_superseded', 'excluded_withdrawn', 'excluded_disabled', 'excluded_cutoff', 'excluded_moderator', 'excluded_error')",
            name="ck_processing_run_submissions_status",
        ),
    )

    processing_run_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("processing_runs.processing_run_id", ondelete="RESTRICT"), primary_key=True
    )
    submission_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("submissions.submission_id", ondelete="RESTRICT"), primary_key=True
    )
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("participants.participant_id", ondelete="RESTRICT"), nullable=False
    )
    stakeholder_group_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("session_stakeholder_groups.session_stakeholder_group_id", ondelete="RESTRICT"), nullable=False
    )
    validation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(), ForeignKey("submission_validations.validation_id", ondelete="RESTRICT"), nullable=True
    )
    inclusion_status: Mapped[str] = mapped_column(String(50), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    run: Mapped[ProcessingRunRow] = relationship(back_populates="submissions", lazy="raise")


class ProcessingMatrixRow(Base):
    __tablename__ = "processing_matrices"
    __table_args__ = (
        CheckConstraint(
            "level IN ('participant', 'stakeholder_group', 'session')",
            name="ck_processing_matrices_level",
        ),
        Index("ix_processing_matrices_run_level", "processing_run_id", "level"),
    )

    processing_matrix_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    processing_run_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("processing_runs.processing_run_id", ondelete="RESTRICT"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(50), nullable=False)
    stakeholder_group_id: Mapped[UUID | None] = mapped_column(
        UUIDString(), ForeignKey("session_stakeholder_groups.session_stakeholder_group_id", ondelete="RESTRICT"), nullable=True
    )
    validation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(), ForeignKey("submission_validations.validation_id", ondelete="RESTRICT"), nullable=True
    )
    criterion_ids_json: Mapped[list[str]] = mapped_column(JSON(none_as_null=True), nullable=False)
    matrix_json: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=False)
    weights_json: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=False)
    matrix_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[ProcessingRunRow] = relationship(back_populates="matrices", lazy="raise")


class RunArtifactRow(Base):
    __tablename__ = "run_artifacts"
    __table_args__ = (Index("ix_run_artifacts_run_type", "processing_run_id", "artifact_type"),)

    run_artifact_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    processing_run_id: Mapped[UUID] = mapped_column(
        UUIDString(), ForeignKey("processing_runs.processing_run_id", ondelete="RESTRICT"), nullable=False
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON(none_as_null=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[ProcessingRunRow] = relationship(back_populates="artifacts", lazy="raise")

