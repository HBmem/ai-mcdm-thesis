from __future__ import annotations

import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    database_url: str
    app_timezone: str

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            database_url=os.getenv(
                "DATABASE_URL",
                "sqlite+pysqlite:///database/poli-insight.sqlite"
            ),
            app_timezone=os.getenv("APP_TIMEZONE", "America/Los_Angeles"),
        )