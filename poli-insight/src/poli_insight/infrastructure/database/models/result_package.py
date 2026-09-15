"""SQLAlchemy rows for immutable final-result packages."""

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


class ResultPackageRunRow(Base):
    __tablename__ = "result_package_runs"
    __table_args__ = (
        UniqueConstraint("session_id", "run_number", name="uq_result_packages_number"),
        Index("ix_result_packages_session_status", "session_id", "status"),
        Index("ix_result_packages_ranking", "source_ranking_run_id"),
        Index(
            "uq_result_packages_success_input",
            "input_hash",
            unique=True,
            sqlite_where=text("status = 'succeeded'"),
            postgresql_where=text("status = 'succeeded'"),
        ),
        CheckConstraint("run_number >= 1", name="ck_result_packages_number_positive"),
        CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_result_packages_status"
        ),
        CheckConstraint(
            "(status = 'succeeded' AND output_hash IS NOT NULL "
            "AND failure_code IS NULL AND failure_detail IS NULL) OR "
            "(status = 'failed' AND output_hash IS NULL "
            "AND failure_code IS NOT NULL AND failure_detail IS NOT NULL)",
            name="ck_result_packages_terminal_evidence",
        ),
    )

    package_run_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
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
    source_analysis_run_ids_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    variants_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    source_roster_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_processing_output_hash: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    source_ranking_output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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

    artifacts: Mapped[list[ResultPackageArtifactRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )
    subjects: Mapped[list[ResultPackageSubjectRow]] = relationship(
        back_populates="run", cascade="save-update, merge", lazy="raise"
    )


class ResultPackageArtifactRow(Base):
    __tablename__ = "result_package_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "package_run_id", "sequence", name="uq_result_package_artifacts_sequence"
        ),
        Index("ix_result_package_artifacts_variant", "package_run_id", "variant"),
        CheckConstraint(
            "sequence >= 1 AND schema_version >= 1",
            name="ck_result_package_artifacts_positive",
        ),
        CheckConstraint(
            "artifact_type IN ('input_manifest', 'common_section', 'variant_manifest')",
            name="ck_result_package_artifacts_type",
        ),
        CheckConstraint(
            "(artifact_type = 'variant_manifest' AND variant IN ('anonymous', 'public')) "
            "OR (artifact_type != 'variant_manifest' AND variant IS NULL)",
            name="ck_result_package_artifacts_variant",
        ),
    )

    package_artifact_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    package_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("result_package_runs.package_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    variant: Mapped[str | None] = mapped_column(String(30), nullable=True)
    content_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[ResultPackageRunRow] = relationship(
        back_populates="artifacts", lazy="raise"
    )


class ResultPackageSubjectRow(Base):
    __tablename__ = "result_package_subjects"
    __table_args__ = (
        UniqueConstraint(
            "package_run_id", "sequence", name="uq_result_package_subjects_sequence"
        ),
        UniqueConstraint(
            "package_run_id", "subject_key", name="uq_result_package_subjects_key"
        ),
        UniqueConstraint(
            "package_run_id",
            "participant_id",
            name="uq_result_package_subjects_participant",
        ),
        Index("ix_result_package_subjects_lookup", "package_run_id", "participant_id"),
        CheckConstraint("sequence >= 1", name="ck_result_package_subjects_positive"),
        CheckConstraint(
            "inclusion_status IN ('included', 'pending_review', 'excluded_invalid', "
            "'excluded_superseded', 'excluded_withdrawn', 'excluded_disabled', "
            "'excluded_cutoff', 'excluded_moderator', 'excluded_error')",
            name="ck_result_package_subjects_inclusion_status",
        ),
        CheckConstraint(
            "(inclusion_status = 'included' AND exclusion_reason IS NULL) OR "
            "(inclusion_status = 'pending_review') OR "
            "(inclusion_status NOT IN ('included', 'pending_review') "
            "AND exclusion_reason IS NOT NULL)",
            name="ck_result_package_subjects_exclusion",
        ),
    )

    package_subject_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    package_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("result_package_runs.package_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_key: Mapped[str] = mapped_column(String(100), nullable=False)
    participant_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("participants.participant_id", ondelete="RESTRICT"),
        nullable=False,
    )
    alias_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    stakeholder_group_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "session_stakeholder_groups.session_stakeholder_group_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    stakeholder_group_label: Mapped[str] = mapped_column(String(200), nullable=False)
    inclusion_status: Mapped[str] = mapped_column(String(50), nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
    result_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True), nullable=False
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[ResultPackageRunRow] = relationship(
        back_populates="subjects", lazy="raise"
    )


class ParticipantResultReleaseRow(Base):
    __tablename__ = "participant_result_releases"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "version_number", name="uq_participant_releases_version"
        ),
        Index(
            "uq_participant_releases_active",
            "session_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        CheckConstraint("version_number >= 1", name="ck_participant_releases_positive"),
        CheckConstraint(
            "status IN ('active', 'withdrawn')", name="ck_participant_releases_status"
        ),
        CheckConstraint(
            "(status = 'active' AND withdrawn_at IS NULL AND withdrawn_by IS NULL "
            "AND withdrawal_reason IS NULL) OR "
            "(status = 'withdrawn' AND withdrawn_at IS NOT NULL "
            "AND withdrawn_by IS NOT NULL AND withdrawal_reason IS NOT NULL)",
            name="ck_participant_releases_withdrawal",
        ),
    )

    release_id: Mapped[UUID] = mapped_column(UUIDString(), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("sessions.session_id", ondelete="RESTRICT"),
        nullable=False,
    )
    package_run_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("result_package_runs.package_run_id", ondelete="RESTRICT"),
        nullable=False,
    )
    package_artifact_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey("result_package_artifacts.package_artifact_id", ondelete="RESTRICT"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    released_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    released_by: Mapped[str] = mapped_column(String(100), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    withdrawn_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    withdrawal_reason: Mapped[str | None] = mapped_column(Text(), nullable=True)
