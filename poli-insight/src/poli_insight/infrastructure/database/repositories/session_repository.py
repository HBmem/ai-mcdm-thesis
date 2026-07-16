from __future__ import annotations

from collections.abc import Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import UTC, datetime


from poli_insight.domain.sessions import (
    SessionScenario,
    SessionStakeholderGroup,
)
from poli_insight.infrastructure.database.orm_models import (
    SessionScenarioRow,
    SessionStakeholderGroupRow,
)
from poli_insight.domain.enums import (
    AggregationMethod,
    ParticipationMethod,
    PreferenceScale,
    RankingMethod,
    SessionStatus,
    SessionVisibility,
    WeightingMethod,
)

class SqlAlchemySessionRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(
        self,
        session: SessionScenario,
        stakeholder_groups: Sequence[SessionStakeholderGroup],
    ) -> None:
        self._database_session.add(
            SessionScenarioRow(
                session_id=session.session_id,
                scenario_id=session.scenario_id,
                scenario_version=session.scenario_version,
                title=session.title,
                description=session.description,
                admin_notes=session.admin_notes,
                visibility=session.visibility.value,
                participation_method=session.participation_method.value,
                preference_scale=session.preference_scale.value,
                weighting_method=session.weighting_method.value,
                ranking_method=session.ranking_method.value,
                aggregation_method=session.aggregation_method.value,
                require_access_code=session.require_access_code,
                access_code_type=session.access_code_type,
                allow_resubmissions=session.allow_resubmissions,
                start_at=session.start_at,
                end_at=session.end_at,
                status=session.status.value,
                opened_at=session.opened_at,
                closed_at=session.closed_at,
                archived_at=session.archived_at,
                created_at=session.created_at,
                created_by=session.created_by,
                updated_at=session.updated_at,
                updated_by=session.updated_by,
            )
        )

        self._database_session.add_all(
            [
                SessionStakeholderGroupRow(
                    session_id=group.session_id,
                    stakeholder_group_id=group.stakeholder_group_id,
                    stakeholder_group_name=group.name,
                    default_voting_power=group.default_voting_power,
                    current_voting_power=group.current_voting_power,
                    normalized_voting_power=group.normalized_voting_power,
                    is_active=group.is_active,
                    created_at=group.created_at,
                    updated_at=group.updated_at,
                    updated_by=group.updated_by
                )
                for group in stakeholder_groups
            ]
        )
    
    def get(
        self,
        session_id:str,
    ) -> SessionScenario | None:
        session_row = self._database_session(
            SessionScenarioRow,
            session_id,
        )

        if session_row is None:
            return None
        
        group_rows = self._database_session.scalars(
            select(SessionStakeholderGroupRow)
            .where(
                SessionStakeholderGroupRow.session_id == session_id
            )
            .order_by(
                SessionStakeholderGroupRow.stakeholder_group_id
            )
        ).all()

        stakeholder_groups = [
            self._group_to_domain(row)
            for row in group_rows
        ]

        return self._session_to_domain(
            session_row,
            stakeholder_groups,
        )
    
    @staticmethod
    def _group_to_domain(
        row: SessionStakeholderGroupRow,
    ) -> SessionStakeholderGroup:
        return SessionStakeholderGroup(
            session_id=row.session_id,
            stakeholder_group_id=row.stakeholder_group_id,
            name=row.stakeholder_group_name,
            default_voting_power=row.default_voting_power,
            current_voting_power=row.current_voting_power,
            normalized_voting_power=row.normalized_voting_power,
            is_active=row.is_active,
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
            updated_by=row.updated_by,
        )
    
    @staticmethod
    def _session_to_domain(
        row: SessionScenarioRow,
        stakeholder_groups: list[SessionStakeholderGroup],
    ) -> SessionScenario:
        return SessionScenario(
            session_id=row.session_id,
            scenario_id=row.scenario_id,
            scenario_version=row.scenario_version,
            title=row.title,
            description=row.description,
            admin_notes=row.admin_notes,
            visibility=SessionVisibility(row.visibility),
            participation_method=ParticipationMethod(
                row.participation_method
            ),
            preference_scale=PreferenceScale(
                row.preference_scale
            ),
            weighting_method=WeightingMethod(
                row.weighting_method
            ),
            ranking_method=RankingMethod(
                row.ranking_method
            ),
            aggregation_method=AggregationMethod(
                row.aggregation_method
            ),
            require_access_code=row.require_access_code,
            access_code_type=row.access_code_type,
            allow_resubmissions=row.allow_resubmissions,
            start_at=_as_utc(row.start_at),
            end_at=_as_utc(row.end_at),
            status=SessionStatus(row.status),
            opened_at=_as_utc(row.opened_at),
            closed_at=_as_utc(row.closed_at),
            archived_at=_as_utc(row.archived_at),
            created_at=_as_utc(row.created_at),
            created_by=row.created_by,
            updated_at=_as_utc(row.updated_at),
            updated_by=row.updated_by,
            stakeholder_groups=stakeholder_groups,
        )

def _as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)