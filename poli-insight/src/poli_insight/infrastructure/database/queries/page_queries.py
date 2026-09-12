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
    AnalysisCaseView,
    AnalysisLevelSummaryView,
    AnalysisScopeView,
    AuthoredAnswerDetail,
    ConfiguredAlgorithmSummary,
    CriterionWeightDetail,
    HomeActiveSessionSummary,
    PageQueries,
    PageQueryError,
    PageResult,
    ParticipantAccessSummary,
    ParticipantConsentSummary,
    ParticipantDraftProgress,
    ParticipantSubmissionAttempt,
    ParticipationGroupOption,
    ParticipationQuestion,
    ParticipationScaleOption,
    ParticipationWorkspace,
    ProcessingGroupSubmissionSummary,
    ProcessingMatrixView,
    ProcessingQueueMode,
    ProcessingSessionSummary,
    ProcessingSubmissionContext,
    PublicParticipationSession,
    PublicSessionSummary,
    RankingAlternativeView,
    RankingResultView,
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
    SessionDateField,
    SessionGroupProgress,
    SessionInvitationSummary,
    SessionParticipantDetail,
    SessionParticipantMetrics,
    SessionParticipantSummary,
    SessionScenarioOption,
    SessionSearchFilters,
    SessionSubmissionDetail,
    SessionSubmissionSummary,
    SessionValidationOverview,
    ValidationQueueItem,
)
from poli_insight.core.time import utc_now
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    AccessCodeMode,
    AlgorithmRole,
    AnalysisCaseStatus,
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
    RunStatus,
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
from poli_insight.infrastructure.database.json_codec import json_from_storage
from poli_insight.infrastructure.database.models.analysis import (
    AnalysisCaseRow,
    AnalysisRunRow,
)
from poli_insight.infrastructure.database.models.audit import AuditEventRow
from poli_insight.infrastructure.database.models.operations import (
    SubmissionReviewDecisionRow,
)
from poli_insight.infrastructure.database.models.participation import (
    ParticipantAccessGrantRow,
    ParticipantConsentRow,
    ParticipantRow,
    SessionInvitationRow,
)
from poli_insight.infrastructure.database.models.processing import (
    ProcessingMatrixRow,
    ProcessingRunRow,
    ProcessingRunSubmissionRow,
)
from poli_insight.infrastructure.database.models.ranking import (
    RankingResultRow,
    RankingRunRow,
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
    SessionAlgorithmConfigRow,
    SessionConfigurationVersionRow,
    SessionRow,
    SessionStakeholderGroupRow,
)
from poli_insight.infrastructure.database.models.submission import (
    SubmissionAnswerRow,
    SubmissionRow,
)
from poli_insight.infrastructure.database.models.validation import (
    ParticipantCriterionWeightRow,
    SubmissionValidationRow,
    ValidationMessageRow,
    ValidationNormalizedAnswerRow,
    ValidationPreparedMatrixRow,
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
        scenario_config_bytes = (
            select(ScenarioSnapshotFileRow.inline_bytes)
            .where(
                ScenarioSnapshotFileRow.scenario_snapshot_id
                == ScenarioSnapshotRow.scenario_snapshot_id,
                ScenarioSnapshotFileRow.file_role
                == ScenarioFileRole.SCENARIO_CONFIG.value,
            )
            .order_by(ScenarioSnapshotFileRow.logical_path)
            .limit(1)
            .correlate(ScenarioSnapshotRow)
            .scalar_subquery()
        )
        statement = (
            select(
                SessionRow,
                ScenarioSnapshotRow,
                scenario_config_bytes.label("scenario_config_bytes"),
            )
            .join(
                ScenarioSnapshotRow,
                ScenarioSnapshotRow.scenario_snapshot_id
                == SessionRow.scenario_snapshot_id,
            )
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
                rows = database_session.execute(statement).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Open sessions could not be loaded.") from error

        return PageResult(
            items=tuple(
                _public_session_summary(
                    session_row,
                    snapshot_row,
                    scenario_source,
                )
                for session_row, snapshot_row, scenario_source in rows
            ),
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
        filters: SessionSearchFilters | None = None,
        search: str | None = None,
        status: SessionStatus | None = None,
        scenario_key: str | None = None,
    ) -> SessionCatalogMetrics:
        query_filters = _session_filters(
            session_filters=filters,
            search=search,
            status=status,
            scenario_key=scenario_key,
            timezone=self._timezone,
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
            .where(*query_filters)
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
        filters: SessionSearchFilters | None = None,
        search: str | None = None,
        status: SessionStatus | None = None,
        scenario_key: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[AdminSessionSummary]:
        _validate_paging(page=page, page_size=page_size)
        query_filters = _session_filters(
            session_filters=filters,
            search=search,
            status=status,
            scenario_key=scenario_key,
            timezone=self._timezone,
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
            .where(*query_filters)
        )
        statement = (
            _admin_session_summary_statement()
            .where(*query_filters)
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
            .outerjoin(
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
        query_time = utc_now()
        latest_submission_id = (
            select(SubmissionRow.submission_id)
            .where(SubmissionRow.participant_id == ParticipantRow.participant_id)
            .order_by(
                SubmissionRow.attempt_number.desc(),
                SubmissionRow.submission_id.desc(),
            )
            .limit(1)
            .correlate(ParticipantRow)
            .scalar_subquery()
        )
        latest_grant_id = (
            select(ParticipantAccessGrantRow.access_grant_id)
            .where(
                ParticipantAccessGrantRow.participant_id
                == ParticipantRow.participant_id
            )
            .order_by(
                ParticipantAccessGrantRow.issued_at.desc(),
                ParticipantAccessGrantRow.access_grant_id.desc(),
            )
            .limit(1)
            .correlate(ParticipantRow)
            .scalar_subquery()
        )
        current_submission = aliased(SubmissionRow)
        current_grant = aliased(ParticipantAccessGrantRow)
        answer_count = (
            select(func.count(SubmissionAnswerRow.submission_answer_id))
            .where(SubmissionAnswerRow.submission_id == latest_submission_id)
            .correlate(ParticipantRow)
            .scalar_subquery()
        )
        required_count = (
            select(func.count(ResponseQuestionDefinitionRow.question_definition_id))
            .where(
                ResponseQuestionDefinitionRow.configuration_version_id
                == ParticipantRow.configuration_version_id,
                ResponseQuestionDefinitionRow.required.is_(True),
            )
            .correlate(ParticipantRow)
            .scalar_subquery()
        )
        grant_status = case(
            (current_grant.access_grant_id.is_(None), "missing"),
            (current_grant.replaced_by_grant_id.is_not(None), "replaced"),
            (current_grant.revoked_at.is_not(None), "revoked"),
            (current_grant.expires_at <= query_time, "expired"),
            else_="active",
        )
        base = (
            select(
                ParticipantRow,
                SessionStakeholderGroupRow.name.label("group_name"),
                func.coalesce(answer_count, 0).label("answer_count"),
                required_count.label("required_count"),
                current_submission.attempt_number.label("current_attempt"),
                current_submission.last_saved_at.label("last_saved_at"),
                current_grant.last_used_at.label("grant_last_used_at"),
                current_grant.expires_at.label("grant_expires_at"),
                grant_status.label("grant_status"),
            )
            .join(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == ParticipantRow.session_stakeholder_group_id,
            )
            .outerjoin(
                current_submission,
                current_submission.submission_id == latest_submission_id,
            )
            .outerjoin(
                current_grant,
                current_grant.access_grant_id == latest_grant_id,
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
                _participant_summary(
                    row.ParticipantRow,
                    row.group_name,
                    answered_count=int(row.answer_count or 0),
                    required_answer_count=int(row.required_count or 0),
                    current_attempt=row.current_attempt,
                    last_activity_at=max(
                        value
                        for value in (
                            row.ParticipantRow.updated_at,
                            row.last_saved_at,
                            row.grant_last_used_at,
                        )
                        if value is not None
                    ),
                    resume_access_status=row.grant_status,
                    resume_expires_at=row.grant_expires_at,
                )
                for row in rows
            ),
            page=page,
            page_size=page_size,
            total=int(total),
        )

    def get_session_participant_metrics(
        self,
        session_id: str,
        *,
        at: datetime | None = None,
    ) -> SessionParticipantMetrics:
        query_time = at or utc_now()
        stale_before = query_time - timedelta(days=7)
        expiring_before = query_time + timedelta(days=7)
        participant_filters = (ParticipantRow.session_id == session_id,)
        statement = select(
            select(func.count(ParticipantRow.participant_id))
            .where(*participant_filters)
            .scalar_subquery()
            .label("total_enrolled"),
            select(func.count(ParticipantRow.participant_id))
            .where(*participant_filters, ParticipantRow.started_at.is_(None))
            .scalar_subquery()
            .label("never_started"),
            select(func.count(SubmissionRow.submission_id))
            .where(
                SubmissionRow.session_id == session_id,
                SubmissionRow.status == SubmissionStatus.DRAFT.value,
            )
            .scalar_subquery()
            .label("active_drafts"),
            select(func.count(ParticipantRow.participant_id))
            .where(*participant_filters, ParticipantRow.submitted_at.is_not(None))
            .scalar_subquery()
            .label("submitted_or_completed"),
            select(func.count(SubmissionRow.submission_id))
            .where(
                SubmissionRow.session_id == session_id,
                SubmissionRow.status == SubmissionStatus.DRAFT.value,
                SubmissionRow.last_saved_at < stale_before,
            )
            .scalar_subquery()
            .label("stale_drafts"),
            select(func.count(ParticipantAccessGrantRow.access_grant_id))
            .join(
                ParticipantRow,
                ParticipantRow.participant_id
                == ParticipantAccessGrantRow.participant_id,
            )
            .where(
                ParticipantRow.session_id == session_id,
                ParticipantAccessGrantRow.revoked_at.is_(None),
                ParticipantAccessGrantRow.expires_at > query_time,
                ParticipantAccessGrantRow.expires_at <= expiring_before,
            )
            .scalar_subquery()
            .label("resume_links_expiring_soon"),
        )
        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).one()
        except SQLAlchemyError as error:
            raise PageQueryError("Participant metrics could not be loaded.") from error
        return SessionParticipantMetrics(
            total_enrolled=int(row.total_enrolled or 0),
            never_started=int(row.never_started or 0),
            active_drafts=int(row.active_drafts or 0),
            submitted_or_completed=int(row.submitted_or_completed or 0),
            stale_drafts=int(row.stale_drafts or 0),
            resume_links_expiring_soon=int(row.resume_links_expiring_soon or 0),
        )

    def get_session_participant_detail(
        self,
        session_id: str,
        participant_id: str,
    ) -> SessionParticipantDetail | None:
        submission_count = (
            select(func.count(SubmissionRow.submission_id))
            .where(SubmissionRow.participant_id == ParticipantRow.participant_id)
            .correlate(ParticipantRow)
            .scalar_subquery()
        )
        detail_required_count = (
            select(func.count(ResponseQuestionDefinitionRow.question_definition_id))
            .where(
                ResponseQuestionDefinitionRow.configuration_version_id
                == ParticipantRow.configuration_version_id,
                ResponseQuestionDefinitionRow.required.is_(True),
            )
            .correlate(ParticipantRow)
            .scalar_subquery()
        )
        statement = (
            select(
                ParticipantRow,
                SessionStakeholderGroupRow.name.label("group_name"),
                SessionConfigurationVersionRow.version_number,
                SessionConfigurationVersionRow.configuration_json,
                submission_count.label("submission_count"),
                detail_required_count.label("required_answer_count"),
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
            .where(
                ParticipantRow.session_id == session_id,
                ParticipantRow.participant_id == participant_id,
            )
        )
        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).one_or_none()
                if row is None:
                    return None
                attempt_validation = aliased(SubmissionValidationRow)
                attempt_review = aliased(SubmissionReviewDecisionRow)
                attempt_answer_count = (
                    select(func.count(SubmissionAnswerRow.submission_answer_id))
                    .where(
                        SubmissionAnswerRow.submission_id == SubmissionRow.submission_id
                    )
                    .correlate(SubmissionRow)
                    .scalar_subquery()
                )
                attempt_rows = database_session.execute(
                    select(
                        SubmissionRow,
                        attempt_validation.status.label("validation_status"),
                        attempt_review.status.label("review_status"),
                        attempt_answer_count.label("answer_count"),
                    )
                    .select_from(SubmissionRow)
                    .outerjoin(
                        attempt_validation,
                        attempt_validation.validation_id
                        == _latest_validation_id(SubmissionRow.submission_id),
                    )
                    .outerjoin(
                        attempt_review,
                        attempt_review.decision_id
                        == _latest_review_id(
                            SubmissionRow.submission_id,
                            attempt_validation.validation_id,
                            attempt_validation,
                        ),
                    )
                    .where(SubmissionRow.participant_id == participant_id)
                    .order_by(SubmissionRow.attempt_number.desc())
                ).all()
                grant_row = database_session.scalars(
                    select(ParticipantAccessGrantRow)
                    .where(ParticipantAccessGrantRow.participant_id == participant_id)
                    .order_by(
                        ParticipantAccessGrantRow.issued_at.desc(),
                        ParticipantAccessGrantRow.access_grant_id.desc(),
                    )
                    .limit(1)
                ).first()
                consent_config = row.configuration_json.get("consent", {})
                consent_required = (
                    isinstance(consent_config, Mapping)
                    and consent_config.get("required") is True
                )
                consent_version = (
                    str(consent_config.get("version", "1"))
                    if isinstance(consent_config, Mapping)
                    else "1"
                )
                consent_row = database_session.scalars(
                    select(ParticipantConsentRow)
                    .where(
                        ParticipantConsentRow.participant_id == participant_id,
                        ParticipantConsentRow.configuration_version_id
                        == row.ParticipantRow.configuration_version_id,
                        ParticipantConsentRow.consent_version == consent_version,
                    )
                    .order_by(ParticipantConsentRow.accepted_at.desc())
                    .limit(1)
                ).first()
        except SQLAlchemyError as error:
            raise PageQueryError("Participant details could not be loaded.") from error
        participant = row.ParticipantRow
        required_answer_count = int(row.required_answer_count or 0)
        draft_row = next(
            (
                item
                for item in attempt_rows
                if item.SubmissionRow.status == SubmissionStatus.DRAFT.value
            ),
            None,
        )
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
            draft=(
                None
                if draft_row is None
                else ParticipantDraftProgress(
                    submission_id=str(draft_row.SubmissionRow.submission_id),
                    attempt_number=draft_row.SubmissionRow.attempt_number,
                    answered_count=int(draft_row.answer_count or 0),
                    required_answer_count=required_answer_count,
                    last_saved_at=draft_row.SubmissionRow.last_saved_at,
                )
            ),
            attempts=tuple(
                ParticipantSubmissionAttempt(
                    submission_id=str(item.SubmissionRow.submission_id),
                    attempt_number=item.SubmissionRow.attempt_number,
                    status=SubmissionStatus(item.SubmissionRow.status),
                    submitted_at=item.SubmissionRow.submitted_at,
                    validation_status=(
                        None
                        if item.validation_status is None
                        else ValidationStatus(item.validation_status)
                    ),
                    review_status=(
                        SubmissionReviewStatus.PENDING
                        if item.review_status is None
                        else SubmissionReviewStatus(item.review_status)
                    ),
                    previous_submission_id=(
                        None
                        if item.SubmissionRow.previous_submission_id is None
                        else str(item.SubmissionRow.previous_submission_id)
                    ),
                )
                for item in attempt_rows
            ),
            access=(
                None
                if grant_row is None
                else ParticipantAccessSummary(
                    access_grant_id=str(grant_row.access_grant_id),
                    issued_at=grant_row.issued_at,
                    expires_at=grant_row.expires_at,
                    last_used_at=grant_row.last_used_at,
                    status=_grant_status(grant_row, at=utc_now()),
                    revoked_at=grant_row.revoked_at,
                    has_replacement=grant_row.replaced_by_grant_id is not None,
                )
            ),
            consent=ParticipantConsentSummary(
                required=consent_required,
                completed=(not consent_required or consent_row is not None),
                consent_version=consent_version,
                accepted_at=(None if consent_row is None else consent_row.accepted_at),
            ),
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
                review.decision_id
                == _latest_review_id(
                    SubmissionRow.submission_id,
                    validation.validation_id,
                    validation,
                ),
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
                validation.completion_ratio.label("detail_completion_ratio"),
                validation.validator_version.label("detail_validator_version"),
                validation.completed_at.label("detail_validation_completed_at"),
                SessionConfigurationVersionRow.consistency_threshold.label(
                    "detail_consistency_threshold"
                ),
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
            .join(
                SessionConfigurationVersionRow,
                SessionConfigurationVersionRow.configuration_version_id
                == SubmissionRow.configuration_version_id,
            )
            .outerjoin(
                validation,
                validation.validation_id
                == _latest_validation_id(SubmissionRow.submission_id),
            )
            .outerjoin(
                review,
                review.decision_id
                == _latest_review_id(
                    SubmissionRow.submission_id,
                    validation.validation_id,
                    validation,
                ),
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
                criterion = aliased(ScenarioCriterionRow)
                left_criterion = aliased(ScenarioCriterionRow)
                right_criterion = aliased(ScenarioCriterionRow)
                alternative = aliased(ScenarioAlternativeRow)
                scale_value = aliased(ScenarioScaleValueRow)
                normalized = aliased(ValidationNormalizedAnswerRow)
                answer_rows = database_session.execute(
                    select(
                        SubmissionAnswerRow,
                        ResponseQuestionDefinitionRow,
                        criterion.name.label("criterion_label"),
                        left_criterion.name.label("left_criterion_label"),
                        right_criterion.name.label("right_criterion_label"),
                        alternative.name.label("alternative_label"),
                        scale_value.label.label("scale_label"),
                        scale_value.numeric_value.label("scale_numeric_value"),
                        normalized.normalized_value_json.label("normalized_value"),
                        normalized.crisp_value.label("normalized_crisp_value"),
                        normalized.normalizer_version.label("normalizer_version"),
                    )
                    .select_from(SubmissionAnswerRow)
                    .join(
                        ResponseQuestionDefinitionRow,
                        ResponseQuestionDefinitionRow.question_definition_id
                        == SubmissionAnswerRow.question_definition_id,
                    )
                    .outerjoin(
                        criterion,
                        criterion.criterion_id
                        == ResponseQuestionDefinitionRow.criterion_id,
                    )
                    .outerjoin(
                        left_criterion,
                        left_criterion.criterion_id
                        == ResponseQuestionDefinitionRow.left_criterion_id,
                    )
                    .outerjoin(
                        right_criterion,
                        right_criterion.criterion_id
                        == ResponseQuestionDefinitionRow.right_criterion_id,
                    )
                    .outerjoin(
                        alternative,
                        alternative.alternative_id
                        == ResponseQuestionDefinitionRow.alternative_id,
                    )
                    .outerjoin(
                        scale_value,
                        scale_value.scale_value_id
                        == SubmissionAnswerRow.selected_scale_value_id,
                    )
                    .outerjoin(
                        normalized,
                        (
                            normalized.submission_answer_id
                            == SubmissionAnswerRow.submission_answer_id
                        )
                        & (normalized.validation_id == row.detail_validation_id),
                    )
                    .where(SubmissionAnswerRow.submission_id == submission_id)
                    .order_by(
                        ResponseQuestionDefinitionRow.display_order,
                        SubmissionAnswerRow.submission_answer_id,
                    )
                ).all()
                weight_rows: tuple[Any, ...] = ()
                if row.detail_validation_id is not None:
                    weight_rows = tuple(
                        database_session.execute(
                            select(
                                ParticipantCriterionWeightRow,
                                ScenarioCriterionRow.name.label("criterion_label"),
                                ScenarioCriterionRow.display_order.label(
                                    "criterion_display_order"
                                ),
                            )
                            .select_from(ParticipantCriterionWeightRow)
                            .join(
                                ScenarioCriterionRow,
                                ScenarioCriterionRow.criterion_id
                                == ParticipantCriterionWeightRow.criterion_id,
                            )
                            .where(
                                ParticipantCriterionWeightRow.validation_id
                                == row.detail_validation_id
                            )
                            .order_by(
                                ScenarioCriterionRow.display_order,
                                ScenarioCriterionRow.criterion_id,
                            )
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
            started_at=row.SubmissionRow.started_at,
            submitted_at=row.SubmissionRow.submitted_at,
            superseded_at=row.SubmissionRow.superseded_at,
            withdrawn_at=row.SubmissionRow.withdrawn_at,
            previous_submission_id=(
                None
                if row.SubmissionRow.previous_submission_id is None
                else str(row.SubmissionRow.previous_submission_id)
            ),
            answer_schema_version=row.SubmissionRow.answer_schema_version,
            completion_ratio=(
                None
                if row.detail_completion_ratio is None
                else str(row.detail_completion_ratio)
            ),
            consistency_threshold=(
                None
                if row.detail_consistency_threshold is None
                else str(row.detail_consistency_threshold)
            ),
            validator_version=row.detail_validator_version,
            authored_answers=tuple(
                _authored_answer_detail(item) for item in answer_rows
            ),
            criterion_weights=tuple(
                CriterionWeightDetail(
                    criterion_id=str(item.ParticipantCriterionWeightRow.criterion_id),
                    criterion_label=item.criterion_label,
                    display_order=item.criterion_display_order,
                    crisp_weight=_decimal_text(
                        item.ParticipantCriterionWeightRow.crisp_weight
                    ),
                    fuzzy_lower=_decimal_text(
                        item.ParticipantCriterionWeightRow.fuzzy_lower
                    ),
                    fuzzy_middle=_decimal_text(
                        item.ParticipantCriterionWeightRow.fuzzy_middle
                    ),
                    fuzzy_upper=_decimal_text(
                        item.ParticipantCriterionWeightRow.fuzzy_upper
                    ),
                    derivation_metadata=(
                        item.ParticipantCriterionWeightRow.derivation_metadata_json
                    ),
                )
                for item in weight_rows
            ),
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
                validation.validation_id.label("validation_id"),
                validation.status.label("validation_status"),
                validation.completion_ratio.label("completion_ratio"),
                validation.consistency_ratio.label("consistency_ratio"),
                validation.failure_code.label("failure_code"),
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
                review.decision_id
                == _latest_review_id(
                    SubmissionRow.submission_id,
                    validation.validation_id,
                    validation,
                ),
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
                    validation_id=(
                        None if row.validation_id is None else str(row.validation_id)
                    ),
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
                    completion_ratio=(
                        None
                        if row.completion_ratio is None
                        else str(row.completion_ratio)
                    ),
                    consistency_ratio=(
                        None
                        if row.consistency_ratio is None
                        else str(row.consistency_ratio)
                    ),
                    failure_code=row.failure_code,
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

    def get_session_validation_overview(
        self,
        session_id: str,
    ) -> SessionValidationOverview | None:
        validation = aliased(SubmissionValidationRow)
        review = aliased(SubmissionReviewDecisionRow)
        current_statement = (
            select(
                SubmissionRow.submission_id,
                SubmissionRow.participant_id,
                SubmissionRow.session_stakeholder_group_id,
                SubmissionRow.answers_hash,
                ParticipantRow.access_status.label("participant_access_status"),
                validation.status.label("validation_status"),
                review.status.label("review_status"),
            )
            .select_from(SubmissionRow)
            .outerjoin(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .outerjoin(
                validation,
                validation.validation_id
                == _latest_validation_id(SubmissionRow.submission_id),
            )
            .outerjoin(
                review,
                review.decision_id
                == _latest_review_id(
                    SubmissionRow.submission_id,
                    validation.validation_id,
                    validation,
                ),
            )
            .where(
                SubmissionRow.session_id == session_id,
                SubmissionRow.configuration_version_id
                == select(SessionRow.active_configuration_version_id)
                .where(SessionRow.session_id == session_id)
                .scalar_subquery(),
                SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
            )
            .order_by(
                SubmissionRow.participant_id,
                SubmissionRow.submission_id,
            )
        )
        latest_batch_statement = (
            select(ProcessingRunRow)
            .where(ProcessingRunRow.session_id == session_id)
            .order_by(
                ProcessingRunRow.run_number.desc(),
                ProcessingRunRow.processing_run_id.desc(),
            )
            .limit(1)
        )
        try:
            with self._session_factory() as database_session:
                session_row = database_session.get(SessionRow, session_id)
                if session_row is None:
                    return None
                current_rows = database_session.execute(current_statement).all()
                latest_batch = database_session.scalars(latest_batch_statement).first()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Session validation overview could not be loaded."
            ) from error

        status_counts = {
            status: sum(row.validation_status == status.value for row in current_rows)
            for status in ValidationStatus
        }
        warning_decisions_required = sum(
            row.validation_status == ValidationStatus.VALID_WITH_WARNING.value
            and row.review_status
            not in {
                SubmissionReviewStatus.ACCEPTED.value,
                SubmissionReviewStatus.REJECTED.value,
            }
            for row in current_rows
        )
        current_roster_hash = (
            None
            if session_row.active_configuration_version_id is None
            else hash_json(
                [
                    {
                        "submission_id": str(row.submission_id),
                        "participant_id": str(row.participant_id),
                        "stakeholder_group_id": str(row.session_stakeholder_group_id),
                        "answers_hash": row.answers_hash,
                        "participant_access_status": (
                            row.participant_access_status or "missing"
                        ),
                    }
                    for row in current_rows
                ]
            )
        )
        return SessionValidationOverview(
            session_id=session_id,
            session_status=SessionStatus(session_row.status),
            has_active_configuration=(
                session_row.active_configuration_version_id is not None
            ),
            effective_submitted_count=len(current_rows),
            unvalidated_count=sum(
                row.validation_status is None for row in current_rows
            ),
            active_count=(
                status_counts[ValidationStatus.PENDING]
                + status_counts[ValidationStatus.RUNNING]
            ),
            valid_count=status_counts[ValidationStatus.VALID],
            warned_count=status_counts[ValidationStatus.VALID_WITH_WARNING],
            invalid_count=status_counts[ValidationStatus.INVALID],
            error_count=status_counts[ValidationStatus.ERROR],
            warning_decisions_required=warning_decisions_required,
            latest_batch_id=(
                None if latest_batch is None else str(latest_batch.processing_run_id)
            ),
            latest_batch_number=(
                None if latest_batch is None else latest_batch.run_number
            ),
            latest_batch_status=(
                None if latest_batch is None else RunStatus(latest_batch.status)
            ),
            latest_batch_created_at=(
                None if latest_batch is None else latest_batch.created_at
            ),
            latest_batch_roster_hash=(
                None if latest_batch is None else latest_batch.roster_hash
            ),
            current_roster_hash=current_roster_hash,
            roster_is_current=(
                latest_batch is not None
                and current_roster_hash == latest_batch.roster_hash
            ),
        )

    def get_processing_submission_context(
        self,
        session_id: str,
    ) -> ProcessingSubmissionContext | None:
        if not session_id.strip():
            raise ValueError("session_id cannot be empty.")
        session_statement = select(
            SessionRow.active_configuration_version_id,
        ).where(SessionRow.session_id == session_id)
        try:
            with self._session_factory() as database_session:
                configuration_id = database_session.scalar(session_statement)
                session_exists = database_session.scalar(
                    select(func.count())
                    .select_from(SessionRow)
                    .where(SessionRow.session_id == session_id)
                )
                if not session_exists:
                    return None
                if configuration_id is None:
                    return ProcessingSubmissionContext(session_id, ())
                configuration = database_session.get(
                    SessionConfigurationVersionRow,
                    configuration_id,
                )
                if configuration is None:
                    return ProcessingSubmissionContext(session_id, ())
                groups = tuple(
                    database_session.scalars(
                        select(SessionStakeholderGroupRow)
                        .where(
                            SessionStakeholderGroupRow.configuration_version_id
                            == configuration_id,
                            SessionStakeholderGroupRow.is_active.is_(True),
                        )
                        .order_by(SessionStakeholderGroupRow.display_order)
                    ).all()
                )
                participant_rows = database_session.execute(
                    select(
                        ParticipantRow.session_stakeholder_group_id,
                        func.count().label("count_value"),
                    )
                    .where(
                        ParticipantRow.session_id == session_id,
                        ParticipantRow.configuration_version_id == configuration_id,
                    )
                    .group_by(ParticipantRow.session_stakeholder_group_id)
                ).all()
                attempt_rows = database_session.execute(
                    select(
                        SubmissionRow.session_stakeholder_group_id,
                        SubmissionRow.status,
                        func.count().label("count_value"),
                        func.sum(
                            case(
                                (SubmissionRow.attempt_number > 1, 1),
                                else_=0,
                            )
                        ).label("resubmission_count"),
                    )
                    .where(
                        SubmissionRow.session_id == session_id,
                        SubmissionRow.configuration_version_id == configuration_id,
                    )
                    .group_by(
                        SubmissionRow.session_stakeholder_group_id,
                        SubmissionRow.status,
                    )
                ).all()
                validation = aliased(SubmissionValidationRow)
                validation_rows = database_session.execute(
                    select(
                        SubmissionRow.session_stakeholder_group_id,
                        validation.status,
                        func.count().label("count_value"),
                    )
                    .outerjoin(
                        validation,
                        validation.validation_id
                        == _latest_validation_id(SubmissionRow.submission_id),
                    )
                    .where(
                        SubmissionRow.session_id == session_id,
                        SubmissionRow.configuration_version_id == configuration_id,
                        SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
                    )
                    .group_by(
                        SubmissionRow.session_stakeholder_group_id,
                        validation.status,
                    )
                ).all()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Processing submission context could not be loaded."
            ) from error

        enrolled_by_group = {
            str(row.session_stakeholder_group_id): int(row.count_value)
            for row in participant_rows
        }
        attempts_by_group: dict[str, dict[str, int]] = {}
        resubmissions_by_group: dict[str, int] = {}
        for row in attempt_rows:
            group_id = str(row.session_stakeholder_group_id)
            attempts_by_group.setdefault(group_id, {})[row.status] = int(
                row.count_value
            )
            resubmissions_by_group[group_id] = resubmissions_by_group.get(
                group_id, 0
            ) + int(row.resubmission_count or 0)
        validations_by_group: dict[str, dict[str | None, int]] = {}
        for row in validation_rows:
            validations_by_group.setdefault(
                str(row.session_stakeholder_group_id),
                {},
            )[row.status] = int(row.count_value)

        summaries: list[ProcessingGroupSubmissionSummary] = []
        for group in groups:
            group_id = str(group.session_stakeholder_group_id)
            attempt_counts = attempts_by_group.get(group_id, {})
            validation_counts = validations_by_group.get(group_id, {})
            unvalidated = sum(
                validation_counts.get(status, 0)
                for status in (
                    None,
                    ValidationStatus.PENDING.value,
                    ValidationStatus.RUNNING.value,
                )
            )
            voting_power = Decimal(group.allocation_units) / Decimal(
                configuration.allocation_total_units
            )
            summaries.append(
                ProcessingGroupSubmissionSummary(
                    stakeholder_group_id=group_id,
                    stakeholder_group_name=group.name,
                    configured_voting_power=format(
                        voting_power.normalize(),
                        "f",
                    ),
                    enrolled_count=enrolled_by_group.get(group_id, 0),
                    submitted_count=attempt_counts.get(
                        SubmissionStatus.SUBMITTED.value,
                        0,
                    ),
                    valid_count=validation_counts.get(
                        ValidationStatus.VALID.value,
                        0,
                    ),
                    warned_count=validation_counts.get(
                        ValidationStatus.VALID_WITH_WARNING.value,
                        0,
                    ),
                    invalid_count=validation_counts.get(
                        ValidationStatus.INVALID.value,
                        0,
                    ),
                    error_count=validation_counts.get(
                        ValidationStatus.ERROR.value,
                        0,
                    ),
                    unvalidated_count=unvalidated,
                    draft_attempt_count=attempt_counts.get(
                        SubmissionStatus.DRAFT.value,
                        0,
                    ),
                    superseded_attempt_count=attempt_counts.get(
                        SubmissionStatus.SUPERSEDED.value,
                        0,
                    ),
                    withdrawn_attempt_count=attempt_counts.get(
                        SubmissionStatus.WITHDRAWN.value,
                        0,
                    ),
                    resubmission_attempt_count=resubmissions_by_group.get(
                        group_id,
                        0,
                    ),
                )
            )
        return ProcessingSubmissionContext(session_id, tuple(summaries))

    def list_processing_sessions(
        self,
        *,
        filters: SessionSearchFilters,
        mode: ProcessingQueueMode,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PageResult[ProcessingSessionSummary]:
        _validate_paging(page=page, page_size=page_size)
        if mode == ProcessingQueueMode.PROCESSED:
            # No persisted end-to-end package contract exists yet. A successful
            # weighting artifact is deliberately not treated as workflow completion.
            return PageResult((), page, page_size, 0)
        query_filters = _session_filters(
            session_filters=filters,
            search=None,
            status=None,
            scenario_key=None,
            timezone=self._timezone,
        )
        latest_run_id = (
            select(ProcessingRunRow.processing_run_id)
            .where(ProcessingRunRow.session_id == SessionRow.session_id)
            .order_by(ProcessingRunRow.run_number.desc())
            .limit(1)
            .correlate(SessionRow)
            .scalar_subquery()
        )
        latest_run = aliased(ProcessingRunRow)
        latest_ranking_id = (
            select(RankingRunRow.ranking_run_id)
            .where(RankingRunRow.session_id == SessionRow.session_id)
            .order_by(RankingRunRow.run_number.desc())
            .limit(1)
            .correlate(SessionRow)
            .scalar_subquery()
        )
        latest_ranking = aliased(RankingRunRow)
        successful_count = (
            select(func.count())
            .select_from(ProcessingRunRow)
            .where(
                ProcessingRunRow.session_id == SessionRow.session_id,
                ProcessingRunRow.status == RunStatus.SUCCEEDED.value,
            )
            .correlate(SessionRow)
            .scalar_subquery()
        )
        latest_successful_run_id = (
            select(ProcessingRunRow.processing_run_id)
            .where(
                ProcessingRunRow.session_id == SessionRow.session_id,
                ProcessingRunRow.status == RunStatus.SUCCEEDED.value,
            )
            .order_by(ProcessingRunRow.run_number.desc())
            .limit(1)
            .correlate(SessionRow)
            .scalar_subquery()
        )
        successful_ranking_count = (
            select(func.count())
            .select_from(RankingRunRow)
            .where(
                RankingRunRow.session_id == SessionRow.session_id,
                RankingRunRow.status == RunStatus.SUCCEEDED.value,
            )
            .correlate(SessionRow)
            .scalar_subquery()
        )
        submission_count = (
            select(func.count())
            .select_from(SubmissionRow)
            .where(
                SubmissionRow.session_id == SessionRow.session_id,
                SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
            )
            .correlate(SessionRow)
            .scalar_subquery()
        )
        if mode == ProcessingQueueMode.UNPROCESSED:
            query_filters.extend(
                (
                    SessionRow.status == SessionStatus.CLOSED.value,
                    latest_run_id.is_(None),
                )
            )
        else:
            query_filters.extend(
                (
                    SessionRow.status.in_(
                        (
                            SessionStatus.CLOSED.value,
                            SessionStatus.ARCHIVED.value,
                        )
                    ),
                    latest_run_id.is_not(None),
                )
            )
        if filters.processing_states:
            state_expressions = {
                "not_started": latest_run.processing_run_id.is_(None),
                "active": latest_run.status.in_(
                    (RunStatus.QUEUED.value, RunStatus.RUNNING.value)
                ),
                "awaiting_review": (
                    latest_run.status == RunStatus.AWAITING_REVIEW.value
                ),
                "failed": latest_run.status == RunStatus.FAILED.value,
                "stale": latest_run.status == RunStatus.STALE.value,
                "completed": successful_count > 0,
                "successful_weighting": successful_count > 0,
                "newer_work": (
                    (successful_count > 0)
                    & (latest_run.status != RunStatus.SUCCEEDED.value)
                ),
                "successful_ranking": successful_ranking_count > 0,
            }
            selected_expressions = tuple(
                state_expressions[value]
                for value in filters.processing_states
                if value in state_expressions
            )
            if selected_expressions:
                query_filters.append(or_(*selected_expressions))
        base = (
            select(
                SessionRow,
                ScenarioDefinitionRow.title.label("scenario_title"),
                ScenarioSnapshotRow.declared_version.label("scenario_version"),
                ScenarioSnapshotRow.status.label("scenario_status"),
                submission_count.label("effective_submission_count"),
                successful_count.label("successful_run_count"),
                latest_run.processing_run_id.label("latest_run_id"),
                latest_run.run_number.label("latest_run_number"),
                latest_run.status.label("latest_run_status"),
                latest_run.created_at.label("latest_run_created_at"),
                successful_ranking_count.label("successful_ranking_run_count"),
                latest_ranking.ranking_run_id.label("latest_ranking_run_id"),
                latest_ranking.run_number.label("latest_ranking_run_number"),
                latest_ranking.status.label("latest_ranking_run_status"),
                latest_ranking.completed_at.label("latest_ranking_activity_at"),
                latest_ranking.roster_hash.label("latest_ranking_roster_hash"),
                latest_ranking.source_processing_run_id.label(
                    "latest_ranking_source_processing_run_id"
                ),
                latest_successful_run_id.label("latest_successful_run_id"),
                func.coalesce(
                    latest_run.completed_at,
                    latest_run.created_at,
                    SessionRow.updated_at,
                ).label("last_processing_activity_at"),
            )
            .select_from(SessionRow)
            .join(ScenarioSnapshotRow)
            .join(ScenarioDefinitionRow)
            .outerjoin(
                latest_run,
                latest_run.processing_run_id == latest_run_id,
            )
            .outerjoin(
                latest_ranking,
                latest_ranking.ranking_run_id == latest_ranking_id,
            )
            .where(*query_filters)
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
                        SessionRow.closed_at.desc().nullslast(),
                        SessionRow.title,
                    )
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).all()
        except SQLAlchemyError as error:
            raise PageQueryError("Processing sessions could not be loaded.") from error

        items: list[ProcessingSessionSummary] = []
        for row in rows:
            overview = self.get_session_validation_overview(
                str(row.SessionRow.session_id)
            )
            blockers = _processing_blockers(row.SessionRow, row, overview)
            items.append(
                ProcessingSessionSummary(
                    session_id=str(row.SessionRow.session_id),
                    title=row.SessionRow.title,
                    public_slug=row.SessionRow.public_slug,
                    status=SessionStatus(row.SessionRow.status),
                    scenario_title=row.scenario_title,
                    scenario_version=row.scenario_version,
                    scenario_status=ScenarioSnapshotStatus(row.scenario_status),
                    has_active_configuration=(
                        row.SessionRow.active_configuration_version_id is not None
                    ),
                    effective_submission_count=int(row.effective_submission_count),
                    current_roster_hash=(
                        None if overview is None else overview.current_roster_hash
                    ),
                    latest_run_id=(
                        None if row.latest_run_id is None else str(row.latest_run_id)
                    ),
                    latest_run_number=row.latest_run_number,
                    latest_run_status=(
                        None
                        if row.latest_run_status is None
                        else RunStatus(row.latest_run_status)
                    ),
                    latest_run_created_at=row.latest_run_created_at,
                    last_processing_activity_at=max(
                        value
                        for value in (
                            row.last_processing_activity_at,
                            row.latest_ranking_activity_at,
                        )
                        if value is not None
                    ),
                    latest_run_roster_hash=(
                        None if overview is None else overview.latest_batch_roster_hash
                    ),
                    roster_is_current=(
                        False if overview is None else overview.roster_is_current
                    ),
                    successful_run_count=int(row.successful_run_count),
                    next_stage=_processing_next_stage(row, overview),
                    blockers=blockers,
                    opens_at=row.SessionRow.opens_at,
                    closes_at=row.SessionRow.closes_at,
                    created_at=row.SessionRow.created_at,
                    updated_at=row.SessionRow.updated_at,
                    latest_ranking_run_id=(
                        None
                        if row.latest_ranking_run_id is None
                        else str(row.latest_ranking_run_id)
                    ),
                    latest_ranking_run_number=row.latest_ranking_run_number,
                    latest_ranking_run_status=(
                        None
                        if row.latest_ranking_run_status is None
                        else RunStatus(row.latest_ranking_run_status)
                    ),
                    latest_ranking_activity_at=row.latest_ranking_activity_at,
                    successful_ranking_run_count=int(row.successful_ranking_run_count),
                    latest_ranking_roster_hash=row.latest_ranking_roster_hash,
                    latest_ranking_source_processing_run_id=(
                        None
                        if row.latest_ranking_source_processing_run_id is None
                        else str(row.latest_ranking_source_processing_run_id)
                    ),
                )
            )
        return PageResult(tuple(items), page, page_size, int(total))

    def list_participant_validation_matrices(
        self,
        session_id: str,
    ) -> tuple[ProcessingMatrixView, ...]:
        validation = aliased(SubmissionValidationRow)
        statement = (
            select(
                ValidationPreparedMatrixRow,
                validation.quality_metrics_json.label("diagnostics"),
                validation.consistency_ratio.label("consistency_ratio"),
                SubmissionRow,
                ParticipantRow.alias.label("participant_alias"),
                SessionStakeholderGroupRow.name.label("group_name"),
            )
            .select_from(SubmissionRow)
            .join(ParticipantRow)
            .join(SessionStakeholderGroupRow)
            .join(
                validation,
                validation.validation_id
                == _latest_validation_id(SubmissionRow.submission_id),
            )
            .join(
                ValidationPreparedMatrixRow,
                ValidationPreparedMatrixRow.validation_id == validation.validation_id,
            )
            .where(
                SubmissionRow.session_id == session_id,
                SubmissionRow.status == SubmissionStatus.SUBMITTED.value,
                validation.status.in_(
                    (
                        ValidationStatus.VALID.value,
                        ValidationStatus.VALID_WITH_WARNING.value,
                    )
                ),
            )
            .order_by(
                SessionStakeholderGroupRow.name,
                ParticipantRow.alias,
                SubmissionRow.participant_id,
            )
        )
        try:
            with self._session_factory() as database_session:
                rows = database_session.execute(statement).all()
                return tuple(
                    _participant_matrix_view(database_session, row) for row in rows
                )
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Participant validation matrices could not be loaded."
            ) from error

    def list_run_matrices(
        self,
        processing_run_id: str,
    ) -> tuple[ProcessingMatrixView, ...]:
        included_count = (
            select(func.count())
            .select_from(ProcessingRunSubmissionRow)
            .where(
                ProcessingRunSubmissionRow.processing_run_id
                == ProcessingMatrixRow.processing_run_id,
                ProcessingRunSubmissionRow.inclusion_status == "included",
            )
            .correlate(ProcessingMatrixRow)
            .scalar_subquery()
        )
        group_included_count = (
            select(func.count())
            .select_from(ProcessingRunSubmissionRow)
            .where(
                ProcessingRunSubmissionRow.processing_run_id
                == ProcessingMatrixRow.processing_run_id,
                ProcessingRunSubmissionRow.stakeholder_group_id
                == ProcessingMatrixRow.stakeholder_group_id,
                ProcessingRunSubmissionRow.inclusion_status == "included",
            )
            .correlate(ProcessingMatrixRow)
            .scalar_subquery()
        )
        statement = (
            select(
                ProcessingMatrixRow,
                SessionStakeholderGroupRow.name.label("group_name"),
                SessionStakeholderGroupRow.session_stakeholder_group_id.label(
                    "resolved_group_id"
                ),
                SessionStakeholderGroupRow.allocation_units.label("allocation_units"),
                SubmissionRow.participant_id.label("participant_id"),
                ParticipantRow.alias.label("participant_alias"),
                included_count.label("included_count"),
                group_included_count.label("group_included_count"),
            )
            .select_from(ProcessingMatrixRow)
            .outerjoin(
                SubmissionValidationRow,
                SubmissionValidationRow.validation_id
                == ProcessingMatrixRow.validation_id,
            )
            .outerjoin(
                SubmissionRow,
                SubmissionRow.submission_id == SubmissionValidationRow.submission_id,
            )
            .outerjoin(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .outerjoin(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == func.coalesce(
                    ProcessingMatrixRow.stakeholder_group_id,
                    SubmissionRow.session_stakeholder_group_id,
                ),
            )
            .where(ProcessingMatrixRow.processing_run_id == processing_run_id)
            .order_by(
                case(
                    (ProcessingMatrixRow.level == "participant", 0),
                    (ProcessingMatrixRow.level == "stakeholder_group", 1),
                    else_=2,
                ),
                SessionStakeholderGroupRow.name,
                ProcessingMatrixRow.processing_matrix_id,
            )
        )
        try:
            with self._session_factory() as database_session:
                rows = database_session.execute(statement).all()
                criterion_ids = {
                    str(item)
                    for row in rows
                    for item in row.ProcessingMatrixRow.criterion_ids_json
                }
                labels = _criterion_labels(database_session, criterion_ids)
        except SQLAlchemyError as error:
            raise PageQueryError("Run matrices could not be loaded.") from error
        return tuple(_run_matrix_view(row, labels) for row in rows)

    def list_ranking_results(
        self,
        ranking_run_id: str,
    ) -> tuple[RankingResultView, ...]:
        statement = (
            select(
                RankingResultRow,
                ParticipantRow.alias.label("participant_alias"),
                SubmissionRow.participant_id.label("participant_id"),
                SessionStakeholderGroupRow.name.label("group_name"),
                SessionStakeholderGroupRow.session_stakeholder_group_id.label(
                    "resolved_group_id"
                ),
            )
            .select_from(RankingResultRow)
            .join(
                ProcessingMatrixRow,
                ProcessingMatrixRow.processing_matrix_id
                == RankingResultRow.source_processing_matrix_id,
            )
            .outerjoin(
                SubmissionValidationRow,
                SubmissionValidationRow.validation_id
                == ProcessingMatrixRow.validation_id,
            )
            .outerjoin(
                SubmissionRow,
                SubmissionRow.submission_id == SubmissionValidationRow.submission_id,
            )
            .outerjoin(
                ParticipantRow,
                ParticipantRow.participant_id == SubmissionRow.participant_id,
            )
            .outerjoin(
                SessionStakeholderGroupRow,
                SessionStakeholderGroupRow.session_stakeholder_group_id
                == func.coalesce(
                    RankingResultRow.stakeholder_group_id,
                    SubmissionRow.session_stakeholder_group_id,
                ),
            )
            .where(RankingResultRow.ranking_run_id == ranking_run_id)
            .order_by(
                case(
                    (RankingResultRow.level == "participant", 0),
                    (RankingResultRow.level == "stakeholder_group", 1),
                    else_=2,
                ),
                SessionStakeholderGroupRow.name,
                RankingResultRow.ranking_result_id,
            )
        )
        try:
            with self._session_factory() as database_session:
                rows = database_session.execute(statement).all()
                alternative_ids = {
                    str(item["alternative_id"])
                    for row in rows
                    for item in json_from_storage(
                        row.RankingResultRow.alternatives_json
                    ).get("values", [])
                    if isinstance(item, Mapping) and "alternative_id" in item
                }
                alternative_labels = {
                    str(alternative_id): name
                    for alternative_id, name in database_session.execute(
                        select(
                            ScenarioAlternativeRow.alternative_id,
                            ScenarioAlternativeRow.name,
                        ).where(
                            ScenarioAlternativeRow.alternative_id.in_(alternative_ids)
                        )
                    )
                }
                views = tuple(
                    _ranking_result_view(row, alternative_labels) for row in rows
                )
        except (SQLAlchemyError, ValueError, TypeError) as error:
            raise PageQueryError("Ranking results could not be loaded.") from error
        return views

    def list_analysis_cases(
        self,
        analysis_run_id: str,
        *,
        scope_type: str | None = None,
        scope_id: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> PageResult[AnalysisCaseView]:
        _validate_paging(page=page, page_size=page_size)
        base = select(AnalysisCaseRow).where(
            AnalysisCaseRow.analysis_run_id == analysis_run_id
        )
        if scope_type is not None:
            base = base.where(AnalysisCaseRow.scope_type == scope_type)
        if scope_id is not None:
            base = base.where(AnalysisCaseRow.scope_id == scope_id)
        try:
            with self._session_factory() as database_session:
                total = (
                    database_session.scalar(
                        select(func.count()).select_from(base.subquery())
                    )
                    or 0
                )
                rows = database_session.scalars(
                    base.order_by(AnalysisCaseRow.sequence)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).all()
                participant_ids = {
                    row.subject_id
                    for row in rows
                    if row.subject_type == "participant" and row.subject_id
                }
                participant_aliases = {
                    str(participant.participant_id): participant.alias
                    for participant in database_session.scalars(
                        select(ParticipantRow).where(
                            ParticipantRow.participant_id.in_(participant_ids)
                        )
                    )
                    if participant.alias is not None
                }
                group_ids = {
                    row.scope_id
                    for row in rows
                    if row.scope_id
                    and row.scope_type in {"stakeholder_group", "participant"}
                } | {
                    row.subject_id
                    for row in rows
                    if row.subject_id and row.subject_type == "stakeholder_group"
                }
                group_labels = {
                    str(group.session_stakeholder_group_id): group.name
                    for group in database_session.scalars(
                        select(SessionStakeholderGroupRow).where(
                            SessionStakeholderGroupRow.session_stakeholder_group_id.in_(
                                group_ids
                            )
                        )
                    )
                }
                criterion_ids = {
                    row.subject_id
                    for row in rows
                    if row.subject_type == "criterion" and row.subject_id
                }
                criterion_labels = _criterion_labels(database_session, criterion_ids)
                alternative_ids = {
                    row.subject_id
                    for row in rows
                    if row.subject_type == "alternative" and row.subject_id
                }
                alternative_labels = {
                    str(alternative_id): name
                    for alternative_id, name in database_session.execute(
                        select(
                            ScenarioAlternativeRow.alternative_id,
                            ScenarioAlternativeRow.name,
                        ).where(
                            ScenarioAlternativeRow.alternative_id.in_(alternative_ids)
                        )
                    )
                }
        except (SQLAlchemyError, ValueError, TypeError) as error:
            raise PageQueryError("Analysis cases could not be loaded.") from error
        items = tuple(
            _analysis_case_view(
                row,
                participant_aliases=participant_aliases,
                group_labels=group_labels,
                criterion_labels=criterion_labels,
                alternative_labels=alternative_labels,
            )
            for row in rows
        )
        return PageResult(items, page, page_size, int(total))

    def list_analysis_scopes(
        self, analysis_run_id: str
    ) -> tuple[AnalysisScopeView, ...]:
        try:
            with self._session_factory() as database_session:
                values = database_session.execute(
                    select(
                        AnalysisCaseRow.scope_type,
                        AnalysisCaseRow.scope_id,
                    )
                    .where(AnalysisCaseRow.analysis_run_id == analysis_run_id)
                    .distinct()
                    .order_by(
                        AnalysisCaseRow.scope_type,
                        AnalysisCaseRow.scope_id,
                    )
                ).all()
                group_ids = {
                    scope_id
                    for scope_type, scope_id in values
                    if scope_id and scope_type in {"stakeholder_group", "participant"}
                }
                group_labels = {
                    str(group.session_stakeholder_group_id): group.name
                    for group in database_session.scalars(
                        select(SessionStakeholderGroupRow).where(
                            SessionStakeholderGroupRow.session_stakeholder_group_id.in_(
                                group_ids
                            )
                        )
                    )
                }
        except (SQLAlchemyError, ValueError, TypeError) as error:
            raise PageQueryError("Analysis scopes could not be loaded.") from error
        result = []
        for scope_type, scope_id in values:
            if scope_type == "session":
                label = "Session aggregate"
            elif scope_type == "stakeholder_group":
                label = group_labels.get(scope_id, scope_id or "Stakeholder group")
            elif scope_type == "participant":
                label = group_labels.get(scope_id, scope_id or "Unknown group")
            else:
                label = scope_type.replace("_", " ").title()
            result.append(AnalysisScopeView(scope_type, scope_id, label))
        return tuple(result)

    def summarize_analysis_level(
        self,
        analysis_run_id: str,
        *,
        result_level: str,
        stakeholder_group_id: str | None = None,
    ) -> AnalysisLevelSummaryView:
        if result_level not in {"session", "stakeholder_group", "participant"}:
            raise PageQueryError("Analysis result level is invalid.")
        try:
            with self._session_factory() as database_session:
                method = database_session.scalar(
                    select(AnalysisRunRow.method).where(
                        AnalysisRunRow.analysis_run_id == analysis_run_id
                    )
                )
                if method is None:
                    raise PageQueryError("Analysis run was not found.")
                case_scopes = (
                    ("participant", "session")
                    if method == "participant_influence" and result_level == "session"
                    else (
                        ("participant",)
                        if method == "participant_influence"
                        else (result_level,)
                    )
                )
                statement = select(
                    AnalysisCaseRow.status,
                    AnalysisCaseRow.result_json,
                    AnalysisCaseRow.warnings_json,
                ).where(
                    AnalysisCaseRow.analysis_run_id == analysis_run_id,
                    AnalysisCaseRow.scope_type.in_(case_scopes),
                )
                if stakeholder_group_id is not None:
                    statement = statement.where(
                        AnalysisCaseRow.scope_id == stakeholder_group_id
                    )
                rows = database_session.execute(statement).all()
                group_label = None
                if stakeholder_group_id is not None:
                    group_label = database_session.scalar(
                        select(SessionStakeholderGroupRow.name).where(
                            SessionStakeholderGroupRow.session_stakeholder_group_id
                            == stakeholder_group_id
                        )
                    )
        except PageQueryError:
            raise
        except (SQLAlchemyError, ValueError, TypeError) as error:
            raise PageQueryError("Analysis summary could not be loaded.") from error

        evaluated = not_evaluable = changes = reversals = maximum = warnings = 0
        distribution: dict[int, int] = {}
        for status, stored_results, stored_warnings in rows:
            results = json_from_storage(stored_results)
            candidates: tuple[object, ...]
            if method == "participant_influence":
                if result_level == "session":
                    candidates = (results.get("session_metrics"),)
                elif result_level == "stakeholder_group":
                    candidates = (results.get("group_metrics"),)
                else:
                    candidates = (
                        results.get("session_metrics"),
                        results.get("group_metrics"),
                    )
            else:
                candidates = (results.get("metrics"),)
            metrics = tuple(item for item in candidates if isinstance(item, Mapping))
            if status != AnalysisCaseStatus.EVALUATED.value or not metrics:
                not_evaluable += 1
            else:
                evaluated += 1
                changes += int(
                    any(bool(item.get("top_set_changed")) for item in metrics)
                )
                reversals += sum(
                    int(item.get("strict_reversals", 0)) for item in metrics
                )
                displacement = max(
                    int(item.get("maximum_rank_displacement", 0)) for item in metrics
                )
                maximum = max(maximum, displacement)
                distribution[displacement] = distribution.get(displacement, 0) + 1
            warning_values = json_from_storage(stored_warnings).get("values", ())
            if isinstance(warning_values, Sequence) and not isinstance(
                warning_values, str
            ):
                warnings += len(warning_values)
        return AnalysisLevelSummaryView(
            result_level=result_level,
            stakeholder_group_id=stakeholder_group_id,
            stakeholder_group_label=group_label,
            case_count=len(rows),
            evaluated_count=evaluated,
            not_evaluable_count=not_evaluable,
            top_set_change_count=changes,
            strict_reversal_count=reversals,
            maximum_rank_displacement=maximum,
            warning_count=warnings,
            displacement_distribution=dict(sorted(distribution.items())),
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

    def get_session_algorithm_configuration(
        self,
        session_id: str,
        role: AlgorithmRole,
    ) -> ConfiguredAlgorithmSummary | None:
        statement = (
            select(SessionAlgorithmConfigRow, AlgorithmImplementationRow)
            .join(
                AlgorithmImplementationRow,
                AlgorithmImplementationRow.algorithm_implementation_id
                == SessionAlgorithmConfigRow.algorithm_implementation_id,
            )
            .where(
                SessionAlgorithmConfigRow.configuration_version_id
                == select(SessionRow.active_configuration_version_id)
                .where(SessionRow.session_id == session_id)
                .scalar_subquery(),
                SessionAlgorithmConfigRow.role == role.value,
            )
            .order_by(SessionAlgorithmConfigRow.execution_order)
            .limit(1)
        )
        try:
            with self._session_factory() as database_session:
                row = database_session.execute(statement).first()
        except SQLAlchemyError as error:
            raise PageQueryError(
                "Configured session algorithm could not be loaded."
            ) from error
        if row is None:
            return None
        config = row.SessionAlgorithmConfigRow
        implementation = row.AlgorithmImplementationRow
        return ConfiguredAlgorithmSummary(
            algorithm_implementation_id=str(implementation.algorithm_implementation_id),
            stable_key=implementation.stable_key,
            role=AlgorithmRole(config.role),
            conceptual_method=implementation.conceptual_method,
            provider=implementation.provider,
            library_name=implementation.library_name,
            library_version=implementation.library_version,
            parameters=dict(config.parameter_json),
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
        return _scenario_document_from_bytes(row.inline_bytes)
    return {}


def _scenario_document_from_bytes(content: Any) -> dict[str, Any]:
    if content is None:
        return {}
    try:
        document = json.loads(bytes(content).decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return {}
    return document if isinstance(document, dict) else {}


def _scenario_tags(
    manifest: Mapping[str, Any],
    scenario_source: Any,
) -> tuple[str, ...]:
    raw_tags = manifest.get("tags")
    if raw_tags is None:
        raw_tags = _scenario_document_from_bytes(scenario_source).get("tags", ())
    if not isinstance(raw_tags, Sequence) or isinstance(raw_tags, (str, bytes)):
        return ()
    return tuple(tag for tag in raw_tags if isinstance(tag, str))


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
    session_filters: SessionSearchFilters | None = None,
    search: str | None,
    status: SessionStatus | None,
    scenario_key: str | None,
    timezone: ZoneInfo | None = None,
) -> list[Any]:
    normalized_search = (
        session_filters.search
        if session_filters is not None
        else (search.strip() if search is not None else "")
    )
    selected_scenario = (
        session_filters.scenario_key if session_filters is not None else scenario_key
    )
    normalized_scenario = selected_scenario.strip() if selected_scenario else ""
    filters: list[Any] = []
    if normalized_search:
        escaped = _escape_like(normalized_search.casefold())
        pattern = f"%{escaped}%"
        filters.append(
            or_(
                func.lower(SessionRow.title).like(pattern, escape="\\"),
                func.lower(SessionRow.public_slug).like(pattern, escape="\\"),
                func.lower(ScenarioDefinitionRow.title).like(pattern, escape="\\"),
                func.lower(ScenarioSnapshotRow.title).like(pattern, escape="\\"),
            )
        )
    if session_filters is not None and session_filters.statuses:
        filters.append(
            SessionRow.status.in_(
                tuple(item.value for item in session_filters.statuses)
            )
        )
    elif status is not None:
        filters.append(SessionRow.status == status.value)
    if normalized_scenario:
        filters.append(ScenarioDefinitionRow.scenario_key == normalized_scenario)
    if session_filters is not None and session_filters.domain:
        filters.append(
            or_(
                ScenarioDefinitionRow.domain == session_filters.domain,
                ScenarioSnapshotRow.domain == session_filters.domain,
            )
        )
    if session_filters is not None and (
        session_filters.date_from is not None or session_filters.date_to is not None
    ):
        query_timezone = timezone or ZoneInfo("UTC")
        date_column = {
            SessionDateField.CREATED: SessionRow.created_at,
            SessionDateField.OPENS: SessionRow.opens_at,
            SessionDateField.CLOSES: SessionRow.closes_at,
            SessionDateField.UPDATED: SessionRow.updated_at,
        }[session_filters.date_field]
        if session_filters.date_from is not None:
            start = datetime.combine(
                session_filters.date_from,
                time.min,
                tzinfo=query_timezone,
            ).astimezone(UTC)
            filters.append(date_column >= start)
        if session_filters.date_to is not None:
            end = datetime.combine(
                session_filters.date_to + timedelta(days=1),
                time.min,
                tzinfo=query_timezone,
            ).astimezone(UTC)
            filters.append(date_column < end)
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
    *,
    answered_count: int = 0,
    required_answer_count: int = 0,
    current_attempt: int | None = None,
    last_activity_at: datetime | None = None,
    resume_access_status: str = "missing",
    resume_expires_at: datetime | None = None,
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
        answered_count=answered_count,
        required_answer_count=required_answer_count,
        current_attempt=current_attempt,
        last_activity_at=last_activity_at,
        resume_access_status=resume_access_status,
        resume_expires_at=resume_expires_at,
    )


def _grant_status(row: ParticipantAccessGrantRow, *, at: datetime) -> str:
    if row.replaced_by_grant_id is not None:
        return "replaced"
    if row.revoked_at is not None:
        return "revoked"
    if row.expires_at <= at:
        return "expired"
    if row.issued_at > at:
        return "not_yet_active"
    return "active"


def _optional_identifier(value: Any) -> str | None:
    return None if value is None else str(value)


def _decimal_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _authored_answer_detail(row: Any) -> AuthoredAnswerDetail:
    answer = row.SubmissionAnswerRow
    question = row.ResponseQuestionDefinitionRow
    normalized_value = row.normalized_value
    return AuthoredAnswerDetail(
        submission_answer_id=str(answer.submission_answer_id),
        question_definition_id=str(answer.question_definition_id),
        display_order=question.display_order,
        prompt=question.prompt_snapshot,
        question_type=QuestionType(question.question_type),
        criterion_id=_optional_identifier(question.criterion_id),
        criterion_label=row.criterion_label,
        left_criterion_id=_optional_identifier(question.left_criterion_id),
        left_criterion_label=row.left_criterion_label,
        right_criterion_id=_optional_identifier(question.right_criterion_id),
        right_criterion_label=row.right_criterion_label,
        alternative_id=_optional_identifier(question.alternative_id),
        alternative_label=row.alternative_label,
        selected_scale_value_id=_optional_identifier(answer.selected_scale_value_id),
        selected_scale_label=row.scale_label,
        selected_scale_numeric_value=_decimal_text(row.scale_numeric_value),
        raw_value=answer.raw_value_json,
        numeric_value=_decimal_text(answer.numeric_value),
        rank_value=answer.rank_value,
        answered_at=answer.answered_at,
        response_time_ms=answer.response_time_ms,
        normalized_value=(
            normalized_value if isinstance(normalized_value, Mapping) else None
        ),
        normalized_crisp_value=_decimal_text(row.normalized_crisp_value),
        normalizer_version=row.normalizer_version,
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
            SubmissionValidationRow.attempt_number.desc(),
            SubmissionValidationRow.validation_id.desc(),
        )
        .limit(1)
        .correlate(SubmissionRow)
        .scalar_subquery()
    )


def _latest_review_id(
    submission_id: Any,
    validation_id: Any,
    validation_source: Any,
):
    return (
        select(SubmissionReviewDecisionRow.decision_id)
        .where(
            SubmissionReviewDecisionRow.submission_id == submission_id,
            SubmissionReviewDecisionRow.validation_id == validation_id,
        )
        .order_by(
            SubmissionReviewDecisionRow.decided_at.desc(),
            SubmissionReviewDecisionRow.decision_id.desc(),
        )
        .limit(1)
        .correlate(SubmissionRow, validation_source)
        .scalar_subquery()
    )


def _processing_blockers(
    session_row: SessionRow,
    row: Any,
    overview: SessionValidationOverview | None,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if session_row.status != SessionStatus.CLOSED.value:
        blockers.append("session.not_closed")
    if session_row.active_configuration_version_id is None:
        blockers.append("configuration.missing")
    if row.scenario_status != ScenarioSnapshotStatus.READY.value:
        blockers.append("scenario.not_ready")
    if int(row.effective_submission_count) == 0:
        blockers.append("roster.empty")
    if overview is not None:
        if overview.active_count:
            blockers.append("validation.active")
        if overview.unvalidated_count:
            blockers.append("validation.missing")
        if overview.warning_decisions_required:
            blockers.append("validation.review_required")
    if getattr(row, "latest_ranking_run_status", None) == RunStatus.FAILED.value:
        blockers.append("ranking.failed")
    if (
        getattr(row, "latest_ranking_run_status", None) == RunStatus.SUCCEEDED.value
        and overview is not None
        and (
            getattr(row, "latest_ranking_roster_hash", None)
            != overview.current_roster_hash
            or getattr(row, "latest_ranking_source_processing_run_id", None)
            != getattr(row, "latest_successful_run_id", None)
        )
    ):
        blockers.append("ranking.stale")
    return tuple(blockers)


def _processing_next_stage(
    row: Any,
    overview: SessionValidationOverview | None,
) -> str:
    if (
        row.SessionRow.status != SessionStatus.CLOSED.value
        or row.SessionRow.active_configuration_version_id is None
        or row.scenario_status != ScenarioSnapshotStatus.READY.value
        or int(row.effective_submission_count) == 0
    ):
        return "session_validation"
    if (
        getattr(row, "latest_ranking_run_status", None) == RunStatus.SUCCEEDED.value
        and overview is not None
        and getattr(row, "latest_ranking_roster_hash", None)
        == overview.current_roster_hash
        and getattr(row, "latest_ranking_source_processing_run_id", None)
        == getattr(row, "latest_successful_run_id", None)
    ):
        return "sensitivity_and_robustness"
    if row.latest_run_status == RunStatus.SUCCEEDED.value:
        return "create_ranking"
    if (
        row.latest_run_status == RunStatus.AWAITING_REVIEW.value
        and overview is not None
        and overview.validation_complete
    ):
        return "weight_generation"
    return "submission_validation"


def _ranking_result_view(
    row: Any,
    alternative_labels: Mapping[str, str],
) -> RankingResultView:
    result = row.RankingResultRow
    stored = json_from_storage(result.alternatives_json).get("values", [])
    alternatives: list[RankingAlternativeView] = []
    for item in stored:
        if not isinstance(item, Mapping):
            continue
        alternative_id = str(item.get("alternative_id", ""))
        metrics = item.get("method_metrics", {})
        alternatives.append(
            RankingAlternativeView(
                alternative_id=alternative_id,
                alternative_label=alternative_labels.get(
                    alternative_id, alternative_id
                ),
                rank=int(item.get("rank", 0)),
                preference_value=str(item.get("preference_value", "")),
                method_metrics=(metrics if isinstance(metrics, Mapping) else {}),
            )
        )
    participant_label = None
    if result.level == "participant":
        participant_label = row.participant_alias or (
            f"Participant {str(row.participant_id)[-8:]}"
            if row.participant_id is not None
            else "Participant"
        )
        label = (
            f"{participant_label} · {row.group_name}"
            if row.group_name
            else participant_label
        )
    elif result.level == "stakeholder_group":
        label = f"{row.group_name or 'Stakeholder group'} aggregate"
    else:
        label = "Session aggregate"
    return RankingResultView(
        ranking_result_id=str(result.ranking_result_id),
        ranking_run_id=str(result.ranking_run_id),
        source_processing_matrix_id=str(result.source_processing_matrix_id),
        level=result.level,
        label=label,
        participant_label=participant_label,
        stakeholder_group_id=(
            str(row.resolved_group_id) if row.resolved_group_id is not None else None
        ),
        stakeholder_group_label=row.group_name,
        validation_id=(
            str(result.validation_id)
            if result.level == "participant" and result.validation_id is not None
            else None
        ),
        metric_label=result.metric_label,
        alternatives=tuple(alternatives),
        diagnostics=json_from_storage(result.diagnostics_json),
        result_hash=result.result_hash,
    )


def _analysis_case_view(
    row: AnalysisCaseRow,
    *,
    participant_aliases: Mapping[str, str],
    group_labels: Mapping[str, str],
    criterion_labels: Mapping[str, str],
    alternative_labels: Mapping[str, str],
) -> AnalysisCaseView:
    subject_label = row.subject_id or row.subject_type.replace("_", " ").title()
    if row.subject_type == "participant" and row.subject_id:
        subject_label = participant_aliases.get(
            row.subject_id, f"Participant {row.subject_id[-8:]}"
        )
    elif row.subject_type == "stakeholder_group" and row.subject_id:
        subject_label = group_labels.get(row.subject_id, row.subject_id)
    elif row.subject_type == "criterion" and row.subject_id:
        subject_label = criterion_labels.get(row.subject_id, row.subject_id)
    elif row.subject_type == "alternative" and row.subject_id:
        subject_label = alternative_labels.get(row.subject_id, row.subject_id)
    scope_label = (
        group_labels.get(row.scope_id, row.scope_id)
        if row.scope_id
        else row.scope_type.replace("_", " ").title()
    )
    return AnalysisCaseView(
        analysis_case_id=str(row.analysis_case_id),
        sequence=row.sequence,
        status=AnalysisCaseStatus(row.status),
        scope_type=row.scope_type,
        scope_id=row.scope_id,
        scope_label=scope_label,
        subject_type=row.subject_type,
        subject_id=row.subject_id,
        subject_label=subject_label,
        inputs=json_from_storage(row.input_json),
        results=json_from_storage(row.result_json),
        warnings=tuple(
            str(item) for item in json_from_storage(row.warnings_json).get("values", [])
        ),
        content_hash=row.content_hash,
    )


def _criterion_labels(
    database_session: DatabaseSession,
    criterion_ids: set[str],
) -> dict[str, str]:
    if not criterion_ids:
        return {}
    rows = database_session.execute(
        select(ScenarioCriterionRow.criterion_id, ScenarioCriterionRow.name).where(
            ScenarioCriterionRow.criterion_id.in_(criterion_ids)
        )
    ).all()
    return {str(row.criterion_id): row.name for row in rows}


def _matrix_values(matrix_json: Mapping[str, object]) -> tuple[tuple[str, ...], ...]:
    raw_values = matrix_json.get("values", ())
    if not isinstance(raw_values, Sequence) or isinstance(raw_values, str):
        return ()
    values: list[tuple[str, ...]] = []
    for raw_row in raw_values:
        if not isinstance(raw_row, Sequence) or isinstance(raw_row, str):
            return ()
        values.append(tuple(str(value) for value in raw_row))
    return tuple(values)


def _weight_values(
    criterion_ids: tuple[str, ...],
    weights_json: Mapping[str, object],
) -> tuple[str | None, ...]:
    raw_values = weights_json.get("values", ())
    by_criterion: dict[str, str] = {}
    if isinstance(raw_values, Sequence) and not isinstance(raw_values, str):
        for item in raw_values:
            if not isinstance(item, Mapping):
                continue
            criterion_id = str(item.get("criterion_id", ""))
            value = item.get("weight")
            if value is None:
                value = item.get("middle")
            if criterion_id and value is not None:
                by_criterion[criterion_id] = str(value)
    return tuple(by_criterion.get(criterion_id) for criterion_id in criterion_ids)


def _participant_matrix_view(
    database_session: DatabaseSession,
    row: Any,
) -> ProcessingMatrixView:
    prepared = row.ValidationPreparedMatrixRow
    prepared_matrix_json = json_from_storage(prepared.matrix_json)
    criterion_ids = tuple(str(item) for item in prepared.criterion_ids_json)
    labels = _criterion_labels(database_session, set(criterion_ids))
    weight_rows = (
        database_session.execute(
            select(ParticipantCriterionWeightRow).where(
                ParticipantCriterionWeightRow.validation_id == prepared.validation_id
            )
        )
        .scalars()
        .all()
    )
    weights_by_criterion = {
        str(item.criterion_id): (
            _decimal_text(item.crisp_weight) or _decimal_text(item.fuzzy_middle)
        )
        for item in weight_rows
    }
    normalized_rows = database_session.scalars(
        select(ValidationNormalizedAnswerRow).where(
            ValidationNormalizedAnswerRow.validation_id == prepared.validation_id
        )
    ).all()
    warnings = tuple(
        database_session.scalars(
            select(ValidationMessageRow.code)
            .where(
                ValidationMessageRow.validation_id == prepared.validation_id,
                ValidationMessageRow.severity == "warning",
            )
            .order_by(ValidationMessageRow.display_order)
        ).all()
    )
    diagnostics = json_from_storage(row.diagnostics or {})
    if row.consistency_ratio is not None:
        diagnostics["consistency_ratio"] = str(row.consistency_ratio)
    participant_label = _participant_label(
        row.SubmissionRow.participant_id,
        row.participant_alias,
    )
    return ProcessingMatrixView(
        matrix_id=str(prepared.validation_id),
        level="participant",
        label=f"{participant_label} · {row.group_name}",
        participant_label=participant_label,
        stakeholder_group_id=str(row.SubmissionRow.session_stakeholder_group_id),
        stakeholder_group_label=row.group_name,
        validation_id=str(prepared.validation_id),
        criterion_ids=criterion_ids,
        criterion_labels=tuple(labels.get(item, item) for item in criterion_ids),
        values=_matrix_values(prepared_matrix_json),
        weights=tuple(weights_by_criterion.get(item) for item in criterion_ids),
        diagnostics=diagnostics,
        normalized_answers=tuple(
            json_from_storage(item.normalized_value_json) for item in normalized_rows
        ),
        matrix_hash=prepared.matrix_hash,
        warnings=warnings,
    )


def _run_matrix_view(
    row: Any,
    labels: Mapping[str, str],
) -> ProcessingMatrixView:
    matrix = row.ProcessingMatrixRow
    matrix_json = json_from_storage(matrix.matrix_json)
    weights_json = json_from_storage(matrix.weights_json)
    diagnostics_json = json_from_storage(matrix.diagnostics_json)
    criterion_ids = tuple(str(item) for item in matrix.criterion_ids_json)
    participant_label = (
        None
        if row.participant_id is None
        else _participant_label(row.participant_id, row.participant_alias)
    )
    level_label = {
        "participant": (
            f"{participant_label} · {row.group_name}"
            if participant_label is not None
            else "Participant matrix"
        ),
        "stakeholder_group": row.group_name or "Stakeholder group matrix",
        "session": "Session aggregate matrix",
    }.get(matrix.level, matrix.level.replace("_", " ").title())
    return ProcessingMatrixView(
        matrix_id=str(matrix.processing_matrix_id),
        level=matrix.level,
        label=level_label,
        participant_label=participant_label,
        stakeholder_group_id=(
            None if row.resolved_group_id is None else str(row.resolved_group_id)
        ),
        stakeholder_group_label=row.group_name,
        validation_id=(
            None if matrix.validation_id is None else str(matrix.validation_id)
        ),
        criterion_ids=criterion_ids,
        criterion_labels=tuple(labels.get(item, item) for item in criterion_ids),
        values=_matrix_values(matrix_json),
        weights=_weight_values(criterion_ids, weights_json),
        diagnostics=diagnostics_json,
        normalized_answers=(),
        matrix_hash=matrix.matrix_hash,
        warnings=(
            ("consistency.threshold_exceeded",)
            if diagnostics_json.get("threshold_exceeded")
            else ()
        ),
        participant_count=(
            1
            if matrix.level == "participant"
            else int(
                row.group_included_count
                if matrix.level == "stakeholder_group"
                else row.included_count
            )
        ),
        voting_power=(
            None
            if row.allocation_units is None
            else str(Decimal(row.allocation_units) / Decimal(10_000))
        ),
    )


def _public_session_summary(
    row: SessionRow,
    snapshot_row: ScenarioSnapshotRow,
    scenario_source: Any,
) -> PublicSessionSummary:
    return PublicSessionSummary(
        session_id=str(row.session_id),
        public_slug=row.public_slug,
        title=row.title,
        description=row.description,
        domain=snapshot_row.domain,
        tags=_scenario_tags(snapshot_row.manifest_json, scenario_source),
        policy_question=snapshot_row.policy_question,
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
