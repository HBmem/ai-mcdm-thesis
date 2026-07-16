import streamlit as st

from poli_insight.bootstrap import ApplicationContainer
from poli_insight.presentation.streamlit.auth import authenticate

def render(container: ApplicationContainer) -> None:
    del container

    # TODO: Production authentication
    # st.title("Administrator login")
    # st.button("Log in", on_click=st.login)

    st.title("Administrator login")

    with st.form("admin-login"):
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        if authenticate(password):
            st.rerun()
        else:
            st.error("Incorrect password")