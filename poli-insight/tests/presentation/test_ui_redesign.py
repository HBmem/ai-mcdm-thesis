"""Behavioral checks for the shared layout and discrete questionnaire sliders."""

from __future__ import annotations

from streamlit.proto.WidgetStates_pb2 import WidgetStates
from streamlit.testing.v1 import AppTest

from tests.presentation.test_participate import PARTICIPATION_WORKSPACE_APP

# Reuse the existing public workspace fixture, with a recording draft service.
_WORKSPACE = PARTICIPATION_WORKSPACE_APP.rsplit(
    '_render_authenticated_workspace(context, "private-resume-token")', 1
)[0]
_RECORDING = """
from dataclasses import replace
import streamlit as st
from poli_insight.presentation.streamlit.pages.public.participate import (
    _render_direct, _render_pairwise, _answer_form, _required_complete,
)
class RecordingSave:
    def execute(self, command):
        st.session_state["test:command"] = command
        saved = dict(st.session_state.get("test:answers", {}))
        for qid in command.remove_question_definition_ids:
            saved.pop(qid, None)
        for answer in command.answers:
            saved[answer.question_definition_id] = answer.raw_value_json
        st.session_state["test:answers"] = saved
        return SimpleNamespace(submission_id="submission-1")
context.container.submissions.save_draft = RecordingSave()
workspace = replace(workspace, answers=st.session_state.get("test:answers", {}))
"""


def _button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def _clear_slider(app: AppTest, index: int = 0) -> AppTest:
    # AppTest.set_value(None) means "no test override" in 1.58. Send the same
    # single formatted value that the browser sends when moving to the first stop.
    states = WidgetStates()
    widget = states.widgets.add()
    widget.id = app.select_slider[index].id
    widget.string_array_value.data.append("Not answered")
    return app._run(widget_state=states)


def test_direct_sliders_preserve_empty_defaults_values_keys_and_validation():
    app = AppTest.from_string(
        _WORKSPACE + _RECORDING + '_render_direct(context, workspace, "token")'
    ).run()
    assert not app.exception
    assert app.selectbox[0].label == "Question"
    slider = app.select_slider[0]
    assert slider.key == "participate:questionnaire:participant-1:1:input:question-1"
    assert slider.value is None
    assert slider.options == ["Not answered", "Low", "High"]
    assert slider.help == "Access to public services."
    assert _button(app, "Save and review").disabled

    slider.set_value("scale-value-2").run()
    assert not _button(app, "Save and review").disabled
    _button(app, "Save draft").click().run()
    command = app.session_state["test:command"]
    assert command.answers[0].raw_value_json == {
        "selected_scale_value_id": "scale-value-2"
    }
    assert not command.remove_question_definition_ids
    assert app.select_slider[0].value == "scale-value-2"

    _clear_slider(app)
    assert app.select_slider[0].value is None
    assert (
        app.session_state["participate:questionnaire:participant-1:1:input:question-1"]
        is None
    )
    assert _button(app, "Save and review").disabled
    _button(app, "Save draft").click().run()
    command = app.session_state["test:command"]
    assert command.answers == ()
    assert command.remove_question_definition_ids == ("question-1",)
    assert not app.exception


def test_saved_and_in_memory_slider_values_are_restored_without_overwriting():
    source = (
        _WORKSPACE
        + _RECORDING
        + """
workspace = replace(workspace, answers={
    "question-1": {"selected_scale_value_id": "scale-value-2"}
})
_render_direct(context, workspace, "token")
"""
    )
    app = AppTest.from_string(source).run()
    assert app.select_slider[0].value == "scale-value-2"
    app.select_slider[0].set_value("scale-value-1").run()
    app.run()
    assert app.select_slider[0].value == "scale-value-1"
    assert not app.exception


def test_optional_question_and_single_value_scale_do_not_create_an_answer():
    source = (
        _WORKSPACE
        + _RECORDING
        + """
workspace = replace(workspace,
    questions=(replace(workspace.questions[0], required=False),),
    scale_options=(workspace.scale_options[0],),
)
_render_direct(context, workspace, "token")
"""
    )
    app = AppTest.from_string(source).run()
    assert not app.exception
    assert app.select_slider[0].value is None
    assert app.select_slider[0].options == ["Not answered", "Low"]
    assert not _button(app, "Save and review").disabled
    _button(app, "Save draft").click().run()
    assert app.session_state["test:command"].answers == ()


def test_pairwise_slider_saves_before_advancing_and_preserves_page_keys():
    source = (
        _WORKSPACE
        + _RECORDING
        + """
workspace = replace(workspace, response_format=ResponseFormat.PAIRWISE,
    questions=(
        replace(workspace.questions[0], left_name="Access", right_name="Cost"),
        replace(workspace.questions[0], question_definition_id="question-2",
                left_name="Cost", right_name="Equity"),
    ),
)
_render_pairwise(context, workspace, "token")
"""
    )
    app = AppTest.from_string(source).run()
    assert not app.exception
    assert (
        app.select_slider[0].key
        == "participate:questionnaire:participant-1:1:input:question-1"
    )
    assert app.select_slider[0].label == "Access compared with Cost"
    assert not _button(app, "Next").disabled
    app.select_slider[0].set_value("scale-value-1").run()
    _button(app, "Next").click().run()
    assert not app.exception
    assert app.session_state["participate:questionnaire:participant-1:1"].current == 1
    assert (
        app.select_slider[0].key
        == "participate:questionnaire:participant-1:1:input:question-2"
    )
    assert app.select_slider[0].value is None
    assert _button(app, "Save and review").disabled
    assert app.session_state["test:answers"]["question-1"] == {
        "selected_scale_value_id": "scale-value-1"
    }


def test_shared_shell_and_surfaces_handle_special_titles_and_distinct_keys():
    app = AppTest.from_string("""
from poli_insight.presentation.streamlit.components.layout import (
    PageHeader, application_shell, reading_width, render_page_header, surface, metric_row,
)
with application_shell(), reading_width("test"):
    render_page_header(PageHeader("A < B & C", "Readable description"))
    with surface(key="a:b"):
        for target in metric_row(3, key="test:metrics"):
            target.metric("Count", 1, border=True)
    with surface(key="a/b"):
        import streamlit as st
        st.text_input("Native control", key="unchanged-key")
""").run()
    assert not app.exception
    assert len(app.title) == 1
    assert app.title[0].value == "A < B & C"
    assert len(app.metric) == 3
    assert app.text_input[0].key == "unchanged-key"
