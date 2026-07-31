"""Swappable authentication boundary for the Streamlit presentation layer."""

from poli_insight.presentation.streamlit.auth.config import (
    AuthenticationSettings,
)
from poli_insight.presentation.streamlit.auth.factory import (
    create_authentication_adapter,
)
from poli_insight.presentation.streamlit.auth.models import (
    AuthBackend,
    AuthConfigurationError,
    LoginMethod,
    LoginResult,
    LoginStatus,
    Principal,
)
from poli_insight.presentation.streamlit.auth.policy import AuthorizationPolicy
from poli_insight.presentation.streamlit.auth.ports import AuthenticationAdapter

__all__ = (
    "AuthBackend",
    "AuthConfigurationError",
    "AuthenticationAdapter",
    "AuthenticationSettings",
    "AuthorizationPolicy",
    "LoginMethod",
    "LoginResult",
    "LoginStatus",
    "Principal",
    "create_authentication_adapter",
)
