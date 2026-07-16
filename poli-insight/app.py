import streamlit as st

from poli_insight.bootstrap import create_container
from poli_insight.presentation.streamlit.navigation import run_navigation

st.set_page_config(page_title="Poli Insight", layout="wide")

container = create_container()
run_navigation(container)
