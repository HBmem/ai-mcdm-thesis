"""Production OIDC adapter backed by Streamlit's authentication API."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast

import streamlit as st

from poli_insight.presentation.streamlit.auth.models import (
    AuthConfigurationError,
    LoginMethod,
    LoginResult,
    LoginStatus,
    Principal,
)


class OidcUser(Protocol):
    is_logged_in: bool

    def to_dict(self) -> dict[str, Any]: ...


class OidcRuntime(Protocol):
    user: OidcUser

    def login(self) -> None: ...

    def logout(self) -> None: ...


class StreamlitOidcAuthAdapter:
    def __init__(
        self,
        *,
        role_claim_names: Sequence[str],
        runtime: OidcRuntime | None = None,
    ) -> None:
        self._role_claim_names = tuple(role_claim_names)
        self._runtime = runtime

    @property
    def login_method(self) -> LoginMethod:
        return LoginMethod.OIDC_REDIRECT

    def current_principal(self) -> Principal:
        runtime = self._oidc_runtime()
        user = getattr(runtime, "user", None)
        if user is None:
            raise AuthConfigurationError(
                "This Streamlit version does not provide OIDC authentication."
            )
        if not bool(getattr(user, "is_logged_in", False)):
            return Principal.anonymous()
        try:
            claims = user.to_dict()
        except (AttributeError, TypeError, ValueError) as error:
            raise AuthConfigurationError(
                "Authenticated user claims could not be read."
            ) from error
        principal = principal_from_claims(
            claims,
            role_claim_names=self._role_claim_names,
        )
        if not principal.is_authenticated:
            raise AuthConfigurationError(
                "The identity provider did not supply a subject claim."
            )
        return principal

    def login(self, *, password: str | None = None) -> LoginResult:
        del password
        self._oidc_runtime().login()
        return LoginResult(LoginStatus.REDIRECT_STARTED)

    def logout(self) -> None:
        self._oidc_runtime().logout()

    def _oidc_runtime(self) -> OidcRuntime:
        if self._runtime is not None:
            return self._runtime
        return cast(OidcRuntime, st)


def principal_from_claims(
    claims: Mapping[str, Any],
    *,
    role_claim_names: Sequence[str],
) -> Principal:
    subject = _first_text(claims, "sub")
    if subject is None:
        return Principal.anonymous()
    display_name = _first_text(claims, "name", "preferred_username", "email")
    roles: set[str] = set()
    for claim_name in role_claim_names:
        roles.update(_claim_values(claims.get(claim_name)))
    return Principal(
        subject=subject,
        display_name=display_name,
        roles=frozenset(roles),
    )


def _first_text(claims: Mapping[str, Any], *names: str) -> str | None:
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _claim_values(value: Any) -> set[str]:
    if isinstance(value, str):
        return {item for item in value.split() if item}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return {
            item.strip()
            for item in value
            if isinstance(item, str) and item.strip()
        }
    return set()
