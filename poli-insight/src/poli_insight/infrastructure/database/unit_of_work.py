from __future__ import annotations

from typing import Self

from sqlalchemy.orm import Session, sessionmaker

from poli_insight.infrastructure.database.repositories.algorithm_repository import (
    SqlAlchemyAlgorithmRepository,
)
from poli_insight.infrastructure.database.repositories.analysis_repository import (
    SqlAlchemyAnalysisRunRepository,
)
from poli_insight.infrastructure.database.repositories.audit_repository import (
    SqlAlchemyAuditRepository,
)
from poli_insight.infrastructure.database.repositories.operations_repository import (
    SqlAlchemyInvitationImportRepository,
    SqlAlchemyParticipantSubmissionImportRepository,
    SqlAlchemySubmissionReviewRepository,
)
from poli_insight.infrastructure.database.repositories.participant_repository import (
    SqlAlchemyAccessAttemptRepository,
    SqlAlchemyEnrollmentAccessCodeRepository,
    SqlAlchemyParticipantAccessGrantRepository,
    SqlAlchemyParticipantConsentRepository,
    SqlAlchemyParticipantIdentityRepository,
    SqlAlchemyParticipantRepository,
    SqlAlchemySessionInvitationRepository,
)
from poli_insight.infrastructure.database.repositories.processing_repository import (
    SqlAlchemyProcessingRunRepository,
)
from poli_insight.infrastructure.database.repositories.ranking_repository import (
    SqlAlchemyRankingRunRepository,
)
from poli_insight.infrastructure.database.repositories.reporting_repository import (
    SqlAlchemyReportingRepository,
)
from poli_insight.infrastructure.database.repositories.result_package_repository import (
    SqlAlchemyParticipantResultReleaseRepository,
    SqlAlchemyResultPackageRepository,
)
from poli_insight.infrastructure.database.repositories.scenario_repository import (
    SqlAlchemyScenarioRepository,
)
from poli_insight.infrastructure.database.repositories.session_repository import (
    SqlAlchemySessionRepository,
)
from poli_insight.infrastructure.database.repositories.submission_repository import (
    SqlAlchemySubmissionRepository,
)
from poli_insight.infrastructure.database.repositories.validation_repository import (
    SqlAlchemyValidationRepository,
)


class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self.database_session = self._session_factory()
        self.reporting = SqlAlchemyReportingRepository(self.database_session)

        self.algorithms = SqlAlchemyAlgorithmRepository(self.database_session)
        self.analysis_runs = SqlAlchemyAnalysisRunRepository(self.database_session)
        self.audit_events = SqlAlchemyAuditRepository(self.database_session)
        self.scenarios = SqlAlchemyScenarioRepository(self.database_session)
        self.session = SqlAlchemySessionRepository(self.database_session)
        self.participants = SqlAlchemyParticipantRepository(self.database_session)
        self.invitations = SqlAlchemySessionInvitationRepository(self.database_session)
        self.access_grants = SqlAlchemyParticipantAccessGrantRepository(
            self.database_session
        )
        self.access_codes = SqlAlchemyEnrollmentAccessCodeRepository(
            self.database_session
        )
        self.access_attempts = SqlAlchemyAccessAttemptRepository(self.database_session)
        self.consents = SqlAlchemyParticipantConsentRepository(self.database_session)
        self.submissions = SqlAlchemySubmissionRepository(self.database_session)
        self.validations = SqlAlchemyValidationRepository(self.database_session)
        self.submission_reviews = SqlAlchemySubmissionReviewRepository(
            self.database_session
        )
        self.invitation_imports = SqlAlchemyInvitationImportRepository(
            self.database_session
        )
        self.participant_imports = SqlAlchemyParticipantSubmissionImportRepository(
            self.database_session
        )
        self.participant_identities = SqlAlchemyParticipantIdentityRepository(
            self.database_session
        )
        self.processing_runs = SqlAlchemyProcessingRunRepository(self.database_session)
        self.ranking_runs = SqlAlchemyRankingRunRepository(self.database_session)
        self.result_packages = SqlAlchemyResultPackageRepository(self.database_session)
        self.participant_result_releases = (
            SqlAlchemyParticipantResultReleaseRepository(self.database_session)
        )

        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            if exc_type is not None:
                self.database_session.rollback()
        finally:
            self.database_session.close()

    def commit(self) -> None:
        self.database_session.commit()

    def rollback(self) -> None:
        self.database_session.rollback()
