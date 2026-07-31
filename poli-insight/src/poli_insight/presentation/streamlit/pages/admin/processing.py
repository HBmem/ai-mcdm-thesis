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
            title="Session Processing",
            description=(
                "Validate frozen inputs, run deterministic MCDM, inspect "
                "diagnostics, and analyze sensitivity and robustness."
            ),
        )
    )
    render_capability_notice(
        "Immutable processing runs",
        "Submission validation is in development. Run manifests, inclusion "
        "records, artifacts, and sensitivity child runs must be implemented "
        "before processing actions are enabled.",
    )
