from __future__ import annotations

import streamlit as st

from poli_insight.domain.enum import SessionStatus
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    render_capability_notice,
    render_page_header,
)
from poli_insight.presentation.streamlit.components.status import render_status
from poli_insight.presentation.streamlit.context import PageContext


def render(context: PageContext) -> None:
    render_page_header(
        PageHeader(
            eyebrow="Administration",
            title="Admin Dashboard",
            description=(
                "Monitor the operational session lifecycle and move directly to "
                "the next administrative task."
            ),
        )
    )
    snapshot = context.queries.get_admin_dashboard()

    cards = st.columns(4)
    cards[0].metric("Draft", snapshot.count(SessionStatus.DRAFT))
    cards[1].metric("Scheduled", snapshot.count(SessionStatus.SCHEDULED))
    cards[2].metric("Open", snapshot.count(SessionStatus.OPEN))
    cards[3].metric("Paused", snapshot.count(SessionStatus.PAUSED))
    cards = st.columns(4)
    cards[0].metric("Closed", snapshot.count(SessionStatus.CLOSED))
    cards[1].metric("Canceled", snapshot.count(SessionStatus.CANCELED))
    cards[2].metric("Archived", snapshot.count(SessionStatus.ARCHIVED))
    cards[3].metric(
        "Active now",
        snapshot.count(SessionStatus.OPEN)
        + snapshot.count(SessionStatus.PAUSED),
    )
    st.caption(
        "Generated "
        + format_datetime(
            snapshot.generated_at,
            timezone_name=context.container.settings.app_timezone,
        )
    )

    st.subheader("Needs attention", anchor=False)
    paused_count = snapshot.count(SessionStatus.PAUSED)
    closed_count = snapshot.count(SessionStatus.CLOSED)
    if paused_count:
        with st.container(border=True):
            render_status(
                SessionStatus.PAUSED,
                detail=(
                    f"{paused_count} session{'s' if paused_count != 1 else ''} "
                    "require review before resuming or closing."
                ),
            )
    if closed_count:
        with st.container(border=True):
            render_status(
                SessionStatus.CLOSED,
                detail=(
                    f"{closed_count} closed session"
                    f"{'s' if closed_count != 1 else ''} will appear in the "
                    "processing queue when run models are implemented."
                ),
            )
    if not paused_count and not closed_count:
        st.success(
            "No operational session items currently require attention.",
            icon=":material/check_circle:",
        )

    st.subheader("Foundation capability status", anchor=False)
    render_capability_notice(
        "Operational read models",
        "Public session discovery and session lifecycle counts are connected.",
        available=True,
    )
    render_capability_notice(
        "Validation, processing, reports, and publication",
        "Their independent read models will be connected in their scheduled "
        "implementation phases.",
    )
