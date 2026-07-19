from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
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

    sessions: Mapped[list[SessionScenarioRow]] = relationship(
        "SessionScenarioRow",
        back_populates="snapshot",
        lazy="raise",
    )

class SessionScenarioRow(Base):
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

    session: Mapped[SessionScenarioRow] = relationship(
        "SessionScenarioRow",
        back_populates="stakeholder_groups",
        lazy="raise",
    )
