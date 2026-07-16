from __future__ import annotations

from dataclasses import dataclass

import hmac
import streamlit as st

_AUTH_SESSION_KEY = "dev_admin_authenticated"

@dataclass(frozen=True, slots=True)
class CurrentUser:
    user_id: str | None
    display_name: str | None
    roles: frozenset[str]

    @property
    def is_authenticated(self) -> bool:
        return self.user_id is not None

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles

def get_current_user() -> CurrentUser:
    if not st.session_state.get(_AUTH_SESSION_KEY, False):
        return CurrentUser(None, None, frozenset())

    return CurrentUser(
        user_id="local-admin",
        display_name="Local administrator",
        roles=frozenset({"admin"}),
    )

def authenticate(password: str) -> bool:
    expected = str(st.secrets.get("DEV_ADMIN_PASSWORD", ""))

    if expected and hmac.compare_digest(password, expected):
        st.session_state[_AUTH_SESSION_KEY] = True
        return True

    return False


def logout_current_user() -> None:
    st.session_state.pop(_AUTH_SESSION_KEY, None)

# TODO: Production authentication
# def get_current_user() -> CurrentUser:
#     if not st.user.is_logged_in:
#         return CurrentUser(
#             user_id=None,
#             display_name=None,
#             roles=frozenset(),
#         )

#     raw_roles = st.user.get("roles", [])

#     if isinstance(raw_roles, str):
#         roles = frozenset({raw_roles})
#     else:
#         roles = frozenset(str(role) for role in raw_roles)

#     return CurrentUser(
#         user_id=str(
#             st.user.get("sub")
#             or st.user.get("email")
#         ),
#         display_name=st.user.get("name"),
#         roles=roles,
#     )