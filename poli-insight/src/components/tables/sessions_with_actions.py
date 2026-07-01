from __future__ import annotations
from typing import Any

import streamlit as st

from src.repositories.scenario_repository import get_sessions_by_filter

def render_sessions_with_actions(filter: dict[str, Any]):
    def on_more_click(show_more, idx):
        show_more[idx] = True


    def on_less_click(show_more, idx):
        show_more[idx] = False


    if "show_more" not in st.session_state:
        st.session_state["show_more"] = dict.fromkeys([1, 2, 3], False)
    show_more = st.session_state["show_more"]

    sessions = get_sessions_by_filter(filter_criteria=filter)

    st.markdown(f":primary[Sessions ({len(sessions)})]")

    # cols = st.columns()
    # fields = ["Session", "Responses", "Participants", "Deadline", "Status", "Actions"]

    cols = st.columns(2)
    fields = ["id", "content"]

    # header
    for col, field in zip(cols, fields):
        col.write("**" + field + "**")

    # rows
    for idx, row in zip ([1, 2, 3], ["test1", "test2", "test3"]):
        col1, col2 = st.columns(2)
        col1.write(str(idx))
        placeholder = col2.empty()

        if show_more[idx]:
            placeholder.button(
                "less", key=str(idx) + "_", on_click=on_less_click, args=[show_more, idx]
            )

            # do stuff
            st.write("This is some more stuff with a checkbox")
            temp = st.selectbox("Select one", ["A", "B", "C"], key=idx)
            st.write("You picked ", temp)
            st.write("---")
        else:
            placeholder.button(
                "more",
                key=idx,
                on_click=on_more_click,
                args=[show_more, idx],
                type="primary",
            )

