"""Provider-independent authorization policies."""

from __future__ import annotations

from poli_insight.presentation.streamlit.auth.models import Principal


class AuthorizationPolicy:
    def __init__(self, *, admin_role: str) -> None:
        normalized_role = admin_role.strip()
        if not normalized_role:
            raise ValueError("admin_role cannot be empty.")
        self._admin_role = normalized_role

    def can_access_admin(self, principal: Principal) -> bool:
        return principal.is_authenticated and principal.has_role(
            self._admin_role
        )
