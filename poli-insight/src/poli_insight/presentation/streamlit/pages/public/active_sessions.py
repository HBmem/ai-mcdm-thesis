import streamlit as st

from poli_insight.bootstrap import ApplicationContainer
from poli_insight.domain.sessions import Session
from poli_insight.application.session_queries import SessionFilters

def render(container: ApplicationContainer) -> None:
    with st.container():
        st.markdown(f":green[:material/android_wifi_4_bar: {0} Active Sessions  ·  Open for participation]")

    st.html("<hr style='margin-top: 0.1rem; margin-bottom: 0.1rem;'>")

    st.markdown(":primary[Public Participation · Policy Evaluation Research]")

    with st.container():
        st.markdown("#### Active :primary[Sessions]")

        st.markdown("Each session presents a real policy decision scenario. Your responses are anonymous, take 5-15 minutes, and contribute to published research on AI-assisted policy modeling. ")

        sessions = _session_search(container)
        

def _session_search(container: ApplicationContainer) -> list[Session]:
    with st.container(border=True):
        session_title = st.text_input(
            "Session Title",
            label_visibility="collapsed",
            placeholder="Search session..."
        )

        session_filters = SessionFilters(
            title=session_title
        )

        sessions = container.session_service.list_sessions(
            session_filters,
            page=1,
            page_size=10,
        )

    return sessions.items