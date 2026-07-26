from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from poli_insight.domain.enums import (
    AggregationMethod,
    ParticipationMethod,
    PreferenceScale,
    RankingMethod,
    SessionVisibility,
    WeightingMethod,
    ParticipantStatus,
    PreferenceElicitationMethod
)
from poli_insight.domain.scenario import ScenarioBundle

@dataclass(frozen=True)
class CreateSessionCommand:
    scenario: ScenarioBundle
    title: str
    description: str | None
    admin_notes: str | None

    visibility: SessionVisibility
    participation_method: ParticipationMethod
    preference_scale: PreferenceScale
    weighting_method: WeightingMethod
    ranking_method: RankingMethod
    aggregation_method: AggregationMethod
    preference_elicitation_method: PreferenceElicitationMethod

    require_access_code: bool
    access_code_type: str | None
    allow_resubmissions: bool

    start_at: datetime | None
    end_at: datetime | None

    voting_power: Mapping[str, float]
    actor_id: str

@dataclass(frozen=True)
class UpdateSessionCommand:
    session_id: str
    title: str
    description: str | None
    admin_notes: str | None
    visibility: SessionVisibility
    end_at: datetime | None
    actor_id: str

@dataclass(frozen=True)
class CreateParticipantCommand:
    participant_id: str
    session_id: str
    user_id: str | None
    stakeholder_group_id: str

    name: str | None
    alias: str | None
    access_status: ParticipantStatus
    disabled_at: datetime | None
    disabled_by: str | None

    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str