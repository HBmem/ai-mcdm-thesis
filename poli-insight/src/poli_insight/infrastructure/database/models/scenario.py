from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from poli_insight.domain.enum import (
    CriterionDataType,
    CriterionDirection,
    ScenarioDefinitionStatus,
    ScenarioFileRole,
    ScenarioSnapshotStatus,
    ScenarioType,
)
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.types import UTCDateTime, UUIDString


NUMERIC_PRECISION = 38
NUMERIC_SCALE = 18


def _enum_sql_values(enum_type: type[StrEnum]) -> str:
    """Return trusted enum values formatted for a SQL CHECK constraint."""

    return ", ".join(f"'{member.value}'" for member in enum_type)


class ScenarioDefinitionRow(Base):
    __tablename__ = "scenario_definitions"
    __table_args__ = (
        UniqueConstraint(
            "scenario_key",
            name="uq_scenario_definitions_scenario_key",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_values(ScenarioDefinitionStatus)})",
            name="ck_scenario_definitions_status_allowed",
        ),
        Index("ix_scenario_definitions_status", "status"),
        Index("ix_scenario_definitions_domain", "domain"),
    )

    scenario_definition_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(
        Text,
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

    snapshots: Mapped[list[ScenarioSnapshotRow]] = relationship(
        back_populates="definition",
        cascade="save-update, merge",
        passive_deletes=True,
        lazy="raise",
    )


class ScenarioSnapshotRow(Base):
    __tablename__ = "scenario_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "root_hash",
            name="uq_scenario_snapshots_root_hash",
        ),
        CheckConstraint(
            f"scenario_type IN ({_enum_sql_values(ScenarioType)})",
            name="ck_scenario_snapshots_scenario_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_enum_sql_values(ScenarioSnapshotStatus)})",
            name="ck_scenario_snapshots_status_allowed",
        ),
        CheckConstraint(
            "schema_version >= 1",
            name="ck_scenario_snapshots_schema_version_positive",
        ),
        CheckConstraint(
            "manifest_schema_version >= 1",
            name="ck_scenario_snapshots_manifest_schema_version_positive",
        ),
        CheckConstraint(
            "length(root_hash) = 64",
            name="ck_scenario_snapshots_root_hash_length",
        ),
        CheckConstraint(
            "length(materialized_input_hash) = 64",
            name="ck_scenario_snapshots_materialized_hash_length",
        ),
        CheckConstraint(
            "status <> 'ready' OR ready_at IS NOT NULL",
            name="ck_scenario_snapshots_ready_has_timestamp",
        ),
        Index(
            "ix_scenario_snapshots_definition_created",
            "scenario_definition_id",
            "created_at",
        ),
        Index("ix_scenario_snapshots_status", "status"),
    )

    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_definition_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_definitions.scenario_definition_id",
            name="fk_scenario_snapshots_definition_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    declared_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    scenario_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    domain: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    policy_question: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    manifest_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    manifest_schema_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    root_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    materialized_input_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    source_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    importer_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    import_environment_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    ready_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(),
        nullable=True,
    )

    definition: Mapped[ScenarioDefinitionRow] = relationship(
        back_populates="snapshots",
        lazy="raise",
    )
    files: Mapped[list[ScenarioSnapshotFileRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ScenarioSnapshotFileRow.logical_path",
    )
    criteria: Mapped[list[ScenarioCriterionRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ScenarioCriterionRow.display_order",
    )
    alternatives: Mapped[list[ScenarioAlternativeRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ScenarioAlternativeRow.display_order",
    )
    scales: Mapped[list[ScenarioScaleRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ScenarioScaleRow.scale_key",
    )
    matrix_values: Mapped[list[ScenarioMatrixValueRow]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        foreign_keys="ScenarioMatrixValueRow.scenario_snapshot_id",
    )


class ScenarioSnapshotFileRow(Base):
    __tablename__ = "scenario_snapshot_files"
    __table_args__ = (
        UniqueConstraint(
            "scenario_snapshot_id",
            "logical_path",
            name="uq_scenario_snapshot_files_snapshot_path",
        ),
        CheckConstraint(
            f"file_role IN ({_enum_sql_values(ScenarioFileRole)})",
            name="ck_scenario_snapshot_files_role_allowed",
        ),
        CheckConstraint(
            "byte_size >= 0",
            name="ck_scenario_snapshot_files_byte_size_nonnegative",
        ),
        CheckConstraint(
            "length(content_hash) = 64",
            name="ck_scenario_snapshot_files_content_hash_length",
        ),
        CheckConstraint(
            "(inline_bytes IS NOT NULL AND immutable_object_uri IS NULL) "
            "OR (inline_bytes IS NULL AND immutable_object_uri IS NOT NULL)",
            name="ck_scenario_snapshot_files_exactly_one_content_location",
        ),
        Index(
            "ix_scenario_snapshot_files_snapshot_role",
            "scenario_snapshot_id",
            "file_role",
        ),
        Index("ix_scenario_snapshot_files_content_hash", "content_hash"),
    )

    snapshot_file_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_scenario_snapshot_files_snapshot_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    logical_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    file_role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    byte_size: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    inline_bytes: Mapped[bytes | None] = mapped_column(
        LargeBinary,
        nullable=True,
    )
    immutable_object_uri: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    snapshot: Mapped[ScenarioSnapshotRow] = relationship(
        back_populates="files",
        lazy="raise",
    )


class ScenarioCriterionRow(Base):
    __tablename__ = "scenario_criteria"
    __table_args__ = (
        UniqueConstraint(
            "scenario_snapshot_id",
            "criterion_key",
            name="uq_scenario_criteria_snapshot_key",
        ),
        UniqueConstraint(
            "scenario_snapshot_id",
            "criterion_id",
            name="uq_scenario_criteria_snapshot_id_criterion_id",
        ),
        CheckConstraint(
            f"direction IN ({_enum_sql_values(CriterionDirection)})",
            name="ck_scenario_criteria_direction_allowed",
        ),
        CheckConstraint(
            f"data_type IN ({_enum_sql_values(CriterionDataType)})",
            name="ck_scenario_criteria_data_type_allowed",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="ck_scenario_criteria_display_order_nonnegative",
        ),
        Index(
            "ix_scenario_criteria_snapshot_order",
            "scenario_snapshot_id",
            "display_order",
        ),
        Index("ix_scenario_criteria_parent_id", "parent_criterion_id"),
    )

    criterion_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_scenario_criteria_snapshot_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    criterion_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    direction: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    data_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    unit: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    parent_criterion_id: Mapped[UUID | None] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_criteria.criterion_id",
            name="fk_scenario_criteria_parent_id",
            ondelete="CASCADE",
        ),
        nullable=True,
    )
    required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=true(),
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    source_column: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    snapshot: Mapped[ScenarioSnapshotRow] = relationship(
        back_populates="criteria",
        lazy="raise",
        foreign_keys=[scenario_snapshot_id],
    )


class ScenarioAlternativeRow(Base):
    __tablename__ = "scenario_alternatives"
    __table_args__ = (
        UniqueConstraint(
            "scenario_snapshot_id",
            "alternative_key",
            name="uq_scenario_alternatives_snapshot_key",
        ),
        UniqueConstraint(
            "scenario_snapshot_id",
            "alternative_id",
            name="uq_scenario_alternatives_snapshot_id_alternative_id",
        ),
        CheckConstraint(
            "display_order >= 0",
            name="ck_scenario_alternatives_display_order_nonnegative",
        ),
        Index(
            "ix_scenario_alternatives_snapshot_order",
            "scenario_snapshot_id",
            "display_order",
        ),
    )

    alternative_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_scenario_alternatives_snapshot_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    alternative_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    display_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    snapshot: Mapped[ScenarioSnapshotRow] = relationship(
        back_populates="alternatives",
        lazy="raise",
    )


class ScenarioScaleRow(Base):
    __tablename__ = "scenario_scales"
    __table_args__ = (
        UniqueConstraint(
            "scenario_snapshot_id",
            "scale_key",
            name="uq_scenario_scales_snapshot_key",
        ),
        CheckConstraint(
            "definition_version >= 1",
            name="ck_scenario_scales_definition_version_positive",
        ),
        Index("ix_scenario_scales_snapshot_id", "scenario_snapshot_id"),
    )

    scale_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_scenario_scales_snapshot_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    scale_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    scale_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    ordered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
    )
    definition_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    snapshot: Mapped[ScenarioSnapshotRow] = relationship(
        back_populates="scales",
        lazy="raise",
    )
    values: Mapped[list[ScenarioScaleValueRow]] = relationship(
        back_populates="scale",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
        order_by="ScenarioScaleValueRow.ordinal",
    )


class ScenarioScaleValueRow(Base):
    __tablename__ = "scenario_scale_values"
    __table_args__ = (
        UniqueConstraint(
            "scale_id",
            "stable_value_key",
            name="uq_scenario_scale_values_scale_key",
        ),
        UniqueConstraint(
            "scale_id",
            "ordinal",
            name="uq_scenario_scale_values_scale_ordinal",
        ),
        CheckConstraint(
            "ordinal >= 0",
            name="ck_scenario_scale_values_ordinal_nonnegative",
        ),
        CheckConstraint(
            "(fuzzy_lower IS NULL AND fuzzy_middle IS NULL "
            "AND fuzzy_upper IS NULL) OR "
            "(fuzzy_lower IS NOT NULL AND fuzzy_middle IS NOT NULL "
            "AND fuzzy_upper IS NOT NULL "
            "AND fuzzy_lower <= fuzzy_middle "
            "AND fuzzy_middle <= fuzzy_upper)",
            name="ck_scenario_scale_values_fuzzy_shape",
        ),
        Index("ix_scenario_scale_values_scale_id", "scale_id"),
    )

    scale_value_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    scale_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_scales.scale_id",
            name="fk_scenario_scale_values_scale_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    stable_value_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )
    ordinal: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )
    numeric_value: Mapped[Decimal | None] = mapped_column(
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
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
        default=dict,
    )

    scale: Mapped[ScenarioScaleRow] = relationship(
        back_populates="values",
        lazy="raise",
    )


class ScenarioMatrixValueRow(Base):
    __tablename__ = "scenario_matrix_values"
    __table_args__ = (
        ForeignKeyConstraint(
            ["scenario_snapshot_id", "alternative_id"],
            [
                "scenario_alternatives.scenario_snapshot_id",
                "scenario_alternatives.alternative_id",
            ],
            name="fk_scenario_matrix_values_snapshot_alternative",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["scenario_snapshot_id", "criterion_id"],
            [
                "scenario_criteria.scenario_snapshot_id",
                "scenario_criteria.criterion_id",
            ],
            name="fk_scenario_matrix_values_snapshot_criterion",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "(value_numeric IS NOT NULL AND value_json IS NULL) "
            "OR (value_numeric IS NULL AND value_json IS NOT NULL)",
            name="ck_scenario_matrix_values_exactly_one_value",
        ),
        Index("ix_scenario_matrix_values_alternative_id", "alternative_id"),
        Index("ix_scenario_matrix_values_criterion_id", "criterion_id"),
    )

    scenario_snapshot_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        ForeignKey(
            "scenario_snapshots.scenario_snapshot_id",
            name="fk_scenario_matrix_values_snapshot_id",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    alternative_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    criterion_id: Mapped[UUID] = mapped_column(
        UUIDString(),
        primary_key=True,
    )
    value_numeric: Mapped[Decimal | None] = mapped_column(
        Numeric(NUMERIC_PRECISION, NUMERIC_SCALE),
        nullable=True,
    )
    value_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    source_provenance_json: Mapped[dict[str, Any]] = mapped_column(
        JSON(none_as_null=True),
        nullable=False,
    )

    snapshot: Mapped[ScenarioSnapshotRow] = relationship(
        back_populates="matrix_values",
        lazy="raise",
        foreign_keys=[scenario_snapshot_id],
    )
