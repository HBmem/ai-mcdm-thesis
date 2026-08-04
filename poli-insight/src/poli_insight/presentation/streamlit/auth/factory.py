"""Composition point for selecting one authentication adapter."""

from __future__ import annotations

from poli_insight.presentation.streamlit.auth.adapters.development import (
    DevelopmentAuthAdapter,
)
from poli_insight.presentation.streamlit.auth.adapters.streamlit_oidc import (
    StreamlitOidcAuthAdapter,
)
from poli_insight.presentation.streamlit.auth.config import (
    AuthenticationSettings,
)
from poli_insight.presentation.streamlit.auth.models import (
    AuthBackend,
    AuthConfigurationError,
)
from poli_insight.presentation.streamlit.auth.ports import AuthenticationAdapter


def create_authentication_adapter(
    settings: AuthenticationSettings,
) -> AuthenticationAdapter:
    if settings.backend == AuthBackend.DEVELOPMENT:
        return DevelopmentAuthAdapter(admin_role=settings.admin_role)
    if settings.backend == AuthBackend.STREAMLIT_OIDC:
        return StreamlitOidcAuthAdapter(
            role_claim_names=settings.role_claim_names,
        )
    raise AuthConfigurationError(
        f"Unsupported authentication backend: {settings.backend!r}."
    )
