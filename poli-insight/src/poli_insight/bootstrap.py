from __future__ import annotations

from dataclasses import dataclass

from poli_insight.application.queries.page_queries import PageQueries
from poli_insight.application.use_cases.add_session_configuration import (
    AddSessionConfiguration,
)
from poli_insight.application.use_cases.close_session import CloseSession
from poli_insight.application.use_cases.create_session import CreateSession
from poli_insight.application.use_cases.import_scenario import ImportScenario
from poli_insight.application.use_cases.open_session import OpenSession
from poli_insight.application.use_cases.save_submission_draft import (
    SaveSubmissionDraft,
)
from poli_insight.application.use_cases.submit_response import SubmitResponse
from poli_insight.config import Settings
from poli_insight.infrastructure.database.engine import build_session_factory
from poli_insight.infrastructure.database.queries.page_queries import (
    SqlAlchemyPageQueries,
)
from poli_insight.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
)


@dataclass(frozen=True, slots=True)
class SessionUseCases:
    create: CreateSession
    add_configuration: AddSessionConfiguration
    open: OpenSession
    close: CloseSession


@dataclass(frozen=True, slots=True)
class SubmissionUseCases:
    save_draft: SaveSubmissionDraft
    submit: SubmitResponse


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    settings: Settings
    page_queries: PageQueries
    import_scenario: ImportScenario
    sessions: SessionUseCases
    submissions: SubmissionUseCases

def create_container(
    settings: Settings | None = None,
) -> ApplicationContainer:
    resolved_settings = settings or Settings.from_environment()
    session_factory = build_session_factory(resolved_settings)

    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return ApplicationContainer(
        settings=resolved_settings,
        page_queries=SqlAlchemyPageQueries(session_factory, resolved_settings.app_timezone),
        import_scenario=ImportScenario(unit_of_work_factory),
        sessions=SessionUseCases(
            create=CreateSession(unit_of_work_factory),
            add_configuration=AddSessionConfiguration(
                unit_of_work_factory
            ),
            open=OpenSession(unit_of_work_factory),
            close=CloseSession(unit_of_work_factory),
        ),
        submissions=SubmissionUseCases(
            save_draft=SaveSubmissionDraft(unit_of_work_factory),
            submit=SubmitResponse(unit_of_work_factory),
        ),
    )

# from __future__ import annotations

# from dataclasses import dataclass

# from poli_insight.config import Settings
# from poli_insight.infrastructure.database.engine import build_session_factory

# @dataclass(frozen=True, slots=True)
# class ApplicationContainer:
#     settings: Settings

#     # TODO: Add services below

# def create_container(
#     settings: Settings | None = None
# ) -> ApplicationContainer:

#     resolved_settings = (
#         settings or Settings.from_environment()
#     )

#     database_session_factory = build_session_factory(
#         resolved_settings
#     )

#     # TODO: Add services

#     return ApplicationContainer(
#         settings=resolved_settings,
#         # TODO: Add services below
#     )
