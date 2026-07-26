from __future__ import annotations

from datetime import UTC, datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from poli_insight.domain.enums import ParticipantStatus
from poli_insight.domain.participant import Participant
from poli_insight.domain.submissions import Submission

from poli_insight.infrastructure.database.orm_models import ParticipantRow

from poli_insight.application.participant_queries import ParticipantPage

class SQLAlchemyParticipantRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, participant: Participant) -> None:
        self._database_session.add(
            ParticipantRow(
                participant_id=participant.participant_id,
                session_id=participant.session_id,
                user_id=participant.user_id,
                stakeholder_group_id=participant.stakeholder_group_id,
                name=participant.name,
                alias=participant.alias,
                access_status=participant.access_status.value,
                joined_at=participant.joined_at,
                disabled_at=participant.disabled_at,
                disabled_by=participant.disabled_by,
                created_at=participant.created_at,
                created_by=participant.created_by,
                updated_at=participant.updated_at,
                updated_by=participant.updated_by,
            )
        )

    def get(self, participant_id: str) -> Participant | None:
        statement = (
            select(ParticipantRow)
            .where(
                ParticipantRow.participant_id == participant_id
            )
        )

        participant_row = (
            self._database_session.execute(statement)
            .scalar_one_or_none()
        )

        if participant_row is None:
            return None

        return self._to_domain(
            participant_row
        )

    def save(self, participant: Participant) -> None:
        ...

    def list_for_session(
        self,
        session_id: str,
        *,
        page: int,
        page_size: int,
    ) -> ParticipantPage:
        condition = ParticipantRow.session_id == session_id

        total = self._database_session.scalar(
            select(func.count())
            .select_from(ParticipantRow)
            .where(condition)
        ) or 0

        rows = self._database_session.scalars(
            select(ParticipantRow)
            .where(condition)
            .order_by(
                ParticipantRow.created_at.desc(),
                ParticipantRow.participant_id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        participants = tuple(
            self._to_domain(row)
            for row in rows
        )

        return ParticipantPage(
            items=participants,
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    def _to_domain(
        row: ParticipantRow,
    ) -> Participant:
        return Participant(
            participant_id=row.participant_id,
            session_id=row.session_id,
            user_id=row.user_id,
            stakeholder_group_id=row.stakeholder_group_id,
            name=row.name,
            alias=row.alias,
            access_status=ParticipantStatus(row.access_status),
            joined_at=_as_utc(row.joined_at),
            disabled_at=_as_utc(row.disabled_at),
            disabled_by=row.disabled_by,
            created_at=_as_utc(row.created_at),
            created_by=row.created_by,
            updated_at=_as_utc(row.updated_at),
            updated_by=row.updated_by,
        )

def _as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)