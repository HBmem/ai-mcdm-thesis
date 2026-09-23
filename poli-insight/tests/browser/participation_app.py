"""Real participation services against a temporary DB for browser regression checks.

Run from the repo: python -m streamlit run tests/browser/participation_app.py
Open ?count=5 or ?count=7. A test participant is enrolled for each browser session;
the access parameter preserves that participant across browser reloads.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from poli_insight.application.use_cases.enroll_participant import (
    EnrollParticipantCommand,
)
from poli_insight.domain.enum import ResponseFormat
from poli_insight.presentation.streamlit.components.layout import application_shell
from poli_insight.presentation.streamlit.components.theme import render_theme
from poli_insight.presentation.streamlit.pages.public.participate import (
    _render_authenticated_workspace,
)
from tests.integration.test_participation_flow import _container, _open_questionnaire

st.set_page_config(layout="centered", page_title="Questionnaire browser check")


@st.cache_resource
def test_sessions():
    root = Path(tempfile.mkdtemp(prefix="participation-browser-"))
    container = _container(root / "participation.sqlite")
    sessions = {
        count: _open_questionnaire(
            container,
            slug=f"browser-study-{count}",
            response_format=ResponseFormat.PAIRWISE,
            consent_required=True,
            scale_count=count,
        )
        for count in (5, 7)
    }
    return container, sessions


container, sessions = test_sessions()
count = int(st.query_params.get("count", "7"))
if "access" not in st.query_params:
    session_id, group_id = sessions[count]
    enrollment = container.participation.enroll.execute(
        EnrollParticipantCommand(session_id=session_id, selected_group_id=group_id)
    )
    st.query_params["access"] = enrollment.access_token
context = SimpleNamespace(container=container, queries=container.page_queries)
render_theme()
with application_shell():
    _render_authenticated_workspace(context, st.query_params["access"])
