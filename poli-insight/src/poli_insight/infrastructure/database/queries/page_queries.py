"""SQLAlchemy implementation of read-only Streamlit page queries."""

from __future__ import annotations

from datetime import datetime, time, timedelta, UTC
from zoneinfo import ZoneInfo

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession, sessionmaker

from poli_insight.application.queries.page_queries import (
    AdminDashboardSnapshot,
    PageQueries,
    PageQueryError,
    PageResult,
    PublicSessionSummary,
    HomeActiveSessionSummary,
)
from poli_insight.core.time import utc_now
from poli_insight.domain.enum import (
    AccessCodeMode,
    Discoverability,
    EnrollmentMode,
    SessionStatus,
)
from poli_insight.infrastructure.database.models.session import SessionRow
from poli_insight.infrastructure.database.models.participation import ParticipantRow


DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


class SqlAlchemyPageQueries(PageQueries):
    """Serve page projections using short-lived read-only sessions."""

    def __init__(
        self,
        session_factory: sessionmaker[DatabaseSession],
        timezone_name: str,
    ) -> None:
        self._session_factory = session_factory
        self._timezone = ZoneInfo(timezone_name)

    def list_open_public_sessions(
        self,
        *,
        search: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        at: datetime | None = None,
    ) -> PageResult[PublicSessionSummary]:
        _validate_paging(page=page, page_size=page_size)
        query_time = at or utc_now()
        normalized_search = search.strip() if search is not None else ""

        filters = [
            SessionRow.status == SessionStatus.OPEN.value,
            SessionRow.discoverability == Discoverability.LISTED.value,
            or_(SessionRow.opens_at.is_(None), SessionRow.opens_at <= query_time),
            or_(SessionRow.closes_at.is_(None), SessionRow.closes_at > query_time),
        ]
        if normalized_search:
            escaped_search = _escape_like(normalized_search.casefold())
            filters.append(
                func.lower(SessionRow.title).like(
                    f"%{escaped_search}%",
                    escape="\\",
                )
            )

        count_statement = select(func.count()).select_from(SessionRow).where(
            *filters
        )
        statement: Select[tuple[SessionRow]] = (
            select(SessionRow)
            .where(*filters)
            .order_by(
                SessionRow.closes_at.is_(None),
                SessionRow.closes_at,
                SessionRow.title,
                SessionRow.session_id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        try:
            with self._session_factory() as database_session:
                total = database_session.scalar(count_statement) or 0
                rows = database_session.scalars(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Open sessions could not be loaded."
            ) from error

        return PageResult(
            items=tuple(_public_session_summary(row) for row in rows),
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_admin_dashboard(
        self,
        *,
        at: datetime | None = None,
    ) -> AdminDashboardSnapshot:
        query_time = at or utc_now()
        statement = select(SessionRow.status, func.count()).group_by(
            SessionRow.status
        )
        try:
            with self._session_factory() as database_session:
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Dashboard metrics could not be loaded."
            ) from error

        counts = {status: 0 for status in SessionStatus}
        for raw_status, count in rows:
            try:
                status = SessionStatus(raw_status)
            except ValueError:
                continue
            counts[status] = int(count)

        return AdminDashboardSnapshot(
            generated_at=query_time,
            session_status_counts=counts,
        )

    def get_home_metrics(
        self,
        *,
        at: datetime | None = None,
    ) -> HomeActiveSessionSummary:
        """Return current open-session and daily participation metrics."""
        query_time = at or utc_now()

        if query_time.tzinfo is None or query_time.utcoffset() is None:
            raise ValueError("at must include timezone information.")

        local_date = query_time.astimezone(self._timezone).date()

        day_start = datetime.combine(
            local_date,
            time.min,
            tzinfo=self._timezone,
        ).astimezone(UTC)

        day_end = datetime.combine(
            local_date + timedelta(days=1),
            time.min,
            tzinfo=self._timezone,
        ).astimezone(UTC)

        active_sessions = (
            select(func.count(SessionRow.session_id))
            .where(
                SessionRow.status == SessionStatus.OPEN.value,
                or_(
                    SessionRow.opens_at.is_(None),
                    SessionRow.opens_at <= query_time,
                ),
                or_(
                    SessionRow.closes_at.is_(None),
                    SessionRow.closes_at > query_time,
                ),
            )
            .scalar_subquery()
        )

        participants_today = (
            select(func.count(ParticipantRow.participant_id))
            .where(
                ParticipantRow.started_at >= day_start,
                ParticipantRow.started_at < day_end,
            )
            .scalar_subquery()
        )

        statement = select(
            active_sessions.label("total_active_sessions"),
            participants_today.label("total_participants_today"),
        )

        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).one()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Home metrics could not be loaded."
            ) from error

        return HomeActiveSessionSummary(
            total_active_sessions=int(row.total_active_sessions),
            total_participants_today=int(row.total_participants_today),
        )
        # statement = select(SessionRow.status, func.count()).where(SessionRow.status == SessionStatus.OPEN).group_by(
        #     SessionRow.status
        # )
        # try:
        #     with self._session_factory() as database_session:
        #         rows = database_session.execute(statement).all()
        # except SQLAlchemyError as error:
        #     raise PageQueryError(
        #         "Home metrics could not be loaded."
        #     ) from error
        # return HomeActiveSessionSummary(
        #     total_active_sessions=0,
        #     total_participants_today=0,
        # )

def _validate_paging(*, page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page must be at least 1.")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(
            f"page_size must be between 1 and {MAX_PAGE_SIZE}."
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _public_session_summary(row: SessionRow) -> PublicSessionSummary:
    return PublicSessionSummary(
        session_id=str(row.session_id),
        public_slug=row.public_slug,
        title=row.title,
        description=row.description,
        closes_at=row.closes_at,
        enrollment_mode=EnrollmentMode(row.enrollment_mode),
        access_code_mode=AccessCodeMode(row.access_code_mode),
    )
