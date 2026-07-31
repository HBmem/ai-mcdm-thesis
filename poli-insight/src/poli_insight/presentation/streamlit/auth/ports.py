"""Authentication interface consumed by navigation and pages."""

from __future__ import annotations

from typing import Protocol

from poli_insight.presentation.streamlit.auth.models import (
    LoginMethod,
    LoginResult,
    Principal,
)


class AuthenticationAdapter(Protocol):
    @property
    def login_method(self) -> LoginMethod:
        """Describe the login interaction without exposing adapter type."""
        ...

    def current_principal(self) -> Principal:
        """Return the authenticated principal or an anonymous principal."""
        ...

    def login(self, *, password: str | None = None) -> LoginResult:
        """Authenticate locally or initiate the configured redirect."""
        ...

    def logout(self) -> None:
        """End the current application authentication session."""
        ...
