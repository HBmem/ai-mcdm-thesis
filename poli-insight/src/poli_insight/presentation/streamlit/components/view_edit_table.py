import streamlit as st

from typing import Any

ROWS_PER_PAGE = 10

def render(filter: dict[str, Any]):
    sessions = ""
    total_pages = max(1, (len(sessions) + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE)

    st.markdown(f":primary[Sessions ({len(sessions)})]")

    with st.container(border=True):
        table_slot = st.empty()
        page = st.pagination(num_pages=total_pages, key="sessions_pagination")
    
    start_index = (page - 1) * ROWS_PER_PAGE
    end_index = start_index + ROWS_PER_PAGE
    sessions_to_display = sessions[start_index:end_index]