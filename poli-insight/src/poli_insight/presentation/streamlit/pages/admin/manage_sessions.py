from __future__ import annotations

import streamlit as st

from poli_insight.presentation.streamlit.components.layout import (
    PageHeader,
    render_capability_notice,
    render_page_header,
)
from poli_insight.presentation.streamlit.context import PageContext


def render(context: PageContext) -> None:
    del context
    render_page_header(
        PageHeader(
            eyebrow="Administration",
            title="Manage Sessions",
            description=(
                "Create sessions from immutable scenario snapshots and manage "
                "their configuration, lifecycle, participants, and submissions."
            ),
        )
    )

    tabs = st.tabs(("Sessions", "Scenario Library", "Imports", "Audit"))
    with tabs[0]:
        render_capability_notice(
            "Session workspace",
            "Command use cases exist for create, configure, open, and close. A "
            "paginated session-list read model and remaining lifecycle commands "
            "are required before controls are enabled.",
        )
    with tabs[1]:
        render_capability_notice(
            "Scenario Library",
            "Scenario import exists. The next slice will add the snapshot catalog, "
            "preview projection, and import UI.",
        )
    with tabs[2]:
        render_capability_notice(
            "Previewable imports",
            "Participant and submission imports require dry-run, idempotency, and "
            "audit application services before upload controls are enabled.",
        )
    with tabs[3]:
        render_capability_notice(
            "Audit timeline",
            "Audit persistence exists; a disclosure-safe page query is still "
            "required.",
        )
