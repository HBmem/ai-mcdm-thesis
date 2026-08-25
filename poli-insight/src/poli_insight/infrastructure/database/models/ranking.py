"""SQLAlchemy rows for immutable algorithm-neutral ranking evidence."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


class RankingRunRow(Base):
    __tablename__ = "ranking_runs"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "run_number",
            name="uq_ranking_runs_session_number",
        ),
        Index("ix_ranking_runs_session_status", "session_id", "status"),
        Index("ix_ranking_runs_source", "source_processing_run_id"),
        Index(
            "uq_ranking_runs_success_input",
            "input_hash",
            unique=True,
            sqlite_where=text("status = 'succeeded'"),
            postgresql_where=text("status = 'succeeded'"),
        ),
        CheckConstraint("run_number >= 1", name="ck_ranking_runs_number_positive"),
        CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_ranking_runs_status_allowed",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND output_hash IS NOT NULL "
            "AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(status = 'failed' AND output_hash IS NULL "
            "AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_ranking_runs_terminal_evidence",
        ),
    )

    ranking_run_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_processing_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("processing_runs.processing_run_id", ondelete="RESTRICT"),
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
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("scenario_snapshots.scenario_snapshot_id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    roster_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_implementation_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "algorithm_implementations.algorithm_implementation_id", ondelete="RESTRICT"
        ),
        nullable=False,
    )
    implementation_version: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(100), nullable=False)
    parameter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    environment_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    results: Mapped[list[RankingResultRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )
    artifacts: Mapped[list[RankingArtifactRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )


class RankingResultRow(Base):
    __tablename__ = "ranking_results"
    __table_args__ = (
        CheckConstraint(
            "level IN ('participant', 'stakeholder_group', 'session')",
            name="ck_ranking_results_level",
        ),
        CheckConstraint(
            "(level = 'participant' AND validation_id IS NOT NULL) OR "
            "(level != 'participant' AND validation_id IS NULL)",
            name="ck_ranking_results_validation_identity",
        ),
        CheckConstraint(
            "level != 'stakeholder_group' OR stakeholder_group_id IS NOT NULL",
            name="ck_ranking_results_group_identity",
        ),
        Index("ix_ranking_results_run_level", "ranking_run_id", "level"),
        Index(
            "uq_ranking_results_run_source",
            "ranking_run_id",
            "source_processing_matrix_id",
            unique=True,
        ),
    )

    ranking_result_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    ranking_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("ranking_runs.ranking_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_processing_matrix_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("processing_matrices.processing_matrix_id", ondelete="RESTRICT"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(String(50), nullable=False)
    stakeholder_group_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "session_stakeholder_groups.session_stakeholder_group_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    validation_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey("submission_validations.validation_id", ondelete="RESTRICT"),
        nullable=True,
    )
    alternatives_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    metric_label: Mapped[str] = mapped_column(String(100), nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[RankingRunRow] = relationship(back_populates="results", lazy="raise")


class RankingArtifactRow(Base):
    __tablename__ = "ranking_run_artifacts"
    __table_args__ = (
        Index("ix_ranking_artifacts_run_type", "ranking_run_id", "artifact_type"),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_ranking_artifacts_schema_positive",
        ),
    )

    ranking_artifact_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    ranking_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("ranking_runs.ranking_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[RankingRunRow] = relationship(back_populates="artifacts", lazy="raise")
