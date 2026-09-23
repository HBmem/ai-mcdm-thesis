from pathlib import Path

import streamlit as st

from poli_insight.bootstrap import ApplicationContainer, create_container
from poli_insight.presentation.streamlit.components.layout import application_shell
from poli_insight.presentation.streamlit.errors import render_startup_error
from poli_insight.presentation.streamlit.navigation import run_navigation

st.set_page_config(
    page_title="Poli Insight",
    page_icon=":material/account_balance:",
    layout="wide",
    initial_sidebar_state="auto",
)


def _application_code_version() -> tuple[tuple[str, int, int], ...]:
    """Fingerprint application modules that Streamlit may hot-reload."""

    source_root = Path(__file__).resolve().parent / "src" / "poli_insight"
    return tuple(
        (
            str(path.relative_to(source_root)),
            path.stat().st_mtime_ns,
            path.stat().st_size,
        )
        for path in sorted(source_root.rglob("*.py"))
    )


@st.cache_resource(show_spinner=False, max_entries=1)
def _create_application_container(
    code_version: tuple[tuple[str, int, int], ...],
) -> ApplicationContainer:
    """Build infrastructure once for each coherent application-code version."""

    del code_version
    return create_container()


try:
    container = _create_application_container(_application_code_version())
except Exception:  # noqa: BLE001 - final startup boundary
    with application_shell():
        render_startup_error()
    st.stop()
else:
    with application_shell():
        run_navigation(container)
