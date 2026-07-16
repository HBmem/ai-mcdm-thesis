from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from poli_insight.bootstrap import ApplicationContainer
from poli_insight.presentation.streamlit.auth import (
    get_current_user,
    logout_current_user,
)
from poli_insight.presentation.streamlit.pages.admin import (
    dashboard,
    login,
    manage_sessions,
)
from poli_insight.presentation.streamlit.pages.public import (
    about,
    active_sessions,
    home,
    published_results,
)


PageRenderer = Callable[[ApplicationContainer], None]


def _bind_page(
    renderer: PageRenderer,
    container: ApplicationContainer,
) -> Callable[[], None]:
    """Adapt render(container) to Streamlit's no-argument page API."""

    def bound_page() -> None:
        renderer(container)

    return bound_page


def run_navigation(
    container: ApplicationContainer,
) -> None:
    """Build navigation for the current user and run its selected page."""

    current_user = get_current_user()

    home_page = st.Page(
        _bind_page(home.render, container),
        title="Home",
        icon=":material/home:",
        url_path="home",
        default=True,
    )

    active_sessions_page = st.Page(
        _bind_page(active_sessions.render, container),
        title="Active sessions",
        icon=":material/event_available:",
        url_path="active-sessions",
    )

    published_results_page = st.Page(
        _bind_page(published_results.render, container),
        title="Published results",
        icon=":material/analytics:",
        url_path="published-results",
    )

    about_page = st.Page(
        _bind_page(about.render, container),
        title="About",
        icon=":material/info:",
        url_path="about",
    )

    public_pages = [
        home_page,
        active_sessions_page,
        published_results_page,
        about_page,
    ]

    navigation_sections: dict[str, list] = {
        "Public": public_pages,
    }

    if current_user.is_admin:
        dashboard_page = st.Page(
            _bind_page(dashboard.render, container),
            title="Dashboard",
            icon=":material/dashboard:",
            url_path="admin-dashboard",
        )

        manage_sessions_page = st.Page(
            _bind_page(manage_sessions.render, container),
            title="Manage sessions",
            icon=":material/settings:",
            url_path="manage-sessions",
        )

        navigation_sections["Administration"] = [
            dashboard_page,
            manage_sessions_page,
        ]

    elif not current_user.is_authenticated:
        login_page = st.Page(
            _bind_page(login.render, container),
            title="Administrator login",
            icon=":material/login:",
            url_path="login",
        )

        navigation_sections["Administration"] = [
            login_page
        ]

    _render_shared_sidebar(current_user)

    selected_page = st.navigation(
        navigation_sections,
        position="sidebar",
        expanded=True,
    )

    selected_page.run()


def _render_shared_sidebar(current_user) -> None:
    with st.sidebar:
        st.caption("Poli Insight")

        if current_user.is_authenticated:
            name = (
                current_user.display_name
                or current_user.user_id
                or "Authenticated user"
            )
            st.caption(f"Signed in as {name}")

            # TODO: Production authentication
            # if st.button(
            #     "Sign out",
            #     icon=":material/logout:",
            # ):
            #     st.logout()

            if st.button("Sign out", icon=":material/logout:"):
                logout_current_user()
                st.rerun()