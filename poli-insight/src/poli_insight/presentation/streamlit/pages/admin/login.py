from __future__ import annotations

import streamlit as st

from poli_insight.presentation.streamlit.auth import (
    LoginMethod,
    LoginStatus,
)
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    render_page_header,
)
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.errors import UserFacingError


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Restricted administration",
            title="Administrator Login",
            description=(
                "Administration requires an authenticated account carrying the "
                "configured administrator role."
            ),
        )
    )

    if context.principal.is_authenticated:
        st.warning(
            "You are signed in, but this account is not authorized for "
            "administration.",
            icon=":material/admin_panel_settings:",
        )
        return

    if context.authentication.login_method == LoginMethod.OIDC_REDIRECT:
        st.write(
            "Continue to the configured identity provider. Authorization is "
            "evaluated again after sign-in."
        )
        if st.button(
            "Sign in",
            type="primary",
            icon=":material/login:",
        ):
            context.authentication.login()
        return

    st.warning(
        "Development authentication is active. Do not use this mode in a "
        "deployed environment.",
        icon=":material/warning:",
    )
    with st.form("auth:development:login"):
        password = st.text_input("Development password", type="password")
        submitted = st.form_submit_button(
            "Sign in",
            type="primary",
            icon=":material/login:",
        )
    if not submitted:
        return
    result = context.authentication.login(password=password)
    if result.status == LoginStatus.REJECTED:
        raise UserFacingError(
            "The supplied credentials were not accepted.",
            title="Sign-in failed",
        )
    if result.authenticated:
        st.rerun()
