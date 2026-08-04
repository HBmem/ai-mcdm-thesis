"""Provider-neutral authentication models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class AuthBackend(StrEnum):
    DEVELOPMENT = "development"
    STREAMLIT_OIDC = "streamlit_oidc"


class LoginMethod(StrEnum):
    PASSWORD = "password"
    OIDC_REDIRECT = "oidc_redirect"


class LoginStatus(StrEnum):
    AUTHENTICATED = "authenticated"
    REJECTED = "rejected"
    REDIRECT_STARTED = "redirect_started"


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is unavailable or configured unsafely."""


@dataclass(frozen=True, slots=True)
class LoginResult:
    status: LoginStatus

    @property
    def authenticated(self) -> bool:
        return self.status == LoginStatus.AUTHENTICATED


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str | None
    display_name: str | None
    roles: frozenset[str]

    @classmethod
    def anonymous(cls) -> "Principal":
        return cls(
            subject=None,
            display_name=None,
            roles=frozenset(),
        )

    @property
    def is_authenticated(self) -> bool:
        return self.subject is not None

    def has_role(self, role: str) -> bool:
        return role in self.roles
