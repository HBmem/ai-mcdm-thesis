from __future__ import annotations

import streamlit as st

from src.utils.db import initialize_db
from src.utils.auth import is_admin_authenticated, logout_admin
from src.pages.page_registry import (
    HOME_PAGE,
    ACTIVE_SESSIONS_PAGE,
    PUBLISHED_RESULTS_PAGE,
    ABOUT_PAGE,
    ADMIN_LOGIN_PAGE,
    ADMIN_DASHBOARD_PAGE,
    MANAGE_SESSIONS_PAGE
)

st.set_page_config(
    page_title="",
    page_icon="",
    layout="wide"
)

initialize_db()

navigation_options = {
    "Public": [ HOME_PAGE, ACTIVE_SESSIONS_PAGE, PUBLISHED_RESULTS_PAGE, ABOUT_PAGE ],
    "Admin": [ADMIN_LOGIN_PAGE] if is_admin_authenticated() == False else [ADMIN_DASHBOARD_PAGE, MANAGE_SESSIONS_PAGE] 
}

if is_admin_authenticated():
    with st.sidebar:
        if st.button("Log Out"):
            logout_admin()
            st.rerun()

pg = st.navigation(navigation_options, position="sidebar")
pg.run()