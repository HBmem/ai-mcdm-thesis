from __future__ import annotations

import streamlit as st

from poli_insight.domain.enum import SessionStatus
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    format_datetime,
    metric_row,
    render_capability_notice,
    render_empty_state,
    render_page_header,
    surface,
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

    cards = metric_row(4, key="dashboard:render:0")
    cards[0].metric("Draft", snapshot.count(SessionStatus.DRAFT), border=True)
    cards[1].metric("Scheduled", snapshot.count(SessionStatus.SCHEDULED), border=True)
    cards[2].metric("Open", snapshot.count(SessionStatus.OPEN), border=True)
    cards[3].metric("Paused", snapshot.count(SessionStatus.PAUSED), border=True)
    cards = metric_row(4, key="dashboard:render:1")
    cards[0].metric("Closed", snapshot.count(SessionStatus.CLOSED), border=True)
    cards[1].metric("Canceled", snapshot.count(SessionStatus.CANCELED), border=True)
    cards[2].metric("Archived", snapshot.count(SessionStatus.ARCHIVED), border=True)
    cards[3].metric(
        "Active now",
        snapshot.count(SessionStatus.OPEN) + snapshot.count(SessionStatus.PAUSED),
        border=True,
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
        with surface(key="dashboard:render:1"):
            render_status(
                SessionStatus.PAUSED,
                detail=(
                    f"{paused_count} session{'s' if paused_count != 1 else ''} "
                    "require review before resuming or closing."
                ),
            )
    if closed_count:
        with surface(key="dashboard:render:2"):
            render_status(
                SessionStatus.CLOSED,
                detail=(
                    f"{closed_count} closed session"
                    f"{'s' if closed_count != 1 else ''} can be inspected in the "
                    "processing queue."
                ),
            )
    if not paused_count and not closed_count:
        render_empty_state(
            "All caught up",
            "No operational session items currently require attention.",
            icon=":material/check_circle:",
        )

    st.subheader("Workspace capabilities", anchor=False)
    render_capability_notice(
        "Operational read models",
        "Public session discovery and session lifecycle counts are connected.",
        available=True,
    )
    render_capability_notice(
        "Deterministic processing and reporting",
        "Validation, weights, rankings, analysis, packages, and controlled "
        "participant releases are available in the administrative workspaces.",
        available=True,
    )
