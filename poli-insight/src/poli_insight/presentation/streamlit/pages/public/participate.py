from __future__ import annotations

import streamlit as st

from poli_insight.application.queries.page_queries import PublicSessionSummary
from poli_insight.domain.enum import AccessCodeMode, EnrollmentMode
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    render_empty_state,
    render_page_header,
)
from poli_insight.presentation.streamlit.context import PageContext


_SEARCH_KEY = "participate:search"


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Public participation",
            title="Participate",
            description=(
                "Browse sessions open to the public. Invitation-only and "
                "unlisted sessions are opened from the invitation link supplied "
                "by the researcher."
            ),
        )
    )

    with st.container(border=True):
        st.subheader("Have an invitation?", anchor=False)
        st.write(
            "Open the invitation link you received. Access codes are verified "
            "only after the session has been identified."
        )

    st.subheader("Open public sessions", anchor=False)
    with st.form("participate:search-form"):
        search = st.text_input(
            "Search sessions",
            value=st.session_state.get(_SEARCH_KEY, ""),
            placeholder="Search by session title",
        )
        submitted = st.form_submit_button(
            "Search",
            icon=":material/search:",
        )
    if submitted:
        st.session_state[_SEARCH_KEY] = search.strip()

    result = context.queries.list_open_public_sessions(
        search=st.session_state.get(_SEARCH_KEY) or None,
    )
    if not result.items:
        render_empty_state(
            "No matching sessions are open",
            "Try a different search or return later. Unlisted sessions never "
            "appear in this catalog.",
            icon=":material/event_busy:",
        )
        return

    st.caption(f"{result.total} open session{'s' if result.total != 1 else ''}")
    for session in result.items:
        _render_session_card(
            session,
            timezone_name=context.container.settings.app_timezone,
        )


def _render_session_card(
    session: PublicSessionSummary,
    *,
    timezone_name: str,
) -> None:
    with st.container(border=True):
        st.subheader(session.title, anchor=False)
        if session.description:
            st.write(session.description)
        columns = st.columns(2)
        columns[0].caption(
            "Closes: "
            + format_datetime(
                session.closes_at,
                timezone_name=timezone_name,
                empty="No closing time listed",
            )
        )
        columns[1].caption(_access_label(session))
        st.button(
            "Participation workspace coming next",
            key=f"participate:session:{session.session_id}",
            icon=":material/arrow_forward:",
            disabled=True,
            help=(
                "The enrollment and questionnaire flow is part of the next "
                "implementation phase."
            ),
        )


def _access_label(session: PublicSessionSummary) -> str:
    if session.enrollment_mode is EnrollmentMode.INVITATION_ONLY:
        return "Access: invitation required"
    if session.access_code_mode is AccessCodeMode.SHARED_SESSION_CODE:
        return "Access: session code required"
    return "Access: open enrollment"
