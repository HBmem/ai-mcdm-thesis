from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from poli_insight.infrastructure.database.repositories.audit_repository import (
    SqlAlchemyAuditRepository,
)
from poli_insight.infrastructure.database.repositories.scenario_repository import (
    SqlAlchemyScenarioRepository,
)
from poli_insight.infrastructure.database.repositories.session_repository import (
    SqlAlchemySessionRepository,
)
from poli_insight.infrastructure.database.repositories.participant_repository import (
    SqlAlchemyParticipantRepository,
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

    def __enter__(self) -> "SqlAlchemyUnitOfWork":
        self.database_session = self._session_factory()

        self.audit_events = SqlAlchemyAuditRepository(
            self.database_session
        )
        self.scenarios = SqlAlchemyScenarioRepository(
            self.database_session
        )
        self.session = SqlAlchemySessionRepository(
            self.database_session
        )
        self.participants = SqlAlchemyParticipantRepository(
            self.database_session
        )
        self.submissions = SqlAlchemySubmissionRepository(
            self.database_session
        )
        self.validations = SqlAlchemyValidationRepository(
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

    def rollback(self) -> None:
        self.database_session.rollback()
