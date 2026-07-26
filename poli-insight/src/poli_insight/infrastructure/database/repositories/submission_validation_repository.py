from __future__ import annotations

import json

from datetime import UTC, datetime
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from poli_insight.domain.enums import (
    ParticipantStatus,
    SubmissionStatus,
    WeightingMethod,
)
from poli_insight.domain.submissions import SubmissionValidation
from poli_insight.application.submission_queries import (
    SubmissionDashboardMetrics,
    SubmissionDashboardPage,
    SubmissionTableItem,
)
from poli_insight.infrastructure.database.orm_models import (
    ParticipantRow,
    SessionRow,
    SessionStakeholderGroupRow,
    SubmissionRow,
    SubmissionValidationRow,
)

class SQLAlchemySubmissionValidationRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(
        self,
        validation: SubmissionValidation,
    ) -> None:
        self._database_session.add(
            SubmissionValidationRow(
                validation_id=validation.validation_id,
                submission_id=validation.submission_id,
                answers_hash=validation.answers_hash,
                weighting_method=validation.weighting_method.value,
                validator_version=validation.validator_version,
                completion_ratio=validation.completion_ratio,
                weights_json=json.dumps(
                    validation.weights,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                consistency_ratio=validation.consistency_ratio,
                is_valid=validation.is_valid,
                errors_json=json.dumps(
                    list(validation.errors),
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                validated_at=validation.validated_at,
                validated_by=validation.validated_by,
            )
        )

    @staticmethod
    def _to_domain(
        row: SubmissionValidationRow,
    ) -> SubmissionValidation:
        return SubmissionValidation(
            validation_id=row.validation_id,
            submission_id=row.submission_id,
            answers_hash=row.answers_hash,
            weighting_method=WeightingMethod(row.weighting_method),
            validator_version=row.validator_version,
            completion_ratio=row.completion_ratio,
            weights=json.loads(row.weights_json),
            consistency_ratio=row.consistency_ratio,
            is_valid=row.is_valid,
            errors=json.loads(row.errors_json),
            validated_at=_as_utc(row.validated_at),
            validated_by=row.validated_by,
        )
        

class SQLAlchemySubmissionDashboardQueryRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def get_dashboard(
        self,
        session_id: str,
        *,
        page: int,
        page_size: int,
        consistency_threshold: float,
    ) -> SubmissionDashboardPage:
        if not session_id.strip():
            raise ValueError("Session ID is required.")

        if page < 1:
            raise ValueError("Page must be at least 1.")

        if not 1 <= page_size <= 100:
            raise ValueError(
                "Page size must be between 1 and 100."
            )

        if consistency_threshold < 0:
            raise ValueError(
                "Consistency threshold cannot be negative."
            )

        submission_priority = case(
            (
                SubmissionRow.status
                == SubmissionStatus.SUBMITTED.value,
                0,
            ),
            else_=1,
        )

        current_submissions = (
            select(
                SubmissionRow.submission_id.label(
                    "submission_id"
                ),
                SubmissionRow.participant_id.label(
                    "participant_id"
                ),
                SubmissionRow.status.label(
                    "submission_status"
                ),
                SubmissionRow.submitted_at.label(
                    "submitted_at"
                ),
                func.row_number()
                .over(
                    partition_by=SubmissionRow.participant_id,
                    order_by=(
                        submission_priority.asc(),
                        SubmissionRow.attempt_number.desc(),
                        SubmissionRow.submission_id.asc(),
                    ),
                )
                .label("submission_rank"),
            )
            .where(
                SubmissionRow.status.in_(
                    (
                        SubmissionStatus.DRAFT.value,
                        SubmissionStatus.SUBMITTED.value,
                    )
                )
            )
            .subquery("current_submissions")
        )

        latest_validations = (
            select(
                SubmissionValidationRow.validation_id.label(
                    "validation_id"
                ),
                SubmissionValidationRow.submission_id.label(
                    "submission_id"
                ),
                SubmissionValidationRow.weighting_method.label(
                    "weighting_method"
                ),
                SubmissionValidationRow.completion_ratio.label(
                    "completion_ratio"
                ),
                SubmissionValidationRow.consistency_ratio.label(
                    "consistency_ratio"
                ),
                SubmissionValidationRow.is_valid.label(
                    "is_valid"
                ),
                func.row_number()
                .over(
                    partition_by=(
                        SubmissionValidationRow.submission_id,
                        SubmissionValidationRow.weighting_method,
                    ),
                    order_by=(
                        SubmissionValidationRow.validated_at.desc(),
                        SubmissionValidationRow.validation_id.desc(),
                    ),
                )
                .label("validation_rank"),
            )
            .subquery("latest_validations")
        )

        participant_conditions = (
            ParticipantRow.session_id == session_id,
            ParticipantRow.access_status
            == ParticipantStatus.ACTIVE.value,
        )

        current_submission_join = and_(
            current_submissions.c.participant_id
            == ParticipantRow.participant_id,
            current_submissions.c.submission_rank == 1,
        )

        latest_validation_join = and_(
            latest_validations.c.submission_id
            == current_submissions.c.submission_id,
            latest_validations.c.weighting_method
            == SessionRow.weighting_method,
            latest_validations.c.validation_rank == 1,
        )

        metrics_row = self._database_session.execute(
            select(
                func.count(
                    ParticipantRow.participant_id
                ).label("expected"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                current_submissions.c.submission_status
                                == SubmissionStatus.SUBMITTED.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("complete"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                current_submissions.c.submission_status
                                == SubmissionStatus.DRAFT.value,
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("in_progress"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                current_submissions.c.submission_id.is_(
                                    None
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("missing"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    current_submissions.c.submission_status
                                    == SubmissionStatus.SUBMITTED.value,
                                    latest_validations.c.consistency_ratio
                                    > consistency_threshold,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("high_consistency_ratio"),
            )
            .select_from(ParticipantRow)
            .join(
                SessionRow,
                SessionRow.session_id
                == ParticipantRow.session_id,
            )
            .outerjoin(
                current_submissions,
                current_submission_join,
            )
            .outerjoin(
                latest_validations,
                latest_validation_join,
            )
            .where(*participant_conditions)
        ).one()

        metrics = SubmissionDashboardMetrics(
            expected=int(metrics_row.expected),
            complete=int(metrics_row.complete),
            in_progress=int(metrics_row.in_progress),
            missing=int(metrics_row.missing),
            high_consistency_ratio=int(
                metrics_row.high_consistency_ratio
            ),
        )

        rows = self._database_session.execute(
            select(
                ParticipantRow.participant_id,
                ParticipantRow.name.label("participant_name"),
                ParticipantRow.alias.label("participant_alias"),
                ParticipantRow.stakeholder_group_id,
                SessionStakeholderGroupRow.stakeholder_group_name,
                current_submissions.c.submission_id,
                current_submissions.c.submission_status,
                current_submissions.c.submitted_at,
                latest_validations.c.validation_id,
                latest_validations.c.completion_ratio,
                latest_validations.c.consistency_ratio,
                latest_validations.c.is_valid,
            )
            .select_from(ParticipantRow)
            .join(
                SessionRow,
                SessionRow.session_id
                == ParticipantRow.session_id,
            )
            .join(
                SessionStakeholderGroupRow,
                and_(
                    SessionStakeholderGroupRow.session_id
                    == ParticipantRow.session_id,
                    SessionStakeholderGroupRow.stakeholder_group_id
                    == ParticipantRow.stakeholder_group_id,
                ),
            )
            .outerjoin(
                current_submissions,
                current_submission_join,
            )
            .outerjoin(
                latest_validations,
                latest_validation_join,
            )
            .where(*participant_conditions)
            .order_by(
                ParticipantRow.created_at.asc(),
                ParticipantRow.participant_id.asc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        items = []

        for row in rows:
            submission_status = (
                SubmissionStatus(row.submission_status)
                if row.submission_status is not None
                else None
            )

            if submission_status is None:
                validation_status = "missing"
            elif submission_status == SubmissionStatus.DRAFT:
                validation_status = "pending"
            elif row.validation_id is None:
                validation_status = "pending"
            elif bool(row.is_valid):
                validation_status = "valid"
            elif (
                row.consistency_ratio is not None
                and row.consistency_ratio
                > consistency_threshold
            ):
                validation_status = "cr_high"
            else:
                validation_status = "invalid"

            items.append(
                SubmissionTableItem(
                    participant_id=row.participant_id,
                    participant_name=row.participant_name,
                    participant_alias=row.participant_alias,
                    stakeholder_group_id=(
                        row.stakeholder_group_id
                    ),
                    stakeholder_group_name=(
                        row.stakeholder_group_name
                    ),
                    submission_id=row.submission_id,
                    submission_status=submission_status,
                    submitted_at=_as_utc(row.submitted_at),
                    completion_ratio=float(
                        row.completion_ratio or 0.0
                    ),
                    consistency_ratio=(
                        float(row.consistency_ratio)
                        if row.consistency_ratio is not None
                        else None
                    ),
                    validation_status=validation_status,
                )
            )

        return SubmissionDashboardPage(
            metrics=metrics,
            items=tuple(items),
            total=metrics.expected,
            page=page,
            page_size=page_size,
        )
    
def _as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)

    return value.astimezone(UTC)