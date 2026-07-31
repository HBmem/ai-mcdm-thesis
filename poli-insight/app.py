import streamlit as st

from poli_insight.bootstrap import ApplicationContainer, create_container
from poli_insight.presentation.streamlit.errors import render_startup_error
from poli_insight.presentation.streamlit.navigation import run_navigation

st.set_page_config(
    page_title="Poli Insight",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource(show_spinner=False)
def _create_application_container() -> ApplicationContainer:
    """Build process-level infrastructure once across Streamlit reruns."""

    return create_container()


try:
    container = _create_application_container()
except Exception:  # noqa: BLE001 - final startup boundary
    render_startup_error()
    st.stop()
else:
    run_navigation(container)
