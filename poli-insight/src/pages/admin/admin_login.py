from __future__ import annotations

import streamlit as st

from src.utils.auth import is_admin_authenticated, get_configured_admin_password_hash, verify_admin_password

def render_admin_login_page() -> bool:
    if is_admin_authenticated():
        return True
    
    st.title("🔐 Admin Login")
    st.write("")

    configured_hash = get_configured_admin_password_hash()

    if not configured_hash:
        st.error(
            "Admin password is not configured. Set ADMIN_PASSWORD_HASH or ADMIN_PASSWORD "
            "in Streamlit secrets or environment variables."
        )
        return False
    
    with st.form("admin_login_form"):
        password = st.text_input("Admin password", type="password")
        submitted = st.form_submit_button("Log in", type="primary")

    if submitted:
        if verify_admin_password(password):
            st.session_state["admin_authenticated"] = True
            st.success("Login successful.")
            st.rerun()
        else:
            st.error("Invalid admin password.")

    return False