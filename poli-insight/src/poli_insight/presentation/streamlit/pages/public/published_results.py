import streamlit as st

from poli_insight.bootstrap import ApplicationContainer


def render(container: ApplicationContainer) -> None:
    del container
    
    st.title("Published Results")