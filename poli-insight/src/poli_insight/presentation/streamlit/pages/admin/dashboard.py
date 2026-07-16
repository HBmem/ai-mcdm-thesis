import streamlit as st

from poli_insight.bootstrap import ApplicationContainer


def render(container: ApplicationContainer) -> None:
    st.title("Dashboard")