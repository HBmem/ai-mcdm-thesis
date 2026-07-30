from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from poli_insight.domain.session import (
    Session,
    SessionConfigurationVersion,
)

# @dataclass(frozen=True, slots=True)
# class

class SessionRepository(Protocol):
    """Persistence port for the Session aggregate."""

    def add(
        self,
        session: Session,
    ) -> None:
        """Add a newly created session aggregate."""
        ...

    def get(
        self,
        session_id: str,
    ) -> Session | None:
        """Load a session without acquiring a write lock."""
        ...

    def get_for_update(
        self,
        session_id: str,
    ) -> Session | None:
        """Load and lock a session for a lifecycle-changing transaction."""
        ...

    def save(
        self,
        session: Session,
    ) -> None:
        """Persist the replacement state of an existing session aggregate."""
        ...

    def get_active_configuration(
        self,
        session_id: str,
    ) -> SessionConfigurationVersion | None:
        """Load the session's currently active configuration."""
        ...