"""Role-aware Streamlit navigation and route authorization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

from poli_insight.bootstrap import ApplicationContainer
from poli_insight.presentation.streamlit.auth import (
    AuthConfigurationError,
    AuthenticationAdapter,
    AuthenticationSettings,
    AuthorizationPolicy,
    Principal,
    create_authentication_adapter,
)
from poli_insight.presentation.streamlit.components.layout import reading_width
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.errors import (
    page_error_boundary,
    render_access_denied,
    render_error,
)
from poli_insight.presentation.streamlit.pages.admin import (
    dashboard,
    login,
    manage_sessions,
    processing,
    reports,
)
from poli_insight.presentation.streamlit.pages.public import (
    about,
    home,
    participate,
    published_results,
)

PageRenderer = Callable[[PageContext], None]


def run_navigation(container: ApplicationContainer) -> None:
    """Build navigation from verified identity and run the selected page."""

    authentication, authorization, principal, auth_error = _authentication_state()
    routes: dict[str, Any] = {}

    home_page = st.Page(
        _bind_page(
            home.render,
            container=container,
            authentication=authentication,
            authorization=authorization,
            principal=principal,
            routes=routes,
        ),
        title="Home",
        icon=":material/home:",
        url_path="home",
        default=True,
    )
    participate_page = st.Page(
        _bind_page(
            participate.render,
            container=container,
            authentication=authentication,
            authorization=authorization,
            principal=principal,
            routes=routes,
        ),
        title="Participate",
        icon=":material/how_to_vote:",
        url_path="participate",
    )
    results_page = st.Page(
        _bind_page(
            published_results.render,
            container=container,
            authentication=authentication,
            authorization=authorization,
            principal=principal,
            routes=routes,
        ),
        title="Published results",
        icon=":material/analytics:",
        url_path="results",
    )
    about_page = st.Page(
        _bind_page(
            about.render,
            container=container,
            authentication=authentication,
            authorization=authorization,
            principal=principal,
            routes=routes,
        ),
        title="About the research",
        icon=":material/science:",
        url_path="about",
    )
    routes.update(
        {
            "home": home_page,
            "participate": participate_page,
            "results": results_page,
            "about": about_page,
        }
    )
    sections: dict[str, list[Any]] = {
        "Public": [home_page, participate_page, results_page, about_page]
    }

    if authorization.can_access_admin(principal) and auth_error is None:
        admin_pages = _admin_pages(
            container=container,
            authentication=authentication,
            authorization=authorization,
            principal=principal,
            routes=routes,
        )
        routes.update(admin_pages)
        sections["Administration"] = list(admin_pages.values())
    else:
        login_page = st.Page(
            _bind_login_page(
                container=container,
                authentication=authentication,
                authorization=authorization,
                principal=principal,
                routes=routes,
                auth_error=auth_error,
            ),
            title="Account" if principal.is_authenticated else "Administrator login",
            icon=(
                ":material/manage_accounts:"
                if principal.is_authenticated
                else ":material/login:"
            ),
            url_path="admin-login",
        )
        routes["admin_login"] = login_page
        sections["Administration"] = [login_page]

    _render_sidebar_account(
        principal=principal,
        authentication=authentication,
        auth_error=auth_error,
    )
    selected_page = st.navigation(
        sections,
        position="sidebar",
        expanded=True,
    )
    selected_page.run()


def _admin_pages(
    *,
    container: ApplicationContainer,
    authentication: AuthenticationAdapter,
    authorization: AuthorizationPolicy,
    principal: Principal,
    routes: dict[str, Any],
) -> dict[str, Any]:
    specifications = (
        (
            "admin_dashboard",
            dashboard.render,
            "Dashboard",
            ":material/dashboard:",
            "admin",
            False,
        ),
        (
            "manage_sessions",
            manage_sessions.render,
            "Manage sessions",
            ":material/settings:",
            "admin-sessions",
            False,
        ),
        (
            "processing",
            processing.render,
            "Session processing",
            ":material/manufacturing:",
            "admin-processing",
            False,
        ),
        (
            "reports",
            reports.render,
            "Reports & Publication",
            ":material/rate_review:",
            "admin-reports",
            False,
        ),
    )
    pages: dict[str, Any] = {}
    for key, renderer, title, icon, url_path, default in specifications:
        pages[key] = st.Page(
            _bind_page(
                renderer,
                container=container,
                authentication=authentication,
                authorization=authorization,
                principal=principal,
                routes=routes,
                admin_required=True,
            ),
            title=title,
            icon=icon,
            url_path=url_path,
            default=default,
        )
    return pages


def _bind_page(
    renderer: PageRenderer,
    *,
    container: ApplicationContainer,
    authentication: AuthenticationAdapter,
    authorization: AuthorizationPolicy,
    principal: Principal,
    routes: dict[str, Any],
    admin_required: bool = False,
) -> Callable[[], None]:
    @page_error_boundary
    def bound_page() -> None:
        current_principal = principal
        if admin_required:
            current_principal = authentication.current_principal()
            if not authorization.can_access_admin(current_principal):
                render_access_denied(authenticated=current_principal.is_authenticated)
                return
        context = PageContext(
            container=container,
            queries=container.page_queries,
            principal=current_principal,
            authentication=authentication,
            routes=routes,
        )
        if renderer in (
            participate.render,
            about.render,
            login.render,
            published_results.render,
        ):
            with reading_width(renderer.__module__):
                renderer(context)
        else:
            renderer(context)

    return bound_page


def _bind_login_page(
    *,
    container: ApplicationContainer,
    authentication: AuthenticationAdapter,
    authorization: AuthorizationPolicy,
    principal: Principal,
    routes: dict[str, Any],
    auth_error: str | None,
) -> Callable[[], None]:
    if auth_error is None:
        return _bind_page(
            login.render,
            container=container,
            authentication=authentication,
            authorization=authorization,
            principal=principal,
            routes=routes,
        )

    def unavailable() -> None:
        render_error(
            "Authentication is unavailable",
            auth_error,
        )

    return unavailable


def _authentication_state() -> tuple[
    AuthenticationAdapter,
    AuthorizationPolicy,
    Principal,
    str | None,
]:
    try:
        settings = AuthenticationSettings.from_environment()
        authentication = create_authentication_adapter(settings)
        authorization = AuthorizationPolicy(admin_role=settings.admin_role)
        return (
            authentication,
            authorization,
            authentication.current_principal(),
            None,
        )
    except AuthConfigurationError as error:
        # Keep public routes available without ever downgrading to dev auth.
        safe_settings = AuthenticationSettings()
        authentication = create_authentication_adapter(safe_settings)
        authorization = AuthorizationPolicy(admin_role=safe_settings.admin_role)
        return (
            authentication,
            authorization,
            Principal.anonymous(),
            str(error),
        )


def _render_sidebar_account(
    *,
    principal: Principal,
    authentication: AuthenticationAdapter,
    auth_error: str | None,
) -> None:
    with st.sidebar:
        with st.container(key="pi_sidebar_brand"):
            st.markdown("**:material/account_balance: Poli Insight**")
            st.caption("Policy evaluation · Research workspace")
        if auth_error is not None:
            st.caption("Administrator authentication unavailable")
            return
        if not principal.is_authenticated:
            st.caption("Public access")
            return
        st.caption(
            "Signed in as "
            + (principal.display_name or principal.subject or "Authenticated user")
        )
        if st.button(
            "Sign out",
            icon=":material/logout:",
            key="auth:logout",
            use_container_width=True,
        ):
            authentication.logout()
            st.rerun()
