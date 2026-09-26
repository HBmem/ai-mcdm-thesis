"""Actual processing UI/services with isolated, temporary migrated SQLite data.

Each ?case=<name> creates an independent test study; never touches the app DB.
"""

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from poli_insight.application.use_cases.close_session import CloseSessionCommand
from poli_insight.application.use_cases.create_session_configuration import (
    StakeholderGroupInput,
)
from poli_insight.application.use_cases.enroll_participant import (
    EnrollParticipantCommand,
)
from poli_insight.application.use_cases.save_submission_draft import (
    SaveSubmissionDraftCommand,
)
from poli_insight.application.use_cases.submit_response import SubmitResponseCommand
from poli_insight.domain.enum import ResponseFormat
from poli_insight.presentation.streamlit.components.layout import application_shell
from poli_insight.presentation.streamlit.navigation import _admin_pages
from poli_insight.presentation.streamlit.pages.admin import processing
from tests.integration.test_manual_reporting import ADMIN
from tests.integration.test_participation_flow import (
    _answer,
    _container,
    _open_questionnaire,
)

st.set_page_config(layout="wide", page_title="Session Processing browser check")


@st.cache_resource
def test_session(case):
    root = Path(tempfile.mkdtemp(prefix="processing-browser-"))
    container = _container(root / "processing.sqlite")
    groups = tuple(
        StakeholderGroupInput(
            group_key=key,
            name=name,
            description=name,
            allocation_units=5000,
            required=True,
        )
        for key, name in (
            ("residents", "Residents"),
            ("providers", "Service providers"),
        )
    )
    if case.startswith("single-"):
        groups = (
            StakeholderGroupInput(
                group_key="residents",
                name="Residents",
                description="Residents",
                allocation_units=10000,
                required=True,
            ),
        )
    session_id, _ = _open_questionnaire(
        container,
        slug="processing-study",
        response_format=ResponseFormat.DIRECT_RATING,
        consent_required=False,
        stakeholder_groups=groups,
    )
    public = container.page_queries.get_public_participation_session("processing-study")
    for group in public.groups:
        for index in range(3):
            enrollment = container.participation.enroll.execute(
                EnrollParticipantCommand(
                    session_id=session_id,
                    selected_group_id=group.group_id,
                    alias=f"Test {group.group_id[:6]} respondent {index + 1}",
                )
            )
            workspace = container.page_queries.get_participation_workspace(
                enrollment.participant_id
            )
            answers = tuple(
                _answer(
                    q.question_definition_id, workspace.scale_options[2].scale_value_id
                )
                for q in workspace.questions
            )
            draft = container.submissions.save_draft.execute(
                SaveSubmissionDraftCommand(
                    session_id=session_id,
                    participant_id=enrollment.participant_id,
                    actor_id=enrollment.participant_id,
                    access_token=enrollment.access_token,
                    answers=answers,
                )
            )
            container.submissions.submit.execute(
                SubmitResponseCommand(
                    submission_id=draft.submission_id,
                    session_id=session_id,
                    participant_id=enrollment.participant_id,
                    actor_id=enrollment.participant_id,
                    access_token=enrollment.access_token,
                )
            )
    container.sessions.close.execute(
        CloseSessionCommand(session_id=session_id, actor_id=ADMIN.subject)
    )
    return container, session_id


container, session_id = test_session(st.query_params.get("case", "default"))
context = SimpleNamespace(
    container=container, queries=container.page_queries, principal=ADMIN, routes={}
)
st.session_state.setdefault("processing:session_id", session_id)
st.session_state.setdefault("processing:workspace_mode", "in_progress")


def processing_page():
    with application_shell():
        processing.render(context)


# Use the production route registry, rather than copying route identifiers.
context.routes.update(
    _admin_pages(
        container=container,
        authentication=SimpleNamespace(current_principal=lambda: ADMIN),
        authorization=SimpleNamespace(can_access_admin=lambda principal: True),
        principal=ADMIN,
        routes=context.routes,
    )
)
processing_route = st.Page(processing_page, title="Session Processing", default=True)
st.navigation([processing_route, context.routes["reports"]]).run()
