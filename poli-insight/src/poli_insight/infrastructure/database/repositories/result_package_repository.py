"""SQLAlchemy repositories for result packages and participant releases."""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from poli_insight.domain.enum import (
    PackageArtifactType,
    ParticipantReleaseStatus,
    RunStatus,
)
from poli_insight.domain.result_package import (
    ParticipantResultRelease,
    ResultPackageOverview,
    ResultPackageRun,
)
from poli_insight.infrastructure.database.json_codec import json_from_storage
from poli_insight.infrastructure.database.mappers.result_package import (
    _artifact_to_domain,
    release_to_domain,
    release_to_row,
    result_package_to_domain,
    result_package_to_row,
)
from poli_insight.infrastructure.database.models.processing import ProcessingRunRow
from poli_insight.infrastructure.database.models.result_package import (
    ParticipantResultReleaseRow,
    ResultPackageArtifactRow,
    ResultPackageRunRow,
)
from poli_insight.infrastructure.database.models.session import SessionRow


def _package_options():
    return (
        selectinload(ResultPackageRunRow.artifacts),
        selectinload(ResultPackageRunRow.subjects),
    )


class SqlAlchemyResultPackageRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, run: ResultPackageRun) -> None:
        self._database_session.add(result_package_to_row(run))

    def _overview_query(self):
        return (
            select(ResultPackageRunRow, ProcessingRunRow.configuration_version_id)
            .join(
                ProcessingRunRow,
                ProcessingRunRow.processing_run_id
                == ResultPackageRunRow.source_processing_run_id,
            )
            .where(ResultPackageRunRow.status == RunStatus.SUCCEEDED.value)
        )

    @staticmethod
    def _overview(row, configuration_id, artifacts=()):
        return ResultPackageOverview(
            package_run_id=str(row.package_run_id),
            session_id=str(row.session_id),
            run_number=row.run_number,
            completed_at=row.completed_at,
            output_hash=row.output_hash,
            source_roster_hash=row.source_roster_hash,
            configuration_version_id=str(configuration_id),
            source_processing_run_id=str(row.source_processing_run_id),
            source_ranking_run_id=str(row.source_ranking_run_id),
            source_analysis_run_ids=tuple(
                json_from_storage(row.source_analysis_run_ids_json).get("values", ())
            ),
            artifacts=artifacts,
        )

    def list_overviews(self, session_id):
        statement = (
            self._overview_query()
            .where(ResultPackageRunRow.session_id == session_id)
            .order_by(ResultPackageRunRow.run_number.desc())
        )
        return tuple(
            self._overview(row, configuration_id)
            for row, configuration_id in self._database_session.execute(statement)
        )

    def get_overview(self, package_run_id):
        result = self._database_session.execute(
            self._overview_query().where(
                ResultPackageRunRow.package_run_id == package_run_id
            )
        ).one_or_none()
        if result is None:
            return None
        # Do not load input manifests, participant subjects, or identity maps.
        artifacts = self._database_session.scalars(
            select(ResultPackageArtifactRow)
            .where(
                ResultPackageArtifactRow.package_run_id == package_run_id,
                ResultPackageArtifactRow.artifact_type.in_(
                    (
                        PackageArtifactType.COMMON_SECTION.value,
                        PackageArtifactType.VARIANT_MANIFEST.value,
                    )
                ),
            )
            .order_by(ResultPackageArtifactRow.sequence)
        )
        return self._overview(
            *result, artifacts=tuple(_artifact_to_domain(item) for item in artifacts)
        )

    def get(self, package_run_id: str) -> ResultPackageRun | None:
        row = self._database_session.execute(
            select(ResultPackageRunRow)
            .options(*_package_options())
            .where(ResultPackageRunRow.package_run_id == package_run_id)
        ).scalar_one_or_none()
        return None if row is None else result_package_to_domain(row)

    def list_for_session(self, session_id: str) -> tuple[ResultPackageRun, ...]:
        rows = self._database_session.scalars(
            select(ResultPackageRunRow)
            .options(*_package_options())
            .where(ResultPackageRunRow.session_id == session_id)
            .order_by(ResultPackageRunRow.run_number.desc())
        ).all()
        return tuple(result_package_to_domain(row) for row in rows)

    def find_success_by_input_hash(self, input_hash: str) -> ResultPackageRun | None:
        row = self._database_session.execute(
            select(ResultPackageRunRow)
            .options(*_package_options())
            .where(
                ResultPackageRunRow.input_hash == input_hash,
                ResultPackageRunRow.status == RunStatus.SUCCEEDED.value,
            )
        ).scalar_one_or_none()
        return None if row is None else result_package_to_domain(row)

    def next_run_number(self, session_id: str) -> int:
        _lock_session(self._database_session, session_id)
        value = self._database_session.scalar(
            select(func.max(ResultPackageRunRow.run_number)).where(
                ResultPackageRunRow.session_id == session_id
            )
        )
        return 1 if value is None else int(value) + 1


class SqlAlchemyParticipantResultReleaseRepository:
    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def add(self, release: ParticipantResultRelease) -> None:
        self._database_session.add(release_to_row(release))

    def save(self, release: ParticipantResultRelease) -> None:
        row = self._database_session.get(
            ParticipantResultReleaseRow, release.release_id
        )
        if row is None:
            raise ValueError("Participant result release no longer exists.")
        row.status = release.status.value
        row.withdrawn_at = release.withdrawn_at
        row.withdrawn_by = release.withdrawn_by
        row.withdrawal_reason = release.withdrawal_reason
        # Release the unique active slot before a replacement is inserted.
        self._database_session.flush()

    def get_active_for_session(
        self, session_id: str, *, for_update: bool = False
    ) -> ParticipantResultRelease | None:
        statement = select(ParticipantResultReleaseRow).where(
            ParticipantResultReleaseRow.session_id == session_id,
            ParticipantResultReleaseRow.status == ParticipantReleaseStatus.ACTIVE.value,
        )
        if for_update:
            statement = statement.with_for_update()
        row = self._database_session.execute(statement).scalar_one_or_none()
        return None if row is None else release_to_domain(row)

    def list_for_session(self, session_id: str) -> tuple[ParticipantResultRelease, ...]:
        rows = self._database_session.scalars(
            select(ParticipantResultReleaseRow)
            .where(ParticipantResultReleaseRow.session_id == session_id)
            .order_by(ParticipantResultReleaseRow.version_number.desc())
        ).all()
        return tuple(release_to_domain(row) for row in rows)

    def next_version(self, session_id: str) -> int:
        _lock_session(self._database_session, session_id)
        value = self._database_session.scalar(
            select(func.max(ParticipantResultReleaseRow.version_number)).where(
                ParticipantResultReleaseRow.session_id == session_id
            )
        )
        return 1 if value is None else int(value) + 1


def _lock_session(database_session: Session, session_id: str) -> None:
    dialect = database_session.get_bind().dialect.name
    if dialect == "sqlite":
        database_session.execute(
            update(SessionRow)
            .where(SessionRow.session_id == session_id)
            .values(session_id=SessionRow.session_id)
        )
    elif dialect == "postgresql":
        database_session.execute(
            select(SessionRow.session_id)
            .where(SessionRow.session_id == session_id)
            .with_for_update()
        ).scalar_one()
