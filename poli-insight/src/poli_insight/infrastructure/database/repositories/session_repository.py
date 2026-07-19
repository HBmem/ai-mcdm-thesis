from __future__ import annotations

from collections.abc import Sequence
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload
from datetime import UTC, datetime

from poli_insight.application.session_queries import (
    SessionFilters,
    SessionPage,
)
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
        session_id: str,
    ) -> SessionScenario | None:
        statement = (
            select(SessionScenarioRow)
            .options(
                selectinload(
                    SessionScenarioRow.stakeholder_groups
                )
            )
            .where(
                SessionScenarioRow.session_id == session_id
            )
        )

        session_row = (
            self._database_session.execute(statement)
            .scalar_one_or_none()
        )

        if session_row is None:
            return None

        stakeholder_groups = [
            self._group_to_domain(row)
            for row in session_row.stakeholder_groups
        ]

        return self._session_to_domain(
            session_row,
            stakeholder_groups,
        )
    
    def save(
        self,
        session: SessionScenario,
    ) -> None:
        row = self._database_session.get(
            SessionScenarioRow,
            session.session_id,
        )

        if row is None:
            raise LookupError(
                f"Session {session.session_id!r} "
                "does not exist."
            )
        
        row.title = session.title
        row.description = session.description
        row.admin_notes = session.admin_notes
        row.visibility = session.visibility.value

        row.require_access_code = (
            session.require_access_code
        )
        row.access_code_type = session.access_code_type
        row.allow_resubmissions = (
            session.allow_resubmissions
        )

        row.start_at = session.start_at
        row.end_at = session.end_at
        row.status = session.status.value

        row.opened_at = session.opened_at
        row.closed_at = session.closed_at
        row.archived_at = session.archived_at

        row.updated_at = session.updated_at
        row.updated_by = session.updated_by
    
    def delete(
        self,
        session_id: str,
    ) -> bool:
        row = self._database_session.get(
            SessionScenarioRow,
            session_id,
        )

        if row is None:
            return False

        self._database_session.delete(row)
        return True
    
    def list_filtered(
        self,
        filters: SessionFilters,
        *,
        page: int,
        page_size: int,
    ) -> SessionPage:
        conditions = []

        if filters.scenario_id is not None:
            conditions.append(
                SessionScenarioRow.scenario_id
                == filters.scenario_id
            )

        if filters.scenario_version is not None:
            conditions.append(
                SessionScenarioRow.scenario_version
                == filters.scenario_version
            )

        if filters.status is not None:
            conditions.append(
                SessionScenarioRow.status
                == filters.status.value
            )

        if filters.visibility is not None:
            conditions.append(
                SessionScenarioRow.visibility
                == filters.visibility.value
            )

        if filters.weighting_method is not None:
            conditions.append(
                SessionScenarioRow.weighting_method
                == filters.weighting_method.value
            )

        if filters.ranking_method is not None:
            conditions.append(
                SessionScenarioRow.ranking_method
                == filters.ranking_method.value
            )

        if filters.preference_scale is not None:
            conditions.append(
                SessionScenarioRow.preference_scale
                == filters.preference_scale.value
            )

        if filters.require_access_code is not None:
            conditions.append(
                SessionScenarioRow.require_access_code
                == filters.require_access_code
            )

        if filters.allow_resubmissions is not None:
            conditions.append(
                SessionScenarioRow.allow_resubmissions
                == filters.allow_resubmissions
            )

        count_statement = (
            select(func.count())
            .select_from(SessionScenarioRow)
            .where(*conditions)
        )

        total = (
            self._database_session.scalar(count_statement)
            or 0
        )

        statement = (
            select(SessionScenarioRow)
            .options(
                selectinload(
                    SessionScenarioRow.stakeholder_groups
                )
            )
            .where(*conditions)
            .order_by(
                SessionScenarioRow.updated_at.desc(),
                SessionScenarioRow.session_id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        rows = self._database_session.scalars(
            statement
        ).all()

        sessions = tuple(
            self._session_to_domain(
                row,
                [
                    self._group_to_domain(group)
                    for group in row.stakeholder_groups
                ],
            )
            for row in rows
        )

        return SessionPage(
            items=sessions,
            total=total,
            page=page,
            page_size=page_size,
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