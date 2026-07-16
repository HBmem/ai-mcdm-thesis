from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Self

from poli_insight.domain.enums import (
    AggregationMethod,
    ParticipationMethod,
    PreferenceScale,
    RankingMethod,
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
)

class SessionRuleViolation(ValueError):
    """Raised when an operation violates session business rule."""
    pass

def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and value.tzinfo is None:
        raise SessionRuleViolation(
            f"{field_name} must include timezone information."
        )
    
@dataclass
class SessionStakeholderGroup:
    session_id: str
    stakeholder_group_id: str
    name: str
    default_voting_power: float
    current_voting_power: float
    created_at: datetime
    updated_at: datetime
    updated_by: str

    # defaults
    normalized_voting_power: float = 0.0
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise SessionRuleViolation(
                "Session ID cannot be empty."
            )
        
        if not self.stakeholder_group_id.strip():
            raise SessionRuleViolation(
                "Stakeholder group ID cannot be empty."
            )
        
        if not self.name.strip():
            raise SessionRuleViolation(
                "Stakeholder group name cannot be empty."
            )

        if self.default_voting_power < 0:
            raise SessionRuleViolation(
                "Default voting power cannot be negative."
            )

        if self.current_voting_power < 0:
            raise SessionRuleViolation(
                "Current voting power cannot be negative."
            )
        
        # if not self.created_at: 
        
@dataclass
class SessionScenario:
    session_id: str

    # The session reference an immutable scenario snapshot
    scenario_id: str
    scenario_version: str

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

    status: SessionStatus

    opened_at: datetime | None
    closed_at: datetime | None
    archived_at: datetime | None

    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    stakeholder_groups: list[SessionStakeholderGroup] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_schedule()
        self._validate_access_configuration()
        self._validate_stakeholder_groups()

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        scenario_id: str,
        scenario_version: str,
        title: str,
        description: str | None,
        admin_notes: str | None,
        visibility: SessionVisibility,
        participation_method: ParticipationMethod,
        preference_scale: PreferenceScale,
        weighting_method: WeightingMethod,
        ranking_method: RankingMethod,
        aggregation_method: AggregationMethod,
        require_access_code: bool,
        access_code_type: str | None,
        allow_resubmissions: bool,
        start_at: datetime | None,
        end_at: datetime | None,
        stakeholder_groups: list[SessionStakeholderGroup],
        actor_id: str,
        now: datetime | None = None,
    ) -> Self:
        """Create a new session in the Draft state."""
        timestamp = now or datetime.now(UTC)

        _require_aware_datetime(timestamp, "now")

        session = cls(
            session_id=session_id,
            scenario_id=scenario_id,
            scenario_version=scenario_version,
            title=title.strip(),
            description=description,
            admin_notes=admin_notes,
            visibility=visibility,
            participation_method=participation_method,
            preference_scale=preference_scale,
            weighting_method=weighting_method,
            ranking_method=ranking_method,
            aggregation_method=aggregation_method,
            require_access_code=require_access_code,
            access_code_type=access_code_type,
            allow_resubmissions=allow_resubmissions,
            start_at=start_at,
            end_at=end_at,
            status=SessionStatus.DRAFT,
            opened_at=None,
            closed_at=None,
            archived_at=None,
            created_at=timestamp,
            created_by=actor_id,
            updated_at=timestamp,
            updated_by=actor_id,
            stakeholder_groups=stakeholder_groups,
        )

        session._normalize_voting_power()

        return session
    
    def open(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status != SessionStatus.DRAFT:
            raise SessionRuleViolation(
                "Only a draft session can be opened."
            )

        if self.end_at is not None and timestamp >= self.end_at:
            raise SessionRuleViolation(
                "A session cannot be opened after its end time."
            )

        self.status = SessionStatus.OPEN
        self.opened_at = timestamp
        self._mark_updated(actor_id, timestamp)
    
    def close(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status != SessionStatus.OPEN:
            raise SessionRuleViolation(
                "Only an open session can be closed."
            )

        self.status = SessionStatus.CLOSED
        self.closed_at = timestamp
        self._mark_updated(actor_id, timestamp)
    
    def archive(
        self,
        *,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        allowed_statuses = {
            SessionStatus.CLOSED,
            SessionStatus.PROCESSED,
            SessionStatus.PUBLISHED,
        }

        if self.status not in allowed_statuses:
            raise SessionRuleViolation(
                f"A session in {self.status.value!r} status cannot be archived."
            )

        self.status = SessionStatus.ARCHIVED
        self.archived_at = timestamp
        self._mark_updated(actor_id, timestamp)

    def can_accept_submissions(
        self,
        now: datetime | None = None,
    ) -> bool:
        timestamp = now or datetime.now(UTC)
        _require_aware_datetime(timestamp, "now")

        if self.status != SessionStatus.OPEN:
            return False

        if self.start_at is not None and timestamp < self.start_at:
            return False

        if self.end_at is not None and timestamp >= self.end_at:
            return False

        return True
    
    def update_voting_power(
        self,
        *,
        stakeholder_group_id: str,
        voting_power: float,
        actor_id: str,
        now: datetime | None = None,
    ) -> None:
        if voting_power < 0:
            raise SessionRuleViolation(
                "Voting power cannot be negative."
            )

        group = self._find_stakeholder_group(
            stakeholder_group_id
        )
        group.current_voting_power = voting_power

        self._normalize_voting_power()

        timestamp = now or datetime.now(UTC)
        self._mark_updated(actor_id, timestamp)

    def _normalize_voting_power(self) -> None:
        active_groups = [
            group
            for group in self.stakeholder_groups
            if group.is_active
        ]

        total = sum(
            group.current_voting_power
            for group in active_groups
        )

        if active_groups and total <= 0:
            raise SessionRuleViolation(
                "Active stakeholder voting power must total more than zero."
            )

        for group in self.stakeholder_groups:
            if not group.is_active:
                group.normalized_voting_power = 0.0
            else:
                group.normalized_voting_power = (
                    group.current_voting_power / total
                )
    def _find_stakeholder_group(
        self,
        stakeholder_group_id: str,
    ) -> SessionStakeholderGroup:
        for group in self.stakeholder_groups:
            if (group.stakeholder_group_id == stakeholder_group_id):
                return group

        raise SessionRuleViolation(
            f"Unknown stakeholder group: "
            f"{stakeholder_group_id!r}."
        )
    
    def _validate_identity(self) -> None:
        if not self.session_id.strip():
            raise SessionRuleViolation(
                "Session ID cannot be empty."
            )

        if not self.scenario_id.strip():
            raise SessionRuleViolation(
                "Scenario ID cannot be empty."
            )

        if not self.scenario_version.strip():
            raise SessionRuleViolation(
                "Scenario version cannot be empty."
            )

        if not self.title.strip():
            raise SessionRuleViolation(
                "Session title cannot be empty."
            )

        if not self.created_by.strip():
            raise SessionRuleViolation(
                "Session creator cannot be empty."
            )
    
    def _validate_schedule(self) -> None:
        _require_aware_datetime(self.start_at, "start_at")
        _require_aware_datetime(self.end_at, "end_at")
        _require_aware_datetime(self.opened_at, "opened_at")
        _require_aware_datetime(self.closed_at, "closed_at")
        _require_aware_datetime(self.archived_at, "archived_at")
        _require_aware_datetime(self.created_at, "created_at")
        _require_aware_datetime(self.updated_at, "updated_at")

        if (
            self.start_at is not None
            and self.end_at is not None
            and self.end_at <= self.start_at
        ):
            raise SessionRuleViolation(
                "Session end time must be later than start time."
            )
    
    def _validate_access_configuration(self) -> None:
        if self.require_access_code and not self.access_code_type:
            raise SessionRuleViolation(
                "Access-code type is required when access "
                "codes are enabled."
            )

        if not self.require_access_code and self.access_code_type:
            raise SessionRuleViolation(
                "Access-code type should be empty when access "
                "codes are disabled."
            )
    
    def _validate_stakeholder_groups(self) -> None:
        group_ids = [
            group.stakeholder_group_id
            for group in self.stakeholder_groups
        ]

        if len(group_ids) != len(set(group_ids)):
            raise SessionRuleViolation(
                "Stakeholder group IDs must be unique."
            )
    
    def _mark_updated(
        self,
        actor_id: str,
        timestamp: datetime,
    ) -> None:
        if not actor_id.strip():
            raise SessionRuleViolation(
                "Updating actor cannot be empty."
            )

        _require_aware_datetime(timestamp, "timestamp")

        self.updated_at = timestamp
        self.updated_by = actor_id
