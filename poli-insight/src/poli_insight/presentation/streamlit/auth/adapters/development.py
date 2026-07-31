"""Explicitly gated local development authentication adapter."""

from __future__ import annotations

import hmac
from collections.abc import Callable, MutableMapping
from typing import Any

import streamlit as st

from poli_insight.presentation.streamlit.auth.models import (
    AuthConfigurationError,
    LoginMethod,
    LoginResult,
    LoginStatus,
    Principal,
)


DEVELOPMENT_AUTHENTICATED_KEY = "auth:development:authenticated"
PasswordLoader = Callable[[], str]


class DevelopmentAuthAdapter:
    def __init__(
        self,
        *,
        admin_role: str,
        session_state: MutableMapping[str, Any] | None = None,
        password_loader: PasswordLoader | None = None,
    ) -> None:
        self._admin_role = admin_role
        self._session_state = session_state
        self._password_loader = password_loader or _streamlit_password

    @property
    def login_method(self) -> LoginMethod:
        return LoginMethod.PASSWORD

    def current_principal(self) -> Principal:
        if not self._state().get(DEVELOPMENT_AUTHENTICATED_KEY, False):
            return Principal.anonymous()
        return Principal(
            subject="local-development-admin",
            display_name="Local development administrator",
            roles=frozenset({self._admin_role}),
        )

    def login(self, *, password: str | None = None) -> LoginResult:
        expected = self._password_loader()
        if not expected:
            raise AuthConfigurationError(
                "DEV_ADMIN_PASSWORD is required in development auth mode."
            )
        accepted = password is not None and hmac.compare_digest(
            password,
            expected,
        )
        if not accepted:
            return LoginResult(LoginStatus.REJECTED)
        self._state()[DEVELOPMENT_AUTHENTICATED_KEY] = True
        return LoginResult(LoginStatus.AUTHENTICATED)

    def logout(self) -> None:
        self._state().pop(DEVELOPMENT_AUTHENTICATED_KEY, None)

    def _state(self) -> MutableMapping[str, Any]:
        if self._session_state is not None:
            return self._session_state
        return st.session_state


def _streamlit_password() -> str:
    return str(st.secrets.get("DEV_ADMIN_PASSWORD", ""))
