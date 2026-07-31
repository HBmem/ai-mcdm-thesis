"""Authentication settings and fail-closed environment parsing."""

from __future__ import annotations

import os
from dataclasses import dataclass

from poli_insight.presentation.streamlit.auth.models import (
    AuthBackend,
    AuthConfigurationError,
)


_BACKEND_ALIASES = {
    "development": AuthBackend.DEVELOPMENT,
    "oidc": AuthBackend.STREAMLIT_OIDC,
    "streamlit_oidc": AuthBackend.STREAMLIT_OIDC,
}


@dataclass(frozen=True, slots=True)
class AuthenticationSettings:
    backend: AuthBackend = AuthBackend.STREAMLIT_OIDC
    admin_role: str = "admin"
    role_claim_names: tuple[str, ...] = ("roles", "groups")
    environment: str = "production"

    def __post_init__(self) -> None:
        normalized_role = self.admin_role.strip()
        normalized_environment = self.environment.strip().lower()
        normalized_claims = tuple(
            claim.strip() for claim in self.role_claim_names if claim.strip()
        )
        if not normalized_role:
            raise AuthConfigurationError("The admin role cannot be empty.")
        if not normalized_claims:
            raise AuthConfigurationError(
                "At least one role claim name is required."
            )
        if (
            self.backend is AuthBackend.DEVELOPMENT
            and normalized_environment != "development"
        ):
            raise AuthConfigurationError(
                "Development authentication is allowed only when "
                "POLI_INSIGHT_ENVIRONMENT=development."
            )
        object.__setattr__(self, "admin_role", normalized_role)
        object.__setattr__(self, "environment", normalized_environment)
        object.__setattr__(self, "role_claim_names", normalized_claims)

    @classmethod
    def from_environment(cls) -> "AuthenticationSettings":
        # AUTH_MODE remains a compatibility alias for the original foundation.
        raw_backend = os.getenv(
            "POLI_INSIGHT_AUTH_BACKEND",
            os.getenv("POLI_INSIGHT_AUTH_MODE", "streamlit_oidc"),
        ).strip().lower()
        backend = _BACKEND_ALIASES.get(raw_backend)
        if backend is None:
            raise AuthConfigurationError(
                "POLI_INSIGHT_AUTH_BACKEND must be 'streamlit_oidc' or "
                "'development'."
            )
        role_claim_names = tuple(
            name.strip()
            for name in os.getenv(
                "POLI_INSIGHT_AUTH_ROLE_CLAIMS",
                "roles,groups",
            ).split(",")
            if name.strip()
        )
        return cls(
            backend=backend,
            admin_role=os.getenv("POLI_INSIGHT_ADMIN_ROLE", "admin"),
            role_claim_names=role_claim_names,
            environment=os.getenv(
                "POLI_INSIGHT_ENVIRONMENT",
                "production",
            ),
        )
