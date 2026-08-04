"""SQLAlchemy implementation of read-only Streamlit page queries."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_FLOOR, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import aliased, sessionmaker

from poli_insight.application.queries.page_queries import (
    AdminAuditEventSummary,
    AdminDashboardSnapshot,
    AdminSessionDetail,
    AdminSessionSummary,
    AlgorithmImplementationOption,
    HomeActiveSessionSummary,
    PageQueries,
    PageQueryError,
    PageResult,
    ParticipationGroupOption,
    ParticipationQuestion,
    ParticipationScaleOption,
    ParticipationWorkspace,
    PublicParticipationSession,
    PublicSessionSummary,
    ScenarioAlternativePreview,
    ScenarioCriterionPreview,
    ScenarioFilePreview,
    ScenarioLibraryMetrics,
    ScenarioScalePreview,
    ScenarioSnapshotDetail,
    ScenarioSnapshotSummary,
    ScenarioStakeholderDefault,
    SessionAuditEventSummary,
    SessionCatalogMetrics,
    SessionConfigurationSummary,
    SessionGroupProgress,
    SessionInvitationSummary,
    SessionParticipantDetail,
    SessionParticipantSummary,
    SessionScenarioOption,
    SessionSubmissionDetail,
    SessionSubmissionSummary,
    ValidationQueueItem,
)
from poli_insight.core.time import utc_now
from poli_insight.domain.enum import (
    AccessCodeMode,
    AlgorithmRole,
    CriterionDataType,
    CriterionDirection,
    Discoverability,
    EnrollmentMode,
    InvitationStatus,
    MissingGroupPolicy,
    ParticipantAccessStatus,
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    ScenarioDefinitionStatus,
    ScenarioFileRole,
    ScenarioSnapshotStatus,
    ScenarioType,
    SessionStatus,
    StakeholderSelectionMode,
    SubmissionReviewStatus,
    SubmissionStatus,
    ValidationStatus,
)
from poli_insight.infrastructure.database.models.audit import AuditEventRow
from poli_insight.infrastructure.database.models.operations import (
    SubmissionReviewDecisionRow,
)
from poli_insight.infrastructure.database.models.participation import (
    ParticipantConsentRow,
    ParticipantRow,
    SessionInvitationRow,
)
from poli_insight.infrastructure.database.models.scenario import (
    ScenarioAlternativeRow,
    ScenarioCriterionRow,
    ScenarioDefinitionRow,
    ScenarioMatrixValueRow,
    ScenarioScaleRow,
    ScenarioScaleValueRow,
    ScenarioSnapshotFileRow,
    ScenarioSnapshotRow,
)
from poli_insight.infrastructure.database.models.session import (
    AlgorithmImplementationRow,
    ResponseQuestionDefinitionRow,
    SessionConfigurationVersionRow,
    SessionRow,
    SessionStakeholderGroupRow,
)
from poli_insight.infrastructure.database.models.submission import (
    SubmissionAnswerRow,
    SubmissionRow,
)
from poli_insight.infrastructure.database.models.validation import (
    SubmissionValidationRow,
    ValidationMessageRow,
)

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 100


class SqlAlchemyPageQueries(PageQueries):
    """Serve page projections using short-lived read-only sessions."""

    def __init__(
        self,
        session_factory: sessionmaker[DatabaseSession],
        timezone_name: str = "UTC",
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
            SessionRow.enrollment_mode == EnrollmentMode.OPEN.value,
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

        count_statement = select(func.count()).select_from(SessionRow).where(*filters)
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
            raise PageQueryError("Open sessions could not be loaded.") from error

        return PageResult(
            items=tuple(_public_session_summary(row) for row in rows),
            page=page,
            page_size=page_size,
            total=total,
        )

    def get_public_participation_session(
        self,
        public_slug: str,
        *,
        at: datetime | None = None,
    ) -> PublicParticipationSession | None:
        query_time = at or utc_now()
        statement = select(SessionRow).where(
            SessionRow.public_slug == public_slug.strip(),
            SessionRow.status == SessionStatus.OPEN.value,
            SessionRow.active_configuration_version_id.is_not(None),
            or_(SessionRow.opens_at.is_(None), SessionRow.opens_at <= query_time),
            or_(SessionRow.closes_at.is_(None), SessionRow.closes_at > query_time),
        )
        try:
            with self._session_factory() as database_session:
                session_row = database_session.execute(statement).scalar_one_or_none()
                if session_row is None:
                    return None
                group_rows = database_session.scalars(
                    select(SessionStakeholderGroupRow)
                    .where(
                        SessionStakeholderGroupRow.configuration_version_id
                        == session_row.active_configuration_version_id,
                        SessionStakeholderGroupRow.is_active.is_(True),
                    )
                    .order_by(
                        SessionStakeholderGroupRow.display_order,
                        SessionStakeholderGroupRow.session_stakeholder_group_id,
                    )
                ).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Participation session could not be loaded."
            ) from error
        return _public_participation_session(session_row, group_rows)

    def get_participation_workspace(
        self,
        participant_id: str,
    ) -> ParticipationWorkspace | None:
        try:
            with self._session_factory() as database_session:
                participant = database_session.get(ParticipantRow, participant_id)
                if participant is None:
                    return None
                session_row = database_session.get(SessionRow, participant.session_id)
                configuration = database_session.get(
                    SessionConfigurationVersionRow,
                    participant.configuration_version_id,
                )
                if session_row is None or configuration is None:
                    return None
                group_rows = database_session.scalars(
                    select(SessionStakeholderGroupRow)
                    .where(
                        SessionStakeholderGroupRow.configuration_version_id
                        == configuration.configuration_version_id,
                        SessionStakeholderGroupRow.is_active.is_(True),
                    )
                    .order_by(SessionStakeholderGroupRow.display_order)
                ).all()
                question_rows = database_session.scalars(
                    select(ResponseQuestionDefinitionRow)
                    .where(
                        ResponseQuestionDefinitionRow.configuration_version_id
                        == configuration.configuration_version_id
                    )
                    .order_by(ResponseQuestionDefinitionRow.display_order)
                ).all()
                criterion_ids = {
                    value
                    for row in question_rows
                    for value in (
                        row.criterion_id,
                        row.left_criterion_id,
                        row.right_criterion_id,
                    )
                    if value is not None
                }
                alternative_ids = {
                    row.alternative_id
                    for row in question_rows
                    if row.alternative_id is not None
                }
                criteria = {
                    str(row.criterion_id): row
                    for row in database_session.scalars(
                        select(ScenarioCriterionRow).where(
                            ScenarioCriterionRow.criterion_id.in_(criterion_ids)
                        )
                    ).all()
                }
                alternatives = {
                    str(row.alternative_id): row
                    for row in database_session.scalars(
                        select(ScenarioAlternativeRow).where(
                            ScenarioAlternativeRow.alternative_id.in_(alternative_ids)
                        )
                    ).all()
                }
                scale = database_session.get(ScenarioScaleRow, configuration.scale_id)
                scale_values = database_session.scalars(
                    select(ScenarioScaleValueRow)
                    .where(ScenarioScaleValueRow.scale_id == configuration.scale_id)
                    .order_by(ScenarioScaleValueRow.ordinal)
                ).all()
                attempts = database_session.scalars(
                    select(SubmissionRow)
                    .where(
                        SubmissionRow.participant_id == participant.participant_id,
                        SubmissionRow.configuration_version_id
                        == configuration.configuration_version_id,
                    )
                    .order_by(SubmissionRow.attempt_number.desc())
                ).all()
                submission = next(
                    (
                        row
                        for row in attempts
                        if row.status == SubmissionStatus.DRAFT.value
                    ),
                    attempts[0] if attempts else None,
                )
                answer_rows = (
                    database_session.scalars(
                        select(SubmissionAnswerRow).where(
                            SubmissionAnswerRow.submission_id
                            == submission.submission_id
                        )
                    ).all()
                    if submission is not None
                    else []
                )
                consent_raw = configuration.configuration_json.get("consent", {})
                consent = consent_raw if isinstance(consent_raw, Mapping) else {}
                consent_version = str(consent.get("version", "1"))
                consent_row = database_session.execute(
                    select(ParticipantConsentRow).where(
                        ParticipantConsentRow.participant_id
                        == participant.participant_id,
                        ParticipantConsentRow.configuration_version_id
                        == configuration.configuration_version_id,
                        ParticipantConsentRow.consent_version == consent_version,
                    )
                ).scalar_one_or_none()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Questionnaire workspace could not be loaded."
            ) from error

        questions = tuple(
            _participation_question(row, criteria=criteria, alternatives=alternatives)
            for row in question_rows
        )
        return ParticipationWorkspace(
            participant_id=str(participant.participant_id),
            session=_public_participation_session(session_row, group_rows),
            response_format=ResponseFormat(configuration.response_format),
            questions=questions,
            scale_name=scale.name if scale is not None else "Response scale",
            scale_options=tuple(
                ParticipationScaleOption(
                    scale_value_id=str(row.scale_value_id),
                    label=row.label,
                    ordinal=row.ordinal,
                    numeric_value=(
                        None if row.numeric_value is None else str(row.numeric_value)
                    ),
                )
                for row in scale_values
            ),
            consent_required=consent.get("required") is True,
            consent_version=consent_version,
            consent_title=str(consent.get("title", "Research participation consent")),
            consent_statement=str(consent.get("statement", "")),
            consent_completed=consent_row is not None,
            submission_id=(str(submission.submission_id) if submission else None),
            submission_status=(
                SubmissionStatus(submission.status) if submission else None
            ),
            attempt_number=submission.attempt_number if submission else None,
            answers={
                str(row.question_definition_id): dict(row.raw_value_json)
                for row in answer_rows
            },
            last_saved_at=submission.last_saved_at if submission else None,
        )

    def get_admin_dashboard(
        self,
        *,
        at: datetime | None = None,
    ) -> AdminDashboardSnapshot:
        query_time = at or utc_now()
        statement = select(SessionRow.status, func.count()).group_by(SessionRow.status)
        try:
            with self._session_factory() as database_session:
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Dashboard metrics could not be loaded.") from error

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
            raise PageQueryError("Home metrics could not be loaded.") from error

        return HomeActiveSessionSummary(
            total_active_sessions=int(row.total_active_sessions),
            total_participants_today=int(row.total_participants_today),
        )

    def get_session_catalog_metrics(
        self,
        *,
        search: str | None = None,
        status: SessionStatus | None = None,
        scenario_key: str | None = None,
    ) -> SessionCatalogMetrics:
        filters = _session_filters(
            search=search,
            status=status,
            scenario_key=scenario_key,
        )
        attention_count = _session_attention_count()
        statement = (
            select(
                func.count(SessionRow.session_id).label("total_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (SessionRow.status == SessionStatus.OPEN.value, 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("open_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                _needs_attention_expression(attention_count),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("attention_count"),
            )
            .select_from(SessionRow)
            .join(
                ScenarioSnapshotRow,
                ScenarioSnapshotRow.scenario_snapshot_id
                == SessionRow.scenario_snapshot_id,
            )
            .join(ScenarioDefinitionRow)
            .where(*filters)
        )
        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).one()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Session catalog metrics could not be loaded."
            ) from error
        return SessionCatalogMetrics(
            total_count=int(row.total_count),
            open_count=int(row.open_count),
            attention_count=int(row.attention_count),
        )

    def list_session_scenarios(self) -> tuple[SessionScenarioOption, ...]:
        statement = (
            select(
                ScenarioDefinitionRow.scenario_key,
                ScenarioDefinitionRow.title,
            )
            .select_from(SessionRow)
            .join(
                ScenarioSnapshotRow,
                ScenarioSnapshotRow.scenario_snapshot_id
                == SessionRow.scenario_snapshot_id,
            )
            .join(ScenarioDefinitionRow)
            .distinct()
            .order_by(
                ScenarioDefinitionRow.title,
                ScenarioDefinitionRow.scenario_key,
            )
        )
        try:
            with self._session_factory() as database_session:
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Session scenario filters could not be loaded."
            ) from error
        return tuple(
            SessionScenarioOption(
                scenario_key=row.scenario_key,
                title=row.title,
            )
            for row in rows
        )

    def list_admin_sessions(
        self,
        *,
        search: str | None = None,
        status: SessionStatus | None = None,
        scenario_key: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[AdminSessionSummary]:
        _validate_paging(page=page, page_size=page_size)
        filters = _session_filters(
            search=search,
            status=status,
            scenario_key=scenario_key,
        )
        count_statement = (
            select(func.count(SessionRow.session_id))
            .select_from(SessionRow)
            .join(
                ScenarioSnapshotRow,
                ScenarioSnapshotRow.scenario_snapshot_id
                == SessionRow.scenario_snapshot_id,
            )
            .join(ScenarioDefinitionRow)
            .where(*filters)
        )
        statement = (
            _admin_session_summary_statement()
            .where(*filters)
            .order_by(SessionRow.updated_at.desc(), SessionRow.title)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        try:
            with self._session_factory() as database_session:
                total = database_session.scalar(count_statement) or 0
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Sessions could not be loaded.") from error
        return PageResult(
            items=tuple(_admin_session_summary(row) for row in rows),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def get_admin_session_detail(
        self,
        session_id: str,
    ) -> AdminSessionDetail | None:
        if not session_id.strip():
            raise ValueError("session_id cannot be empty.")

        summary_statement = _admin_session_summary_statement().where(
            SessionRow.session_id == session_id
        )
        session_statement = select(
            SessionRow.admin_notes,
            SessionRow.discoverability,
            SessionRow.enrollment_mode,
            SessionRow.access_code_mode,
            SessionRow.identity_policy,
            SessionRow.stakeholder_selection_mode,
            SessionRow.created_at,
            SessionRow.created_by,
            SessionRow.active_configuration_version_id,
        ).where(SessionRow.session_id == session_id)
        participant_total_statement = (
            select(func.count())
            .select_from(ParticipantRow)
            .where(ParticipantRow.session_id == session_id)
        )
        submission_total_statement = (
            select(func.count())
            .select_from(SubmissionRow)
            .where(SubmissionRow.session_id == session_id)
        )
        participant_statement = (
            select(
                ParticipantRow,
                SessionStakeholderGroupRow.name.label("group_name"),
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == ParticipantRow.session_stakeholder_group_id,
            )
            .where(ParticipantRow.session_id == session_id)
            .order_by(ParticipantRow.enrolled_at.desc())
            .limit(100)
        )
        submission_statement = (
            select(
                SubmissionRow,
                ParticipantRow.alias.label("participant_alias"),
                SessionStakeholderGroupRow.name.label("group_name"),
            )
            .select_from(SubmissionRow)
            .join(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == SubmissionRow.session_stakeholder_group_id,
            )
            .where(SubmissionRow.session_id == session_id)
            .order_by(SubmissionRow.updated_at.desc())
            .limit(100)
        )
        audit_statement = (
            select(AuditEventRow)
            .where(AuditEventRow.session_id == session_id)
            .order_by(AuditEventRow.occurred_at.desc())
            .limit(50)
        )

        try:
            with self._session_factory() as database_session:
                summary_row = database_session.execute(summary_statement).one_or_none()
                if summary_row is None:
                    return None
                session_row = database_session.execute(session_statement).one()
                configuration_rows = _load_configurations(
                    database_session,
                    session_id,
                    active_configuration_id=(
                        session_row.active_configuration_version_id
                    ),
                )
                _group_rows, group_progress = _load_group_progress(
                    database_session,
                    session_id=session_id,
                    configuration_id=session_row.active_configuration_version_id,
                )
                participant_rows = database_session.execute(participant_statement).all()
                submission_rows = database_session.execute(submission_statement).all()
                participant_total = (
                    database_session.scalar(participant_total_statement) or 0
                )
                submission_total = (
                    database_session.scalar(submission_total_statement) or 0
                )
                validation_by_submission = _load_latest_validations(
                    database_session,
                    tuple(
                        str(row.SubmissionRow.submission_id) for row in submission_rows
                    ),
                )
                audit_rows = database_session.scalars(audit_statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Session details could not be loaded.") from error

        configurations = tuple(
            _configuration_summary(row) for row in configuration_rows
        )
        configuration = next(
            (item for item in configurations if item.is_active),
            None,
        )

        participants = tuple(
            _participant_summary(row.ParticipantRow, row.group_name)
            for row in participant_rows
        )
        submissions = tuple(
            _submission_summary(
                row.SubmissionRow,
                participant_alias=row.participant_alias,
                group_name=row.group_name,
                validation=validation_by_submission.get(
                    str(row.SubmissionRow.submission_id)
                ),
            )
            for row in submission_rows
        )
        return AdminSessionDetail(
            summary=_admin_session_summary(summary_row),
            admin_notes=session_row.admin_notes,
            discoverability=Discoverability(session_row.discoverability),
            enrollment_mode=EnrollmentMode(session_row.enrollment_mode),
            access_code_mode=AccessCodeMode(session_row.access_code_mode),
            identity_policy=session_row.identity_policy,
            stakeholder_selection_mode=StakeholderSelectionMode(
                session_row.stakeholder_selection_mode
            ),
            created_at=session_row.created_at,
            created_by=session_row.created_by,
            configuration=configuration,
            configurations=configurations,
            group_progress=group_progress,
            participants=participants,
            participant_total=int(participant_total),
            submissions=submissions,
            submission_total=int(submission_total),
            audit_events=tuple(_audit_summary(row) for row in audit_rows),
        )

    def list_session_invitations(
        self,
        session_id: str,
        *,
        search: str | None = None,
        status: InvitationStatus | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        at: datetime | None = None,
    ) -> PageResult[SessionInvitationSummary]:
        _validate_paging(page=page, page_size=page_size)
        effective_at = at or utc_now()
        effective_status = case(
            (
                SessionInvitationRow.status.in_(
                    (
                        InvitationStatus.PENDING.value,
                        InvitationStatus.SENT.value,
                        InvitationStatus.DELIVERY_FAILED.value,
                    )
                )
                & (SessionInvitationRow.expires_at <= effective_at),
                InvitationStatus.EXPIRED.value,
            ),
            else_=SessionInvitationRow.status,
        )
        filters = [SessionInvitationRow.session_id == session_id]
        if status is not None:
            filters.append(effective_status == status.value)
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(SessionInvitationRow.token_hint, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(SessionStakeholderGroupRow.name, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(ParticipantRow.alias, "")).like(
                        pattern, escape="\\"
                    ),
                )
            )
        base = (
            select(
                SessionInvitationRow,
                SessionStakeholderGroupRow.name.label("group_name"),
                ParticipantRow.alias.label("participant_alias"),
                effective_status.label("effective_status"),
            )
            .select_from(SessionInvitationRow)
            .outerjoin(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == SessionInvitationRow.assigned_group_id,
            )
            .outerjoin(
                ParticipantRow,
                ParticipantRow.participant_id
                == SessionInvitationRow.redeemed_participant_id,
            )
            .where(*filters)
        )
        count_statement = select(func.count()).select_from(base.subquery())
        statement = (
            base.order_by(
                SessionInvitationRow.created_at.desc(),
                SessionInvitationRow.invitation_id,
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        try:
            with self._session_factory() as database_session:
                total = database_session.scalar(count_statement) or 0
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Invitations could not be loaded.") from error
        return PageResult(
            items=tuple(
                SessionInvitationSummary(
                    invitation_id=str(row.SessionInvitationRow.invitation_id),
                    token_hint=row.SessionInvitationRow.token_hint,
                    group_name=row.group_name,
                    status=InvitationStatus(row.effective_status),
                    expires_at=row.SessionInvitationRow.expires_at,
                    sent_at=row.SessionInvitationRow.sent_at,
                    send_count=row.SessionInvitationRow.send_count,
                    redeemed_at=row.SessionInvitationRow.redeemed_at,
                    participant_label=(
                        None
                        if row.SessionInvitationRow.redeemed_participant_id is None
                        else _participant_label(
                            row.SessionInvitationRow.redeemed_participant_id,
                            row.participant_alias,
                        )
                    ),
                    created_at=row.SessionInvitationRow.created_at,
                )
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def list_session_participants(
        self,
        session_id: str,
        *,
        search: str | None = None,
        access_status: ParticipantAccessStatus | None = None,
        progress: str | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[SessionParticipantSummary]:
        _validate_paging(page=page, page_size=page_size)
        progress_expression = _participant_progress_expression()
        filters = [ParticipantRow.session_id == session_id]
        if access_status is not None:
            filters.append(ParticipantRow.access_status == access_status.value)
        if progress is not None:
            allowed = {"enrolled", "joined", "started", "submitted", "completed"}
            if progress not in allowed:
                raise ValueError("Unsupported participant progress filter.")
            filters.append(progress_expression == progress)
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(ParticipantRow.alias, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(SessionStakeholderGroupRow.name).like(
                        pattern, escape="\\"
                    ),
                )
            )
        order = {
            "newest": (
                ParticipantRow.enrolled_at.desc(),
                ParticipantRow.participant_id,
            ),
            "oldest": (ParticipantRow.enrolled_at, ParticipantRow.participant_id),
            "name": (
                func.lower(func.coalesce(ParticipantRow.alias, "")),
                ParticipantRow.participant_id,
            ),
        }.get(sort)
        if order is None:
            raise ValueError("Unsupported participant sort.")
        base = (
            select(
                ParticipantRow,
                SessionStakeholderGroupRow.name.label("group_name"),
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == ParticipantRow.session_stakeholder_group_id,
            )
            .where(*filters)
        )
        try:
            with self._session_factory() as database_session:
                total = (
                    database_session.scalar(
                        select(func.count()).select_from(base.subquery())
                    )
                    or 0
                )
                rows = database_session.execute(
                    base.order_by(*order)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Participants could not be loaded.") from error
        return PageResult(
            items=tuple(
                _participant_summary(row.ParticipantRow, row.group_name) for row in rows
            ),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def get_session_participant_detail(
        self,
        session_id: str,
        participant_id: str,
    ) -> SessionParticipantDetail | None:
        statement = (
            select(
                ParticipantRow,
                SessionStakeholderGroupRow.name.label("group_name"),
                SessionConfigurationVersionRow.version_number,
                func.count(SubmissionRow.submission_id).label("submission_count"),
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == ParticipantRow.session_stakeholder_group_id,
            )
            .join(
                SessionConfigurationVersionRow,
                SessionConfigurationVersionRow.configuration_version_id
                == ParticipantRow.configuration_version_id,
            )
            .outerjoin(
                SubmissionRow,
                SubmissionRow.participant_id == ParticipantRow.participant_id,
            )
            .where(
                ParticipantRow.session_id == session_id,
                ParticipantRow.participant_id == participant_id,
            )
            .group_by(
                ParticipantRow.participant_id,
                SessionStakeholderGroupRow.name,
                SessionConfigurationVersionRow.version_number,
            )
        )
        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).one_or_none()
        except SQLAlchemyError as error:
            raise PageQueryError("Participant details could not be loaded.") from error
        if row is None:
            return None
        participant = row.ParticipantRow
        return SessionParticipantDetail(
            summary=_participant_summary(participant, row.group_name),
            configuration_version=row.version_number,
            invitation_id=(
                None
                if participant.invitation_id is None
                else str(participant.invitation_id)
            ),
            joined_at=participant.joined_at,
            started_at=participant.started_at,
            submitted_at=participant.submitted_at,
            completed_at=participant.completed_at,
            updated_at=participant.updated_at,
            submission_count=int(row.submission_count),
        )

    def list_session_submissions(
        self,
        session_id: str,
        *,
        search: str | None = None,
        status: SubmissionStatus | None = None,
        validation_status: ValidationStatus | None = None,
        review_status: SubmissionReviewStatus | None = None,
        sort: str = "newest",
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[SessionSubmissionSummary]:
        _validate_paging(page=page, page_size=page_size)
        validation = aliased(SubmissionValidationRow)
        review = aliased(SubmissionReviewDecisionRow)
        filters = [SubmissionRow.session_id == session_id]
        if status is not None:
            filters.append(SubmissionRow.status == status.value)
        if validation_status is not None:
            filters.append(validation.status == validation_status.value)
        if review_status is not None:
            if review_status == SubmissionReviewStatus.PENDING:
                filters.append(review.decision_id.is_(None))
            else:
                filters.append(review.status == review_status.value)
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(ParticipantRow.alias, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(SessionStakeholderGroupRow.name).like(
                        pattern, escape="\\"
                    ),
                )
            )
        order = {
            "newest": (SubmissionRow.updated_at.desc(), SubmissionRow.submission_id),
            "oldest": (SubmissionRow.updated_at, SubmissionRow.submission_id),
            "participant": (
                func.lower(func.coalesce(ParticipantRow.alias, "")),
                SubmissionRow.submission_id,
            ),
        }.get(sort)
        if order is None:
            raise ValueError("Unsupported submission sort.")
        base = (
            select(
                SubmissionRow,
                ParticipantRow.alias.label("participant_alias"),
                SessionStakeholderGroupRow.name.label("group_name"),
                validation.status.label("validation_status"),
                validation.consistency_ratio.label("consistency_ratio"),
                review.status.label("review_status"),
            )
            .join(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == SubmissionRow.session_stakeholder_group_id,
            )
            .outerjoin(
                validation,
                validation.validation_id
                == _latest_validation_id(SubmissionRow.submission_id),
            )
            .outerjoin(
                review,
                review.decision_id == _latest_review_id(SubmissionRow.submission_id),
            )
            .where(*filters)
        )
        try:
            with self._session_factory() as database_session:
                total = (
                    database_session.scalar(
                        select(func.count()).select_from(base.subquery())
                    )
                    or 0
                )
                rows = database_session.execute(
                    base.order_by(*order)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Submissions could not be loaded.") from error
        return PageResult(
            items=tuple(
                SessionSubmissionSummary(
                    submission_id=str(row.SubmissionRow.submission_id),
                    participant_label=_participant_label(
                        row.SubmissionRow.participant_id,
                        row.participant_alias,
                    ),
                    group_name=row.group_name,
                    attempt_number=row.SubmissionRow.attempt_number,
                    status=SubmissionStatus(row.SubmissionRow.status),
                    validation_status=(
                        None
                        if row.validation_status is None
                        else ValidationStatus(row.validation_status)
                    ),
                    consistency_ratio=(
                        None
                        if row.consistency_ratio is None
                        else str(row.consistency_ratio)
                    ),
                    submitted_at=row.SubmissionRow.submitted_at,
                    review_status=(
                        SubmissionReviewStatus.PENDING
                        if row.review_status is None
                        else SubmissionReviewStatus(row.review_status)
                    ),
                )
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def get_session_submission_detail(
        self,
        session_id: str,
        submission_id: str,
    ) -> SessionSubmissionDetail | None:
        validation = aliased(SubmissionValidationRow)
        review = aliased(SubmissionReviewDecisionRow)
        answer_count = (
            select(func.count(SubmissionAnswerRow.submission_answer_id))
            .where(SubmissionAnswerRow.submission_id == SubmissionRow.submission_id)
            .correlate(SubmissionRow)
            .scalar_subquery()
        )
        required_count = (
            select(func.count(ResponseQuestionDefinitionRow.question_definition_id))
            .where(
                ResponseQuestionDefinitionRow.configuration_version_id
                == SubmissionRow.configuration_version_id,
                ResponseQuestionDefinitionRow.required.is_(True),
            )
            .correlate(SubmissionRow)
            .scalar_subquery()
        )
        statement = (
            select(
                SubmissionRow,
                ParticipantRow.alias.label("participant_alias"),
                SessionStakeholderGroupRow.name.label("group_name"),
                validation.validation_id.label("detail_validation_id"),
                validation.status.label("detail_validation_status"),
                validation.consistency_ratio.label("detail_consistency_ratio"),
                validation.completed_at.label("detail_validation_completed_at"),
                review.status.label("detail_review_status"),
                review.reviewer_notes.label("detail_review_notes"),
                review.decided_at.label("detail_reviewed_at"),
                review.decided_by.label("detail_reviewed_by"),
                answer_count.label("answer_count"),
                required_count.label("required_count"),
            )
            .join(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == SubmissionRow.session_stakeholder_group_id,
            )
            .outerjoin(
                validation,
                validation.validation_id
                == _latest_validation_id(SubmissionRow.submission_id),
            )
            .outerjoin(
                review,
                review.decision_id == _latest_review_id(SubmissionRow.submission_id),
            )
            .where(
                SubmissionRow.session_id == session_id,
                SubmissionRow.submission_id == submission_id,
            )
        )
        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).one_or_none()
                if row is None:
                    return None
                messages: tuple[str, ...] = ()
                if row.detail_validation_id is not None:
                    messages = tuple(
                        database_session.scalars(
                            select(ValidationMessageRow.safe_message)
                            .where(
                                ValidationMessageRow.validation_id
                                == row.detail_validation_id
                            )
                            .order_by(ValidationMessageRow.display_order)
                        )
                    )
        except SQLAlchemyError as error:
            raise PageQueryError("Submission details could not be loaded.") from error
        review_status = (
            SubmissionReviewStatus.PENDING
            if row.detail_review_status is None
            else SubmissionReviewStatus(row.detail_review_status)
        )
        summary = SessionSubmissionSummary(
            submission_id=str(row.SubmissionRow.submission_id),
            participant_label=_participant_label(
                row.SubmissionRow.participant_id,
                row.participant_alias,
            ),
            group_name=row.group_name,
            attempt_number=row.SubmissionRow.attempt_number,
            status=SubmissionStatus(row.SubmissionRow.status),
            validation_status=(
                None
                if row.detail_validation_status is None
                else ValidationStatus(row.detail_validation_status)
            ),
            consistency_ratio=(
                None
                if row.detail_consistency_ratio is None
                else str(row.detail_consistency_ratio)
            ),
            submitted_at=row.SubmissionRow.submitted_at,
            review_status=review_status,
        )
        return SessionSubmissionDetail(
            summary=summary,
            participant_id=str(row.SubmissionRow.participant_id),
            response_format=ResponseFormat(row.SubmissionRow.response_format),
            answer_count=int(row.answer_count),
            required_answer_count=int(row.required_count),
            last_saved_at=row.SubmissionRow.last_saved_at,
            answers_hash=row.SubmissionRow.answers_hash,
            validation_id=(
                None
                if row.detail_validation_id is None
                else str(row.detail_validation_id)
            ),
            validation_completed_at=row.detail_validation_completed_at,
            validation_messages=messages,
            review_status=review_status,
            review_notes=row.detail_review_notes,
            reviewed_at=row.detail_reviewed_at,
            reviewed_by=row.detail_reviewed_by,
        )

    def list_validation_queue(
        self,
        session_id: str,
        *,
        search: str | None = None,
        review_status: SubmissionReviewStatus | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[ValidationQueueItem]:
        _validate_paging(page=page, page_size=page_size)
        validation = aliased(SubmissionValidationRow)
        review = aliased(SubmissionReviewDecisionRow)
        message_count = (
            select(func.count(ValidationMessageRow.validation_message_id))
            .where(ValidationMessageRow.validation_id == validation.validation_id)
            .correlate(validation)
            .scalar_subquery()
        )
        filters = [
            SubmissionRow.session_id == session_id,
            SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
        ]
        if review_status is not None:
            if review_status == SubmissionReviewStatus.PENDING:
                filters.append(review.decision_id.is_(None))
            else:
                filters.append(review.status == review_status.value)
        normalized_search = (search or "").strip().lower()
        if normalized_search:
            pattern = f"%{_escape_like(normalized_search)}%"
            filters.append(
                or_(
                    func.lower(func.coalesce(ParticipantRow.alias, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(SessionStakeholderGroupRow.name).like(
                        pattern, escape="\\"
                    ),
                )
            )
        base = (
            select(
                SubmissionRow,
                ParticipantRow.alias.label("participant_alias"),
                SessionStakeholderGroupRow.name.label("group_name"),
                validation.status.label("validation_status"),
                validation.consistency_ratio.label("consistency_ratio"),
                message_count.label("message_count"),
                review.status.label("review_status"),
                review.decided_at.label("reviewed_at"),
                review.decided_by.label("reviewed_by"),
            )
            .join(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == SubmissionRow.session_stakeholder_group_id,
            )
            .outerjoin(
                validation,
                validation.validation_id
                == _latest_validation_id(SubmissionRow.submission_id),
            )
            .outerjoin(
                review,
                review.decision_id == _latest_review_id(SubmissionRow.submission_id),
            )
            .where(*filters)
        )
        try:
            with self._session_factory() as database_session:
                total = (
                    database_session.scalar(
                        select(func.count()).select_from(base.subquery())
                    )
                    or 0
                )
                rows = database_session.execute(
                    base.order_by(
                        case(
                            (review.decision_id.is_(None), 0),
                            (
                                review.status
                                == SubmissionReviewStatus.NEEDS_REVIEW.value,
                                1,
                            ),
                            else_=2,
                        ),
                        SubmissionRow.submitted_at,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Validation queue could not be loaded.") from error
        return PageResult(
            items=tuple(
                ValidationQueueItem(
                    submission_id=str(row.SubmissionRow.submission_id),
                    participant_label=_participant_label(
                        row.SubmissionRow.participant_id,
                        row.participant_alias,
                    ),
                    group_name=row.group_name,
                    attempt_number=row.SubmissionRow.attempt_number,
                    submitted_at=row.SubmissionRow.submitted_at,
                    validation_status=(
                        None
                        if row.validation_status is None
                        else ValidationStatus(row.validation_status)
                    ),
                    consistency_ratio=(
                        None
                        if row.consistency_ratio is None
                        else str(row.consistency_ratio)
                    ),
                    validation_message_count=int(row.message_count or 0),
                    review_status=(
                        SubmissionReviewStatus.PENDING
                        if row.review_status is None
                        else SubmissionReviewStatus(row.review_status)
                    ),
                    reviewed_at=row.reviewed_at,
                    reviewed_by=row.reviewed_by,
                )
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def list_active_algorithm_implementations(
        self,
        *,
        role: AlgorithmRole | None = None,
    ) -> tuple[AlgorithmImplementationOption, ...]:
        filters = [AlgorithmImplementationRow.status == "active"]
        if role is not None:
            filters.append(AlgorithmImplementationRow.role == role.value)
        statement = (
            select(AlgorithmImplementationRow)
            .where(*filters)
            .order_by(
                AlgorithmImplementationRow.role,
                AlgorithmImplementationRow.conceptual_method,
                AlgorithmImplementationRow.stable_key,
            )
        )
        try:
            with self._session_factory() as database_session:
                rows = database_session.scalars(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Algorithm implementations could not be loaded."
            ) from error
        return tuple(
            AlgorithmImplementationOption(
                algorithm_implementation_id=str(row.algorithm_implementation_id),
                stable_key=row.stable_key,
                role=AlgorithmRole(row.role),
                conceptual_method=row.conceptual_method,
                provider=row.provider,
                library_name=row.library_name,
                library_version=row.library_version,
            )
            for row in rows
        )

    def list_admin_audit_events(
        self,
        *,
        search: str | None = None,
        action: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> PageResult[AdminAuditEventSummary]:
        _validate_paging(page=page, page_size=page_size)
        normalized_search = search.strip() if search is not None else ""
        normalized_action = action.strip() if action is not None else ""
        filters: list[Any] = []
        if normalized_search:
            escaped = _escape_like(normalized_search.casefold())
            pattern = f"%{escaped}%"
            filters.append(
                or_(
                    func.lower(AuditEventRow.entity_type).like(pattern, escape="\\"),
                    func.lower(AuditEventRow.entity_id).like(pattern, escape="\\"),
                    func.lower(AuditEventRow.correlation_id).like(pattern, escape="\\"),
                    func.lower(func.coalesce(AuditEventRow.actor_id, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(SessionRow.title, "")).like(
                        pattern, escape="\\"
                    ),
                    func.lower(func.coalesce(SessionRow.public_slug, "")).like(
                        pattern, escape="\\"
                    ),
                )
            )
        if normalized_action:
            filters.append(AuditEventRow.action == normalized_action)
        base = (
            select(AuditEventRow)
            .outerjoin(SessionRow, SessionRow.session_id == AuditEventRow.session_id)
            .where(*filters)
        )
        count_statement = (
            select(func.count(AuditEventRow.audit_event_id))
            .outerjoin(SessionRow, SessionRow.session_id == AuditEventRow.session_id)
            .where(*filters)
        )
        statement = (
            base.add_columns(
                SessionRow.title.label("session_title"),
                SessionRow.public_slug.label("public_slug"),
            )
            .order_by(
                AuditEventRow.occurred_at.desc(),
                AuditEventRow.audit_event_id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        try:
            with self._session_factory() as database_session:
                total = database_session.scalar(count_statement) or 0
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Audit events could not be loaded.") from error
        return PageResult(
            items=tuple(_admin_audit_summary(row) for row in rows),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def list_audit_actions(self) -> tuple[str, ...]:
        statement = (
            select(AuditEventRow.action).distinct().order_by(AuditEventRow.action)
        )
        try:
            with self._session_factory() as database_session:
                actions = database_session.scalars(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Audit filters could not be loaded.") from error
        return tuple(str(action) for action in actions)

    def is_public_slug_available(self, public_slug: str) -> bool:
        normalized_slug = public_slug.strip()
        if not normalized_slug:
            raise ValueError("public_slug cannot be empty.")
        statement = select(
            ~select(SessionRow.session_id)
            .where(SessionRow.public_slug == normalized_slug)
            .exists()
        )
        try:
            with self._session_factory() as database_session:
                return bool(database_session.scalar(statement))
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Session slug availability could not be checked."
            ) from error

    def get_scenario_library_metrics(self) -> ScenarioLibraryMetrics:
        definition_statement = select(
            func.count(ScenarioDefinitionRow.scenario_definition_id)
        )
        snapshot_statement = select(
            ScenarioSnapshotRow.status,
            func.count(ScenarioSnapshotRow.scenario_snapshot_id),
        ).group_by(ScenarioSnapshotRow.status)

        try:
            with self._session_factory() as database_session:
                definition_count = database_session.scalar(definition_statement) or 0
                status_rows = database_session.execute(snapshot_statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Scenario library metrics could not be loaded."
            ) from error

        counts = {status: 0 for status in ScenarioSnapshotStatus}
        for raw_status, count in status_rows:
            try:
                status = ScenarioSnapshotStatus(raw_status)
            except ValueError:
                continue
            counts[status] = int(count)

        return ScenarioLibraryMetrics(
            definition_count=int(definition_count),
            snapshot_count=sum(counts.values()),
            ready_count=counts[ScenarioSnapshotStatus.READY],
            attention_count=(
                counts[ScenarioSnapshotStatus.VALIDATING]
                + counts[ScenarioSnapshotStatus.INVALID]
            ),
        )

    def list_scenario_domains(self) -> tuple[str, ...]:
        statement = (
            select(ScenarioSnapshotRow.domain)
            .distinct()
            .order_by(ScenarioSnapshotRow.domain)
        )
        try:
            with self._session_factory() as database_session:
                domains = database_session.scalars(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Scenario domains could not be loaded.") from error
        return tuple(domain for domain in domains if domain.strip())

    def list_scenario_snapshots(
        self,
        *,
        search: str | None = None,
        status: ScenarioSnapshotStatus | None = None,
        domain: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[ScenarioSnapshotSummary]:
        _validate_paging(page=page, page_size=page_size)
        normalized_search = search.strip() if search is not None else ""
        normalized_domain = domain.strip() if domain is not None else ""

        filters = []
        if normalized_search:
            escaped_search = _escape_like(normalized_search.casefold())
            pattern = f"%{escaped_search}%"
            filters.append(
                or_(
                    func.lower(ScenarioSnapshotRow.title).like(
                        pattern,
                        escape="\\",
                    ),
                    func.lower(ScenarioSnapshotRow.domain).like(
                        pattern,
                        escape="\\",
                    ),
                    func.lower(ScenarioDefinitionRow.scenario_key).like(
                        pattern,
                        escape="\\",
                    ),
                )
            )
        if status is not None:
            filters.append(ScenarioSnapshotRow.status == status.value)
        if normalized_domain:
            filters.append(ScenarioSnapshotRow.domain == normalized_domain)

        count_statement = (
            select(func.count(ScenarioSnapshotRow.scenario_snapshot_id))
            .join(ScenarioDefinitionRow)
            .where(*filters)
        )
        statement = (
            _scenario_summary_statement()
            .where(*filters)
            .order_by(
                ScenarioSnapshotRow.created_at.desc(),
                ScenarioSnapshotRow.title,
                ScenarioSnapshotRow.declared_version.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        try:
            with self._session_factory() as database_session:
                total = database_session.scalar(count_statement) or 0
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Scenario snapshots could not be loaded.") from error

        return PageResult(
            items=tuple(_scenario_summary(row) for row in rows),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def get_scenario_snapshot_detail(
        self,
        scenario_snapshot_id: str,
    ) -> ScenarioSnapshotDetail | None:
        if not scenario_snapshot_id.strip():
            raise ValueError("scenario_snapshot_id cannot be empty.")

        matrix_value_count = (
            select(func.count())
            .select_from(ScenarioMatrixValueRow)
            .where(
                ScenarioMatrixValueRow.scenario_snapshot_id
                == ScenarioSnapshotRow.scenario_snapshot_id
            )
            .correlate(ScenarioSnapshotRow)
            .scalar_subquery()
        )
        summary_statement = (
            _scenario_summary_statement()
            .add_columns(
                ScenarioSnapshotRow.policy_question,
                ScenarioSnapshotRow.schema_version,
                ScenarioSnapshotRow.manifest_schema_version,
                ScenarioSnapshotRow.manifest_json,
                ScenarioSnapshotRow.materialized_input_hash,
                ScenarioSnapshotRow.source_uri,
                ScenarioSnapshotRow.importer_version,
                ScenarioSnapshotRow.created_by,
                matrix_value_count.label("matrix_value_count"),
            )
            .where(ScenarioSnapshotRow.scenario_snapshot_id == scenario_snapshot_id)
        )
        criterion_statement = (
            select(
                ScenarioCriterionRow.criterion_key,
                ScenarioCriterionRow.name,
                ScenarioCriterionRow.description,
                ScenarioCriterionRow.direction,
                ScenarioCriterionRow.data_type,
                ScenarioCriterionRow.unit,
                ScenarioCriterionRow.required,
                ScenarioCriterionRow.display_order,
            )
            .where(ScenarioCriterionRow.scenario_snapshot_id == scenario_snapshot_id)
            .order_by(ScenarioCriterionRow.display_order)
        )
        alternative_statement = (
            select(
                ScenarioAlternativeRow.alternative_key,
                ScenarioAlternativeRow.name,
                ScenarioAlternativeRow.description,
                ScenarioAlternativeRow.display_order,
            )
            .where(ScenarioAlternativeRow.scenario_snapshot_id == scenario_snapshot_id)
            .order_by(ScenarioAlternativeRow.display_order)
        )
        scale_statement = (
            select(
                ScenarioScaleRow.scale_id,
                ScenarioScaleRow.scale_key,
                ScenarioScaleRow.name,
                ScenarioScaleRow.scale_type,
                ScenarioScaleRow.ordered,
                ScenarioScaleRow.definition_version,
                ScenarioScaleRow.metadata_json,
                func.count(ScenarioScaleValueRow.scale_value_id).label("value_count"),
            )
            .outerjoin(ScenarioScaleValueRow)
            .where(ScenarioScaleRow.scenario_snapshot_id == scenario_snapshot_id)
            .group_by(ScenarioScaleRow.scale_id)
            .order_by(ScenarioScaleRow.scale_key)
        )
        file_statement = (
            select(
                ScenarioSnapshotFileRow.logical_path,
                ScenarioSnapshotFileRow.file_role,
                ScenarioSnapshotFileRow.media_type,
                ScenarioSnapshotFileRow.byte_size,
                ScenarioSnapshotFileRow.content_hash,
                ScenarioSnapshotFileRow.inline_bytes,
            )
            .where(ScenarioSnapshotFileRow.scenario_snapshot_id == scenario_snapshot_id)
            .order_by(ScenarioSnapshotFileRow.logical_path)
        )

        try:
            with self._session_factory() as database_session:
                summary_row = database_session.execute(summary_statement).one_or_none()
                if summary_row is None:
                    return None
                criterion_rows = database_session.execute(criterion_statement).all()
                alternative_rows = database_session.execute(alternative_statement).all()
                scale_rows = database_session.execute(scale_statement).all()
                file_rows = database_session.execute(file_statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Scenario snapshot details could not be loaded."
            ) from error

        configuration_defaults = _scenario_configuration_defaults(
            summary_row.manifest_json,
            file_rows,
        )
        return ScenarioSnapshotDetail(
            summary=_scenario_summary(summary_row),
            policy_question=summary_row.policy_question,
            schema_version=summary_row.schema_version,
            manifest_schema_version=summary_row.manifest_schema_version,
            manifest_json=summary_row.manifest_json,
            materialized_input_hash=summary_row.materialized_input_hash,
            source_uri=summary_row.source_uri,
            importer_version=summary_row.importer_version,
            created_by=summary_row.created_by,
            matrix_value_count=summary_row.matrix_value_count,
            criteria=tuple(
                ScenarioCriterionPreview(
                    criterion_key=row.criterion_key,
                    name=row.name,
                    description=row.description,
                    direction=CriterionDirection(row.direction),
                    data_type=CriterionDataType(row.data_type),
                    unit=row.unit,
                    required=row.required,
                    display_order=row.display_order,
                )
                for row in criterion_rows
            ),
            alternatives=tuple(
                ScenarioAlternativePreview(
                    alternative_key=row.alternative_key,
                    name=row.name,
                    description=row.description,
                    display_order=row.display_order,
                )
                for row in alternative_rows
            ),
            scales=tuple(
                ScenarioScalePreview(
                    scale_id=str(row.scale_id),
                    scale_key=row.scale_key,
                    name=row.name,
                    scale_type=row.scale_type,
                    ordered=row.ordered,
                    definition_version=row.definition_version,
                    value_count=row.value_count,
                    is_application_defined=(
                        row.metadata_json.get("source") == "application"
                    ),
                )
                for row in scale_rows
            ),
            default_response_format=_scenario_default_response_format(
                configuration_defaults
            ),
            default_scale_key=_scenario_default_scale_key(configuration_defaults),
            stakeholder_group_defaults=_scenario_stakeholder_defaults(
                configuration_defaults
            ),
            files=tuple(
                ScenarioFilePreview(
                    logical_path=row.logical_path,
                    file_role=ScenarioFileRole(row.file_role),
                    media_type=row.media_type,
                    byte_size=row.byte_size,
                    content_hash=row.content_hash,
                )
                for row in file_rows
            ),
        )


def _scenario_source_document(file_rows: Sequence[Any]) -> dict[str, Any]:
    for row in file_rows:
        if ScenarioFileRole(row.file_role) != ScenarioFileRole.SCENARIO_CONFIG:
            continue
        if row.inline_bytes is None:
            continue
        try:
            document = json.loads(bytes(row.inline_bytes).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return {}
        return document if isinstance(document, dict) else {}
    return {}


def _scenario_configuration_defaults(
    manifest: Mapping[str, Any],
    file_rows: Sequence[Any],
) -> dict[str, Any]:
    persisted = manifest.get("configuration_defaults")
    if isinstance(persisted, Mapping):
        return dict(persisted)
    source = _scenario_source_document(file_rows)
    preference = source.get("preference_collection")
    preference = preference if isinstance(preference, Mapping) else {}
    raw_groups = source.get("stakeholder_groups")
    return {
        "default_response_method": preference.get("default_method"),
        "default_scale_key": preference.get("default_scale_id"),
        "stakeholder_groups": raw_groups if isinstance(raw_groups, list) else [],
    }


def _scenario_default_response_format(
    defaults: dict[str, Any],
) -> ResponseFormat | None:
    value = str(defaults.get("default_response_method", "")).strip().lower()
    aliases = {
        "pairwise": ResponseFormat.PAIRWISE,
        "pairwise_comparison": ResponseFormat.PAIRWISE,
        "criterion_linguistic_rating": ResponseFormat.DIRECT_RATING,
        "direct_rating": ResponseFormat.DIRECT_RATING,
        "direct_ranking": ResponseFormat.DIRECT_RANKING,
    }
    return aliases.get(value)


def _scenario_default_scale_key(defaults: dict[str, Any]) -> str | None:
    value = defaults.get("default_scale_key")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _scenario_stakeholder_defaults(
    defaults: dict[str, Any],
) -> tuple[ScenarioStakeholderDefault, ...]:
    raw_groups = defaults.get("stakeholder_groups")
    if not isinstance(raw_groups, list):
        return ()

    groups: list[tuple[str, str, str, Decimal | None, bool]] = []
    seen_keys: set[str] = set()
    for raw_group in raw_groups:
        if not isinstance(raw_group, dict):
            continue
        raw_group_key = str(raw_group.get("id", "")).strip()
        name = str(raw_group.get("label", raw_group.get("name", ""))).strip()
        group_key = _safe_stakeholder_group_key(raw_group_key or name)
        if not group_key or not name:
            continue
        base_key = group_key
        suffix = 2
        while group_key in seen_keys:
            group_key = f"{base_key}_{suffix}"
            suffix += 1
        seen_keys.add(group_key)
        raw_power = raw_group.get("default_group_voting_power")
        power: Decimal | None
        try:
            power = Decimal(str(raw_power)) if raw_power is not None else None
        except (InvalidOperation, ValueError):
            power = None
        if power is not None and (not power.is_finite() or power < 0):
            power = None
        groups.append(
            (
                group_key,
                name,
                (
                    str(raw_group.get("description", "")).strip()
                    or f"Participants represented by {name}."
                ),
                power,
                bool(raw_group.get("required", True)),
            )
        )
    if not groups:
        return ()

    powers = [item[3] for item in groups]
    if (
        any(power is None for power in powers)
        or sum(
            (power for power in powers if power is not None),
            Decimal(0),
        )
        <= 0
    ):
        normalized_powers = [Decimal(1) for _ in groups]
    else:
        normalized_powers = [
            power if power is not None else Decimal(0) for power in powers
        ]
    allocations = _normalized_allocation_units(normalized_powers)
    return tuple(
        ScenarioStakeholderDefault(
            group_key=group_key,
            name=name,
            description=description,
            allocation_units=allocation_units,
            required=required,
        )
        for (group_key, name, description, _, required), allocation_units in zip(
            groups,
            allocations,
            strict=True,
        )
    )


def _safe_stakeholder_group_key(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "_", value.strip().lower()).strip("_-")
    if not normalized:
        return ""
    if not normalized[0].isalpha():
        normalized = f"group_{normalized}"
    return normalized


def _normalized_allocation_units(powers: list[Decimal]) -> list[int]:
    total = sum(powers, Decimal(0))
    exact = [power * 10_000 / total for power in powers]
    units = [int(value.to_integral_value(rounding=ROUND_FLOOR)) for value in exact]
    remaining = 10_000 - sum(units)
    order = sorted(
        range(len(exact)),
        key=lambda index: (exact[index] - units[index], -index),
        reverse=True,
    )
    for index in order[:remaining]:
        units[index] += 1
    return units


_VALIDATION_ATTENTION_STATUSES = (
    ValidationStatus.VALID_WITH_WARNING.value,
    ValidationStatus.INVALID.value,
    ValidationStatus.ERROR.value,
)


def _session_filters(
    *,
    search: str | None,
    status: SessionStatus | None,
    scenario_key: str | None,
) -> list[Any]:
    normalized_search = search.strip() if search is not None else ""
    normalized_scenario = scenario_key.strip() if scenario_key is not None else ""
    filters: list[Any] = []
    if normalized_search:
        escaped = _escape_like(normalized_search.casefold())
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                func.lower(SessionRow.title).like(pattern, escape="\\"),
                func.lower(SessionRow.public_slug).like(pattern, escape="\\"),
            )
        )
    if status is not None:
        filters.append(SessionRow.status == status.value)
    if normalized_scenario:
        filters.append(ScenarioDefinitionRow.scenario_key == normalized_scenario)
    return filters


def _session_attention_count() -> Any:
    return (
        select(func.count(func.distinct(SubmissionValidationRow.submission_id)))
        .select_from(SubmissionValidationRow)
        .join(
            SubmissionRow,
            SubmissionRow.submission_id == SubmissionValidationRow.submission_id,
        )
        .where(
            SubmissionRow.session_id == SessionRow.session_id,
            SubmissionValidationRow.status.in_(_VALIDATION_ATTENTION_STATUSES),
        )
        .correlate(SessionRow)
        .scalar_subquery()
    )


def _needs_attention_expression(attention_count: Any) -> Any:
    return or_(
        SessionRow.status == SessionStatus.PAUSED.value,
        ScenarioSnapshotRow.status != ScenarioSnapshotStatus.READY.value,
        (
            SessionRow.status.in_(
                (SessionStatus.DRAFT.value, SessionStatus.SCHEDULED.value)
            )
            & SessionRow.active_configuration_version_id.is_(None)
        ),
        attention_count > 0,
    )


def _admin_session_summary_statement() -> Select:
    participant_count = (
        select(func.count(ParticipantRow.participant_id))
        .where(ParticipantRow.session_id == SessionRow.session_id)
        .correlate(SessionRow)
        .scalar_subquery()
    )
    submitted_count = (
        select(func.count(ParticipantRow.participant_id))
        .where(
            ParticipantRow.session_id == SessionRow.session_id,
            ParticipantRow.submitted_at.is_not(None),
        )
        .correlate(SessionRow)
        .scalar_subquery()
    )
    attention_count = _session_attention_count()
    active_configuration_version = (
        select(SessionConfigurationVersionRow.version_number)
        .where(
            SessionConfigurationVersionRow.configuration_version_id
            == SessionRow.active_configuration_version_id
        )
        .correlate(SessionRow)
        .scalar_subquery()
    )
    return (
        select(
            SessionRow.session_id,
            SessionRow.scenario_snapshot_id,
            SessionRow.public_slug,
            SessionRow.title,
            SessionRow.description,
            SessionRow.status,
            ScenarioDefinitionRow.scenario_key,
            ScenarioSnapshotRow.title.label("scenario_title"),
            ScenarioSnapshotRow.declared_version.label("scenario_version"),
            ScenarioSnapshotRow.status.label("scenario_status"),
            active_configuration_version.label("active_configuration_version"),
            participant_count.label("participant_count"),
            submitted_count.label("submitted_participant_count"),
            attention_count.label("validation_attention_count"),
            _needs_attention_expression(attention_count).label("needs_attention"),
            SessionRow.opens_at,
            SessionRow.closes_at,
            SessionRow.paused_at,
            SessionRow.closed_at,
            SessionRow.updated_at,
        )
        .select_from(SessionRow)
        .join(
            ScenarioSnapshotRow,
            ScenarioSnapshotRow.scenario_snapshot_id == SessionRow.scenario_snapshot_id,
        )
        .join(ScenarioDefinitionRow)
    )


def _admin_session_summary(row: Any) -> AdminSessionSummary:
    return AdminSessionSummary(
        session_id=str(row.session_id),
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        public_slug=row.public_slug,
        title=row.title,
        description=row.description,
        status=SessionStatus(row.status),
        scenario_key=row.scenario_key,
        scenario_title=row.scenario_title,
        scenario_version=row.scenario_version,
        scenario_status=ScenarioSnapshotStatus(row.scenario_status),
        active_configuration_version=(
            None
            if row.active_configuration_version is None
            else int(row.active_configuration_version)
        ),
        participant_count=int(row.participant_count),
        submitted_participant_count=int(row.submitted_participant_count),
        validation_attention_count=int(row.validation_attention_count),
        needs_attention=bool(row.needs_attention),
        opens_at=row.opens_at,
        closes_at=row.closes_at,
        paused_at=row.paused_at,
        closed_at=row.closed_at,
        updated_at=row.updated_at,
    )


def _load_configurations(
    database_session: DatabaseSession,
    session_id: str,
    *,
    active_configuration_id: Any,
) -> tuple[Any, ...]:
    question_count = (
        select(func.count(ResponseQuestionDefinitionRow.question_definition_id))
        .where(
            ResponseQuestionDefinitionRow.configuration_version_id
            == SessionConfigurationVersionRow.configuration_version_id
        )
        .correlate(SessionConfigurationVersionRow)
        .scalar_subquery()
    )
    stakeholder_group_count = (
        select(func.count(SessionStakeholderGroupRow.session_stakeholder_group_id))
        .where(
            SessionStakeholderGroupRow.configuration_version_id
            == SessionConfigurationVersionRow.configuration_version_id
        )
        .correlate(SessionConfigurationVersionRow)
        .scalar_subquery()
    )
    statement = (
        select(
            SessionConfigurationVersionRow,
            ScenarioScaleRow.name.label("scale_name"),
            question_count.label("question_count"),
            stakeholder_group_count.label("stakeholder_group_count"),
        )
        .join(
            ScenarioScaleRow,
            ScenarioScaleRow.scale_id == SessionConfigurationVersionRow.scale_id,
        )
        .where(SessionConfigurationVersionRow.session_id == session_id)
        .order_by(SessionConfigurationVersionRow.version_number.desc())
    )
    return tuple(
        {
            **row._mapping,
            "is_active": (
                str(row.SessionConfigurationVersionRow.configuration_version_id)
                == str(active_configuration_id)
            ),
        }
        for row in database_session.execute(statement).all()
    )


def _configuration_summary(row: Any) -> SessionConfigurationSummary:
    configuration = row["SessionConfigurationVersionRow"]
    return SessionConfigurationSummary(
        configuration_version_id=str(configuration.configuration_version_id),
        version_number=configuration.version_number,
        response_format=ResponseFormat(configuration.response_format),
        response_target_type=ResponseTargetType(configuration.response_target_type),
        scale_name=row["scale_name"],
        allow_resubmissions=configuration.allow_resubmissions,
        max_submissions_per_participant=(configuration.max_submissions_per_participant),
        allow_incomplete_submission=configuration.allow_incomplete_submission,
        minimum_valid_submissions=configuration.minimum_valid_submissions,
        missing_group_policy=MissingGroupPolicy(configuration.missing_group_policy),
        consistency_threshold=(
            None
            if configuration.consistency_threshold is None
            else str(configuration.consistency_threshold)
        ),
        config_hash=configuration.config_hash,
        activated_at=configuration.activated_at,
        activated_by=configuration.activated_by,
        created_at=configuration.created_at,
        created_by=configuration.created_by,
        is_active=bool(row["is_active"]),
        question_count=int(row["question_count"]),
        stakeholder_group_count=int(row["stakeholder_group_count"]),
    )


def _load_group_progress(
    database_session: DatabaseSession,
    *,
    session_id: str,
    configuration_id: Any,
) -> tuple[tuple[SessionStakeholderGroupRow, ...], tuple[SessionGroupProgress, ...]]:
    if configuration_id is None:
        return (), ()
    group_statement = (
        select(SessionStakeholderGroupRow)
        .where(
            SessionStakeholderGroupRow.configuration_version_id == configuration_id,
            SessionStakeholderGroupRow.is_active.is_(True),
        )
        .order_by(SessionStakeholderGroupRow.display_order)
    )
    count_statement = (
        select(
            ParticipantRow.session_stakeholder_group_id,
            func.count(ParticipantRow.participant_id).label("enrolled_count"),
            func.sum(
                case((ParticipantRow.submitted_at.is_not(None), 1), else_=0)
            ).label("submitted_count"),
        )
        .where(
            ParticipantRow.session_id == session_id,
            ParticipantRow.configuration_version_id == configuration_id,
        )
        .group_by(ParticipantRow.session_stakeholder_group_id)
    )
    valid_statement = (
        select(
            SubmissionRow.session_stakeholder_group_id,
            func.count(func.distinct(SubmissionRow.submission_id)).label("valid_count"),
        )
        .join(
            SubmissionValidationRow,
            SubmissionValidationRow.submission_id == SubmissionRow.submission_id,
        )
        .where(
            SubmissionRow.session_id == session_id,
            SubmissionRow.configuration_version_id == configuration_id,
            SubmissionValidationRow.status == ValidationStatus.VALID.value,
        )
        .group_by(SubmissionRow.session_stakeholder_group_id)
    )
    groups = tuple(database_session.scalars(group_statement).all())
    counts = {
        str(row.session_stakeholder_group_id): (
            int(row.enrolled_count),
            int(row.submitted_count or 0),
        )
        for row in database_session.execute(count_statement).all()
    }
    valid_counts = {
        str(row.session_stakeholder_group_id): int(row.valid_count)
        for row in database_session.execute(valid_statement).all()
    }
    progress = tuple(
        SessionGroupProgress(
            group_id=str(group.session_stakeholder_group_id),
            group_name=group.name,
            allocation_units=group.allocation_units,
            enrolled_count=counts.get(str(group.session_stakeholder_group_id), (0, 0))[
                0
            ],
            submitted_count=counts.get(str(group.session_stakeholder_group_id), (0, 0))[
                1
            ],
            valid_count=valid_counts.get(str(group.session_stakeholder_group_id), 0),
        )
        for group in groups
    )
    return groups, progress


def _load_latest_validations(
    database_session: DatabaseSession,
    submission_ids: tuple[str, ...],
) -> dict[str, SubmissionValidationRow]:
    if not submission_ids:
        return {}
    statement = (
        select(SubmissionValidationRow)
        .where(SubmissionValidationRow.submission_id.in_(submission_ids))
        .order_by(
            SubmissionValidationRow.submission_id,
            SubmissionValidationRow.completed_at.desc().nullslast(),
            SubmissionValidationRow.validation_id.desc(),
        )
    )
    latest: dict[str, SubmissionValidationRow] = {}
    for row in database_session.scalars(statement):
        latest.setdefault(str(row.submission_id), row)
    return latest


def _participant_label(participant_id: Any, alias: str | None) -> str:
    if alias is not None and alias.strip():
        return alias.strip()
    compact = str(participant_id).replace("-", "")
    return f"Participant {compact[-8:].upper()}"


def _participant_summary(
    row: ParticipantRow,
    group_name: str,
) -> SessionParticipantSummary:
    if row.completed_at is not None:
        progress = "Completed"
    elif row.submitted_at is not None:
        progress = "Submitted"
    elif row.started_at is not None:
        progress = "Started"
    elif row.joined_at is not None:
        progress = "Joined"
    else:
        progress = "Enrolled"
    return SessionParticipantSummary(
        participant_id=str(row.participant_id),
        display_label=_participant_label(row.participant_id, row.alias),
        group_name=group_name,
        access_status=ParticipantAccessStatus(row.access_status),
        progress=progress,
        enrolled_at=row.enrolled_at,
    )


def _submission_summary(
    row: SubmissionRow,
    *,
    participant_alias: str | None,
    group_name: str,
    validation: SubmissionValidationRow | None,
) -> SessionSubmissionSummary:
    return SessionSubmissionSummary(
        submission_id=str(row.submission_id),
        participant_label=_participant_label(row.participant_id, participant_alias),
        group_name=group_name,
        attempt_number=row.attempt_number,
        status=SubmissionStatus(row.status),
        validation_status=(
            None if validation is None else ValidationStatus(validation.status)
        ),
        consistency_ratio=(
            None
            if validation is None or validation.consistency_ratio is None
            else str(validation.consistency_ratio)
        ),
        submitted_at=row.submitted_at,
    )


def _audit_summary(row: AuditEventRow) -> SessionAuditEventSummary:
    actor_display = (
        row.actor_display_snapshot
        or row.actor_id
        or row.actor_type.replace("_", " ").title()
    )
    return SessionAuditEventSummary(
        audit_event_id=str(row.audit_event_id),
        occurred_at=row.occurred_at,
        actor_display=actor_display,
        action=row.action.replace("_", " ").title(),
        entity_type=row.entity_type.replace("_", " ").title(),
        reason=row.reason_text or row.reason_code,
        correlation_id=row.correlation_id,
    )


def _admin_audit_summary(row: Any) -> AdminAuditEventSummary:
    event = row.AuditEventRow
    actor_display = (
        event.actor_display_snapshot
        or event.actor_id
        or event.actor_type.replace("_", " ").title()
    )
    return AdminAuditEventSummary(
        audit_event_id=str(event.audit_event_id),
        occurred_at=event.occurred_at,
        session_id=None if event.session_id is None else str(event.session_id),
        session_title=row.session_title,
        public_slug=row.public_slug,
        actor_display=actor_display,
        action=event.action.replace("_", " ").title(),
        entity_type=event.entity_type.replace("_", " ").title(),
        entity_id=event.entity_id,
        reason=event.reason_text or event.reason_code,
        correlation_id=event.correlation_id,
    )


def _validate_paging(*, page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page must be at least 1.")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}.")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _participant_progress_expression():
    return case(
        (ParticipantRow.completed_at.is_not(None), "completed"),
        (ParticipantRow.submitted_at.is_not(None), "submitted"),
        (ParticipantRow.started_at.is_not(None), "started"),
        (ParticipantRow.joined_at.is_not(None), "joined"),
        else_="enrolled",
    )


def _latest_validation_id(submission_id: Any):
    return (
        select(SubmissionValidationRow.validation_id)
        .where(SubmissionValidationRow.submission_id == submission_id)
        .order_by(
            SubmissionValidationRow.completed_at.desc().nullslast(),
            SubmissionValidationRow.validation_id.desc(),
        )
        .limit(1)
        .correlate(SubmissionRow)
        .scalar_subquery()
    )


def _latest_review_id(submission_id: Any):
    return (
        select(SubmissionReviewDecisionRow.decision_id)
        .where(SubmissionReviewDecisionRow.submission_id == submission_id)
        .order_by(
            SubmissionReviewDecisionRow.decided_at.desc(),
            SubmissionReviewDecisionRow.decision_id.desc(),
        )
        .limit(1)
        .correlate(SubmissionRow)
        .scalar_subquery()
    )


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


def _public_participation_session(
    row: SessionRow,
    groups: Sequence[SessionStakeholderGroupRow],
) -> PublicParticipationSession:
    return PublicParticipationSession(
        session_id=str(row.session_id),
        public_slug=row.public_slug,
        title=row.title,
        description=row.description,
        enrollment_mode=EnrollmentMode(row.enrollment_mode),
        access_code_mode=AccessCodeMode(row.access_code_mode),
        stakeholder_selection_mode=StakeholderSelectionMode(
            row.stakeholder_selection_mode
        ),
        identity_policy=row.identity_policy,
        groups=tuple(
            ParticipationGroupOption(
                group_id=str(group.session_stakeholder_group_id),
                name=group.name,
                description=group.description,
            )
            for group in groups
        ),
    )


def _participation_question(
    row: ResponseQuestionDefinitionRow,
    *,
    criteria: Mapping[str, ScenarioCriterionRow],
    alternatives: Mapping[str, ScenarioAlternativeRow],
) -> ParticipationQuestion:
    criterion = criteria.get(str(row.criterion_id))
    alternative = alternatives.get(str(row.alternative_id))
    target = criterion or alternative
    left = criteria.get(str(row.left_criterion_id))
    right = criteria.get(str(row.right_criterion_id))
    return ParticipationQuestion(
        question_definition_id=str(row.question_definition_id),
        question_type=QuestionType(row.question_type),
        prompt=row.prompt_snapshot,
        required=row.required,
        display_order=row.display_order,
        target_name=target.name if target is not None else None,
        target_description=target.description if target is not None else None,
        left_name=left.name if left is not None else None,
        right_name=right.name if right is not None else None,
    )


def _scenario_summary_statement() -> Select:
    alternative_count = (
        select(func.count())
        .select_from(ScenarioAlternativeRow)
        .where(
            ScenarioAlternativeRow.scenario_snapshot_id
            == ScenarioSnapshotRow.scenario_snapshot_id
        )
        .correlate(ScenarioSnapshotRow)
        .scalar_subquery()
    )
    criterion_count = (
        select(func.count())
        .select_from(ScenarioCriterionRow)
        .where(
            ScenarioCriterionRow.scenario_snapshot_id
            == ScenarioSnapshotRow.scenario_snapshot_id
        )
        .correlate(ScenarioSnapshotRow)
        .scalar_subquery()
    )
    scale_count = (
        select(func.count())
        .select_from(ScenarioScaleRow)
        .where(
            ScenarioScaleRow.scenario_snapshot_id
            == ScenarioSnapshotRow.scenario_snapshot_id
        )
        .correlate(ScenarioSnapshotRow)
        .scalar_subquery()
    )
    file_count = (
        select(func.count())
        .select_from(ScenarioSnapshotFileRow)
        .where(
            ScenarioSnapshotFileRow.scenario_snapshot_id
            == ScenarioSnapshotRow.scenario_snapshot_id
        )
        .correlate(ScenarioSnapshotRow)
        .scalar_subquery()
    )
    return select(
        ScenarioSnapshotRow.scenario_snapshot_id,
        ScenarioSnapshotRow.scenario_definition_id,
        ScenarioDefinitionRow.scenario_key,
        ScenarioSnapshotRow.title,
        ScenarioSnapshotRow.domain,
        ScenarioSnapshotRow.summary,
        ScenarioSnapshotRow.declared_version,
        ScenarioSnapshotRow.scenario_type,
        ScenarioSnapshotRow.status.label("snapshot_status"),
        ScenarioDefinitionRow.status.label("definition_status"),
        alternative_count.label("alternative_count"),
        criterion_count.label("criterion_count"),
        scale_count.label("scale_count"),
        file_count.label("file_count"),
        ScenarioSnapshotRow.created_at,
        ScenarioSnapshotRow.ready_at,
        ScenarioSnapshotRow.root_hash,
    ).join(
        ScenarioDefinitionRow,
        ScenarioDefinitionRow.scenario_definition_id
        == ScenarioSnapshotRow.scenario_definition_id,
    )


def _scenario_summary(row: Any) -> ScenarioSnapshotSummary:
    return ScenarioSnapshotSummary(
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        scenario_definition_id=str(row.scenario_definition_id),
        scenario_key=row.scenario_key,
        title=row.title,
        domain=row.domain,
        summary=row.summary,
        declared_version=row.declared_version,
        scenario_type=ScenarioType(row.scenario_type),
        snapshot_status=ScenarioSnapshotStatus(row.snapshot_status),
        definition_status=ScenarioDefinitionStatus(row.definition_status),
        alternative_count=int(row.alternative_count),
        criterion_count=int(row.criterion_count),
        scale_count=int(row.scale_count),
        file_count=int(row.file_count),
        created_at=row.created_at,
        ready_at=row.ready_at,
        root_hash=row.root_hash,
    )
