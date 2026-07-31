from __future__ import annotations

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
            eyebrow="Reviewed releases",
            title="Published Results",
            description=(
                "Explore results that have been deliberately reviewed and "
                "released for a public audience."
            ),
        )
    )
    render_capability_notice(
        "Publication catalog",
        "The release-manifest and public-result query models are scheduled for "
        "the publication phase. Closed sessions are intentionally not shown as "
        "published results.",
    )
