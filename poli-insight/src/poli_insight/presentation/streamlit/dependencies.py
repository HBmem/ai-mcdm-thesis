from __future__ import annotations

import streamlit as st

from poli_insight.bootstrap import (
    ApplicationContainer,
    create_container,
)


@st.cache_resource(show_spinner=False)
def get_container() -> ApplicationContainer:
    """Return the shared, thread-safe application container."""

    return create_container()