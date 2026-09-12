"""SQLAlchemy rows for immutable analysis evidence."""

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


class AnalysisRunRow(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_processing_run_id",
            "run_number",
            name="uq_analysis_runs_processing_number",
        ),
        Index("ix_analysis_runs_session_method", "session_id", "method"),
        Index("ix_analysis_runs_ranking", "source_ranking_run_id"),
        Index("ix_analysis_runs_correlation", "correlation_id"),
        Index(
            "uq_analysis_runs_success_input",
            "input_hash",
            unique=True,
            sqlite_where=text("status = 'succeeded'"),
            postgresql_where=text("status = 'succeeded'"),
        ),
        CheckConstraint("run_number >= 1", name="ck_analysis_runs_number_positive"),
        CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_analysis_runs_status"
        ),
        CheckConstraint(
            "(method = 'one_at_a_time_weight_perturbation' AND analysis_type = 'sensitivity') OR "
            "(method IN ('criterion_removal', 'rank_reversal') AND analysis_type = 'robustness') OR "
            "(method = 'stakeholder_group_influence' AND analysis_type = 'stakeholder_comparison') OR "
            "(method = 'participant_influence' AND analysis_type = 'participant_impact')",
            name="ck_analysis_runs_method_type",
        ),
        CheckConstraint(
            "(status = 'succeeded' AND output_hash IS NOT NULL AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(status = 'failed' AND output_hash IS NULL AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_analysis_runs_terminal_evidence",
        ),
    )

    analysis_run_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
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
    source_ranking_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("ranking_runs.ranking_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    method: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    source_processing_output_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    source_ranking_output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parameter_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    environment_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(100), nullable=False)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text(), nullable=True)

    cases: Mapped[list[AnalysisCaseRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )
    artifacts: Mapped[list[AnalysisArtifactRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )


class AnalysisCaseRow(Base):
    __tablename__ = "analysis_cases"
    __table_args__ = (
        UniqueConstraint(
            "analysis_run_id", "sequence", name="uq_analysis_cases_run_sequence"
        ),
        Index(
            "ix_analysis_cases_run_scope", "analysis_run_id", "scope_type", "scope_id"
        ),
        Index(
            "ix_analysis_cases_run_subject",
            "analysis_run_id",
            "subject_type",
            "subject_id",
        ),
        CheckConstraint("sequence >= 1", name="ck_analysis_cases_sequence_positive"),
        CheckConstraint(
            "status IN ('evaluated', 'not_evaluable')", name="ck_analysis_cases_status"
        ),
    )

    analysis_case_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    analysis_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("analysis_runs.analysis_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(50), nullable=False)
    scope_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    warnings_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[AnalysisRunRow] = relationship(back_populates="cases", lazy="raise")


class AnalysisArtifactRow(Base):
    __tablename__ = "analysis_artifacts"
    __table_args__ = (
        Index("ix_analysis_artifacts_run_type", "analysis_run_id", "artifact_type"),
        CheckConstraint(
            "schema_version >= 1", name="ck_analysis_artifacts_schema_positive"
        ),
    )

    analysis_artifact_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    analysis_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("analysis_runs.analysis_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[AnalysisRunRow] = relationship(back_populates="artifacts", lazy="raise")
