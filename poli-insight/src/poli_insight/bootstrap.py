from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from poli_insight.application.services.session_service import SessionService
from poli_insight.application.services.participant_service import ParticipantService
from poli_insight.application.services.submissions_service import SubmissionService
from poli_insight.config import Settings
from poli_insight.infrastructure.database.engine import (
    build_session_factory,
)
from poli_insight.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)

@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Application services available to presentation layers."""

    settings: Settings
    session_service: SessionService
    participant_service: ParticipantService
    submission_service: SubmissionService

    # TODO: Add future services here:
    # scenario_service: ScenarioService
    # submission_service: SubmissionService
    # participant_service: ParticipantService

def create_container(
    settings: Settings | None = None,
) -> ApplicationContainer:
    """Construct the application dependency graph."""

    resolved_settings = (
        settings or Settings.from_environment()
    )

    database_session_factory = build_session_factory(
        resolved_settings
    )

    # partial produces a callable equivalent to:
    #
    # lambda: SqlAlchemyUnitOfWork(
    #     database_session_factory
    # )
    #
    # Each call creates a new unit of work and a new
    # SQLAlchemy Session.
    unit_of_work_factory = partial(
        SqlAlchemyUnitOfWork,
        database_session_factory,
    )

    session_service = SessionService(
        unit_of_work_factory=unit_of_work_factory
    )

    participant_service = ParticipantService(
        unit_of_work_factory=unit_of_work_factory
    )

    submission_service = SubmissionService(
        unit_of_work_factory=unit_of_work_factory
    )

    return ApplicationContainer(
        settings=resolved_settings,
        session_service=session_service,
        participant_service=participant_service,
        submission_service=submission_service,
    )