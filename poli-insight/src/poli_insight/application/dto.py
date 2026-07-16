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

    require_access_code: bool
    access_code_type: str | None
    allow_resubmissions: bool

    start_at: datetime | None
    end_at: datetime | None

    voting_power: Mapping[str, float]
    actor_id: str