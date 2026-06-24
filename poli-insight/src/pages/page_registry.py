from __future__ import annotations

import streamlit as st

from src.utils.page_context import pages

from src.pages.public.home import render_home_page
from src.pages.public.active_sessions import render_active_sessions_page
from src.pages.public.published_results import render_published_results_page
from src.pages.public.about import render_about_page

from src.pages.admin.admin_login import render_admin_login_page
from src.pages.admin.admin_dashboard import render_admin_dashboard_page
from src.pages.admin.manage_sessions import render_manage_sessions_page

# Public pages includes the home page and the about page, which are accessible to all users without authentication.
HOME_PAGE = st.Page(
    render_home_page,
    title="Home",
    icon="🏠",
    url_path="/",
    default=True
)
pages["home"] = HOME_PAGE

ACTIVE_SESSIONS_PAGE = st.Page(
    render_active_sessions_page,
    title="Active Sessions",
    icon="📊",
    url_path="/active-sessions"
)
pages["active_sessions"] = ACTIVE_SESSIONS_PAGE

PUBLISHED_RESULTS_PAGE = st.Page(
    render_published_results_page,
    title="Published Results",
    icon="📈",
    url_path="/published-results"
)
pages["published_results"] = PUBLISHED_RESULTS_PAGE

ABOUT_PAGE = st.Page(
    render_about_page,
    title="About",
    icon="ℹ️",
    url_path="/about"
)
pages["about"] = ABOUT_PAGE

# Admin pages include the admin dashboard, session management, session processing, AI analytics, and publication management pages, which are accessible only to authenticated admin users.
ADMIN_LOGIN_PAGE = st.Page(
    render_admin_login_page,
    title="Admin Login",
    icon="🔐",
    url_path="/login"
)
pages["admin_login"] = ADMIN_LOGIN_PAGE

ADMIN_DASHBOARD_PAGE = st.Page(
    render_admin_dashboard_page,
    title="Admin Dashboard",
    icon="⚙️",
    url_path="/admin"
)
pages["admin_dashboard"] = ADMIN_DASHBOARD_PAGE

MANAGE_SESSIONS_PAGE = st.Page(
    render_manage_sessions_page,
    title="Manage Sessions",
    icon="📋",
    url_path="/manage-sessions"
)
pages["manage_sessions"] = MANAGE_SESSIONS_PAGE

# SESSION_PROCESSING_PAGE = st.Page(
#     render_session_processing_page,
#     title="Session Processing",
#     icon="⚡",
#     url_path="/session-processing"
# )

# AI_ANALYTICS_PAGE = st.Page(
#     render_ai_analytics_page,
#     title="AI Analytics",
#     icon="🧠",
#     url_path="/ai-analytics"
# )

# PUBLICATION_MANAGEMENT_PAGE = st.Page(
#     render_publication_management_page,
#     title="Publication Management",
#     icon="📚",
#     url_path="/publication-management"
# )