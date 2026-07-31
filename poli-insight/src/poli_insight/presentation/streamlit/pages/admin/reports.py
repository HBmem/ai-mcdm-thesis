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
            eyebrow="Administration",
            title="AI Reports & Publication",
            description=(
                "Generate evidence-linked explanations, conduct human review, "
                "and publish explicit audience-specific releases."
            ),
        )
    )
    render_capability_notice(
        "Reporting and release workflow",
        "Report revisions, approvals, redacted AI adapters, and publication "
        "release manifests are scheduled after deterministic processing.",
    )
