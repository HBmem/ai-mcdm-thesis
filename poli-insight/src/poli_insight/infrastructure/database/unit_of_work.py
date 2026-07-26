from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from poli_insight.infrastructure.database.repositories.scenario_repository import (
    SqlAlchemyScenarioRepository,
)
from poli_insight.infrastructure.database.repositories.session_repository import (
    SqlAlchemySessionRepository,
)
from poli_insight.infrastructure.database.repositories.participant_repository import (
    SQLAlchemyParticipantRepository,
)
from poli_insight.infrastructure.database.repositories.submission_repository import (
    SQLAlchemySubmissionRepository,
)
from poli_insight.infrastructure.database.repositories.submission_validation_repository import (
    SQLAlchemySubmissionValidationRepository,
    SQLAlchemySubmissionDashboardQueryRepository,
)

class SqlAlchemyUnitOfWork:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.database_session = self._session_factory()

        self.sessions = SqlAlchemySessionRepository(
            self.database_session
        )
        self.scenarios = SqlAlchemyScenarioRepository(
            self.database_session
        )
        self.participants = SQLAlchemyParticipantRepository(
            self.database_session
        )
        self.submissions = SQLAlchemySubmissionRepository(
            self.database_session
        )
        self.submission_validations = SQLAlchemySubmissionValidationRepository(
            self.database_session
        )
        self.submission_dashboard = SQLAlchemySubmissionDashboardQueryRepository(
            self.database_session
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