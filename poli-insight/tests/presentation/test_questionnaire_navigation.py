"""Question navigation and completion across custom-component mount lifetimes."""

import json

import pytest
from streamlit.testing.v1 import AppTest

from tests.presentation.test_preference_slider import _WORKSPACE

_APP = (
    _WORKSPACE
    + """
from dataclasses import replace
import streamlit as st
from poli_insight.application.response_scale_catalog import APPLICATION_RESPONSE_SCALES
from poli_insight.application.use_cases.save_submission_draft import SaveSubmissionDraftError
from poli_insight.presentation.streamlit.pages.public.participate import _render_questionnaire

participant = st.session_state.get("test:participant", "participant-1")
attempt = st.session_state.get("test:attempt", None)
scale = next(s for s in APPLICATION_RESPONSE_SCALES
             if s.response_format == FORMAT and len(s.values) == COUNT)
options = tuple(ParticipationScaleOption(f"value-{i}", v.label, i, str(v.numeric_value))
                for i, v in enumerate(scale.values))
question = workspace.questions[0]
workspace = replace(workspace,
    participant_id=participant, attempt_number=attempt,
    response_format=ResponseFormat(FORMAT), scale_options=options,
    answers=st.session_state.get("test:saved", {}), submission_id=None,
    questions=tuple(replace(question, question_definition_id=f"question-{i+1}",
        display_order=i, prompt=f"Compare {left} with {right}",
        left_name=left if FORMAT == "pairwise" else None,
        right_name=right if FORMAT == "pairwise" else None,
        left_description="Access <services> & community support.",
        right_description="Resources needed to provide services.",
        required=i != st.session_state.get("test:optional", -1),
    ) for i, (left, right) in enumerate([
        ("Access", "Cost"), ("Access", "Equity"), ("Cost", "Equity")
    ])),
)
class Queries:
    def get_participation_workspace(self, participant_id):
        return replace(workspace,
            answers=st.session_state.get("test:saved", {}),
            attempt_number=st.session_state.get("test:attempt", None),
            submission_id="submission-1" if "test:saved" in st.session_state else None,
            submission_status=(SubmissionStatus.SUBMITTED if st.session_state.get("test:submitted")
                               else SubmissionStatus.DRAFT),
        )
class Save:
    def execute(self, command):
        st.session_state["test:command"] = command
        if st.session_state.get("test:fail"):
            raise SaveSubmissionDraftError("Could not save. Try again.")
        saved = dict(st.session_state.get("test:saved", {}))
        for qid in command.remove_question_definition_ids:
            saved.pop(qid, None)
        for answer in command.answers:
            saved[answer.question_definition_id] = answer.raw_value_json
        st.session_state["test:saved"] = saved
        st.session_state["test:attempt"] = attempt or 1
class Submit:
    def execute(self, command):
        st.session_state["test:submitted"] = True
context.queries = Queries()
context.container.submissions.save_draft = Save()
context.container.submissions.submit = Submit()
context.container.packages = SimpleNamespace(participant_access=SimpleNamespace(available=lambda pid: False))
workspace = context.queries.get_participation_workspace(participant)
if FULL:
    _render_authenticated_workspace(context, "token")
else:
    st.session_state["test:review_ready"] = _render_questionnaire(context, workspace, "token")
"""
)


def source(count=7, *, direct=False, full=False):
    return (
        _APP.replace("COUNT", str(count))
        .replace("FORMAT", repr("direct_rating" if direct else "pairwise"))
        .replace("FULL", str(full))
    )


def button(app, label):
    return next(item for item in app.button if item.label == label)


_UNCHANGED = object()


def run(app, selected=_UNCHANGED):
    states = app._tree.get_widget_states()
    for component in app.get("bidi_component"):
        data = json.loads(component.proto.json)
        widget = states.widgets.add()
        widget.id = component.proto.id
        widget.json_value = json.dumps(
            {"selected": data["selected"] if selected is _UNCHANGED else selected}
        )
    app._run(widget_state=states)
    assert not app.exception
    return app


def click(app, label):
    button(app, label).click()
    return run(app)


def current(app):
    return app.selectbox[0].value


@pytest.mark.parametrize("count", [5, 7])
def test_navigation_skips_revisits_and_checks_all_questions(count):
    app = AppTest.from_string(source(count)).run()
    assert not app.exception
    assert current(app) == 0
    assert button(app, "Previous").disabled
    assert not button(app, "Next").disabled
    data = json.loads(app.get("bidi_component")[0].proto.json)
    assert data["left_description"] == "Access <services> & community support."
    assert data["right_description"] == "Resources needed to provide services."
    click(app, "Next")  # unanswered is allowed; first save creates attempt one
    assert current(app) == 1
    assert app.session_state["test:attempt"] == 1
    run(app, "value-0")
    click(app, "Next")
    assert current(app) == 2
    run(app, f"value-{count - 1}")
    assert button(app, "Next").disabled
    assert button(app, "Save and review").disabled  # first answer still missing
    app.selectbox[0].select(0)
    run(app)
    assert current(app) == 0
    assert "question-3" in app.session_state["test:saved"]
    assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] is None
    run(app, f"value-{count // 2}")
    assert not button(app, "Save and review").disabled
    click(app, "Next")
    assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] == "value-0"
    run(app, None)
    assert button(app, "Save and review").disabled
    click(app, "Previous")
    assert "question-2" not in app.session_state["test:saved"]
    click(app, "Next")
    assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] is None
    run(app, "value-1")
    click(app, "Save and review")
    assert app.session_state["test:review_ready"]
    assert len(app.session_state["test:saved"]) == 3


@pytest.mark.parametrize("navigation", ["Next", "selector", "Save and review"])
def test_failed_saves_keep_position_and_edits(navigation):
    app = AppTest.from_string(source()).run()
    app.session_state["test:fail"] = True
    run(app, "value-0")
    if navigation == "selector":
        app.selectbox[0].select(2)
        run(app)
    elif navigation == "Save and review":
        # Fill the remaining answers in the persistent draft for this save failure.
        draft = app.session_state["participate:questionnaire:participant-1:1"]
        draft.answers.update({"question-2": "value-0", "question-3": "value-0"})
        run(app)
        click(app, navigation)
    else:
        click(app, navigation)
    assert current(app) == 0
    assert app.error[0].value == "Could not save. Try again."
    assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] == "value-0"
    app.session_state["test:fail"] = False
    click(app, "Next")
    assert current(app) == 1
    assert (
        app.session_state["test:saved"]["question-1"]["selected_scale_value_id"]
        == "value-0"
    )


def test_resume_chooses_first_missing_and_new_participants_and_attempts_are_isolated():
    app = AppTest.from_string(source())
    app.session_state["test:saved"] = {
        "question-1": {"selected_scale_value_id": "value-0"}
    }
    app.run()
    assert current(app) == 1
    run(app, "value-2")
    # A different participant and a new attempt both start from their saved answers.
    for key, value in [("test:participant", "participant-2"), ("test:attempt", 2)]:
        app.session_state[key] = value
        app.session_state["test:saved"] = {}
        run(app)
        assert current(app) == 0
        assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] is None


@pytest.mark.parametrize("count", [5, 7])
def test_direct_rating_uses_same_navigation_with_optional_questions(count):
    app = AppTest.from_string(source(count, direct=True))
    app.session_state["test:optional"] = 1
    app.run()
    app.select_slider[0].set_value("value-0").run()
    click(app, "Next")
    click(app, "Next")
    assert button(app, "Save and review").disabled
    app.select_slider[0].set_value("value-1").run()
    assert not button(app, "Save and review").disabled
    click(app, "Previous")
    assert app.select_slider[0].value is None
    click(app, "Previous")
    assert app.select_slider[0].value == "value-0"
    click(app, "Save and review")
    assert app.session_state["test:review_ready"]


@pytest.mark.parametrize("count", [5, 7])
def test_active_wizard_steps_review_edit_and_submit(count):
    app = AppTest.from_string(source(count, full=True)).run()
    assert not app.get("bidi_component")  # questionnaire is not mounted in consent
    assert not app.dataframe  # review is not rendered either
    click(app, "Continue to questionnaire")
    for i in range(3):
        run(app, f"value-{i}")
        if i < 2:
            click(app, "Next")
    click(app, "Save and review")
    app.run()  # Remove AppTest's stale elements from the interrupted navigation run.
    assert app.dataframe
    assert not app.get("bidi_component")
    click(app, "Edit answers")
    assert current(app) == 2
    run(app, None)
    assert button(app, "Save and review").disabled
    run(app, "value-1")
    click(app, "Save and review")
    assert button(app, "Submit questionnaire").disabled
    app.checkbox[0].check().run()
    click(app, "Submit questionnaire")
    assert app.session_state["test:submitted"]
    assert any("submitted successfully" in item.value for item in app.success)


def test_review_guard_rejects_invalid_saved_answers():
    app = AppTest.from_string(source(full=True))
    app.session_state["_steps_state_participation:participant-1:1"] = 2
    app.session_state["test:saved"] = {
        f"question-{i}": {"selected_scale_value_id": "unknown-value"}
        for i in range(1, 4)
    }
    app.run()
    assert not app.exception
    assert app.warning
    app.checkbox[0].check().run()
    assert button(app, "Submit questionnaire").disabled
