from __future__ import annotations

from dataclasses import dataclass

from poli_insight.config import Settings
from poli_insight.infrastructure.database.engine import build_session_factory

@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    settings: Settings

    # TODO: Add services below

def create_container(
    settings: Settings | None = None
) -> ApplicationContainer:

    resolved_settings = (
        settings or Settings.from_environment()
    )

    database_session_factory = build_session_factory(
        resolved_settings
    )

    # TODO: Add services

    return ApplicationContainer(
        settings=resolved_settings,
        # TODO: Add services below
    )