from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.models.enum import AggregationMethod, ParticipationMethod, PreferenceMethod, RankingMethod, SessionStatus, SessionVisibility, WeightingMethod

@dataclass(frozen=True)
class SessionScenario:
    session_id: str
    scenario_id: str
    scenario_version: str
    title: str
    description: str | None
    admin_notes: str | None
    status: SessionStatus
    visibility: SessionVisibility
    weighting_method: WeightingMethod
    ranking_method: RankingMethod
    preference_method: PreferenceMethod
    participation_method: ParticipationMethod
    aggregation_method: AggregationMethod
    require_access_code: bool
    access_code_type: str | None
    allow_resubmissions: bool
    start_at: datetime | None
    end_at: datetime | None
    opened_at: datetime | None
    closed_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    created_by: str | None
    updated_at: datetime
    updated_by: str | None

    def can_accept_submissions(self) -> bool:
        return (
            self.status == SessionStatus.OPEN
            and (self.start_at is None or self.start_at <= datetime.now())
            and (self.end_at is None or self.end_at > datetime.now())
        )

@dataclass
class SessionStakeholderGroup:
    session_id: str
    stakeholder_group_id: str
    stakeholder_group_name: str
    default_voting_power: float
    current_voting_power: float
    normalized_voting_power: float
    is_active: bool
    created_at: datetime
    updated_at: datetime

@dataclass
class SessionParticipant:
    participant_id: str
    session_id: str
    stakeholder_group_id: str
    display_name: str
    status: str
    access_code_hash: str | None
    access_code_created_at: datetime | None
    access_code_regenerated_at: datetime | None
    access_code_expires_at: datetime | None
    invited_at: datetime | None
    submitted_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime