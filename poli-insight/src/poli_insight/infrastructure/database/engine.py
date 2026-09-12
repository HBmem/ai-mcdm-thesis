"""Database engine and SQLAlchemy session-factory construction.

Schema creation belongs to Alembic migrations, not application startup. This
module registers every ORM model, configures one reusable engine, and returns
a sessionmaker that creates a fresh Session for each unit of work.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from poli_insight.config import Settings
from poli_insight.infrastructure.database.models import analysis as analysis_models
from poli_insight.infrastructure.database.models import audit as audit_models
from poli_insight.infrastructure.database.models import (
    operations as operations_models,
)
from poli_insight.infrastructure.database.models import (
    participation as participation_models,
)
from poli_insight.infrastructure.database.models import ranking as ranking_models
from poli_insight.infrastructure.database.models import scenario as scenario_models
from poli_insight.infrastructure.database.models import session as session_models
from poli_insight.infrastructure.database.models import (
    submission as submission_models,
)
from poli_insight.infrastructure.database.models import (
    validation as validation_models,
)

# These imports form the model-registration boundary for normal application
# startup. Keeping explicit aliases makes that side effect visible and prevents
# formatters from treating the imports as accidentally unused.
_REGISTERED_MODEL_MODULES = (
    analysis_models,
    audit_models,
    operations_models,
    participation_models,
    ranking_models,
    scenario_models,
    session_models,
    submission_models,
    validation_models,
)


def build_engine(settings: Settings) -> Engine:
    """Build the application's reusable SQLAlchemy engine.

    SQLite is used for local development and Streamlit may execute work on
    different threads, so its DBAPI thread check is disabled. Referential
    integrity is enabled independently for every pooled SQLite connection.
    PostgreSQL and other configured dialects retain their driver defaults.
    """

    database_url = _database_url(settings.database_url)
    engine_options: dict[str, Any] = {"pool_pre_ping": True}
    if database_url.get_backend_name() == "sqlite":
        engine_options["connect_args"] = {
            "check_same_thread": False,
        }

    engine = create_engine(database_url, **engine_options)
    if database_url.get_backend_name() == "sqlite":
        _register_sqlite_connection_settings(engine)
    return engine


def build_session_factory(
    settings: Settings,
) -> sessionmaker[Session]:
    """Return the session factory injected into unit-of-work instances."""

    engine = build_engine(settings)
    return sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
        autoflush=False,
    )


def _database_url(value: str) -> URL:
    if not value.strip():
        raise ValueError("Database URL cannot be empty.")
    try:
        return make_url(value)
    except (ArgumentError, TypeError, ValueError) as error:
        # Do not include the URL because it may contain database credentials.
        raise ValueError("Database URL is invalid.") from error


def _register_sqlite_connection_settings(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(
        dbapi_connection: Any,
        connection_record: Any,
    ) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()
