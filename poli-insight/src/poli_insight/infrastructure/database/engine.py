from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from poli_insight.config import Settings
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database import orm_models  # noqa: F401

def build_session_factory(
    settings: Settings,
) -> sessionmaker[Session]:
    engine_options = {
        "pool_pre_ping": True,
    }

    if settings.database_url.startswith("sqlite"):
        engine_options["connect_args"] = {
            "check_same_thread": False,
        }
    
    engine = create_engine(
        settings.database_url,
        **engine_options,
    )

    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )