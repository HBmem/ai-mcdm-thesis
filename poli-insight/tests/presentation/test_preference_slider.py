"""Exercise scale semantics and the component's real Streamlit state protocol."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from streamlit.testing.v1 import AppTest

from poli_insight.application.queries.page_queries import ParticipationScaleOption
from poli_insight.application.response_scale_catalog import APPLICATION_RESPONSE_SCALES
from poli_insight.presentation.streamlit.components.preference_slider import (
    balanced_options,
)
from tests.presentation.test_participate import PARTICIPATION_WORKSPACE_APP


def _options(count):
    scale = next(
        scale
        for scale in APPLICATION_RESPONSE_SCALES
        if scale.response_format == "pairwise" and len(scale.values) == count
    )
    return tuple(
        ParticipationScaleOption(f"value-{i}", value.label, i, str(value.numeric_value))
        for i, value in enumerate(scale.values)
    )


@pytest.mark.parametrize("count", [5, 7])
def test_both_catalog_and_legacy_order_preserve_direction_and_ids(count):
    options = _options(count)
    for source in (options, tuple(reversed(options))):
        choices = balanced_options(source, left_name="Access", right_name="Cost")
        assert choices is not None
        assert [choice["id"] for choice in choices] == [
            option.scale_value_id for option in options
        ]
        assert choices[0]["summary"].startswith("Access is")
        assert choices[-1]["summary"].startswith("Cost is")
        assert (
            choices[count // 2]["summary"] == "Access and Cost are equally important."
        )


@pytest.mark.parametrize("bad_value", [None, "NaN", "Infinity", "-1", "0", "text", "1"])
def test_invalid_ratio_scales_fall_back_instead_of_mislabeling(bad_value):
    options = _options(5)
    options = (replace(options[0], numeric_value=bad_value), *options[1:])
    assert balanced_options(options, left_name="A", right_name="B") is None


_WORKSPACE = PARTICIPATION_WORKSPACE_APP.rsplit(
    '_render_authenticated_workspace(context, "private-resume-token")', 1
)[0]
_PAIRWISE_APP = (
    _WORKSPACE
    + """
from dataclasses import replace
import streamlit as st
from poli_insight.application.response_scale_catalog import APPLICATION_RESPONSE_SCALES
from poli_insight.presentation.streamlit.pages.public.participate import _render_pairwise

scale = next(scale for scale in APPLICATION_RESPONSE_SCALES
    if scale.response_format == "pairwise" and len(scale.values) == SCALE_COUNT)
options = tuple(ParticipationScaleOption(
    f"value-{i}", value.label, i, str(value.numeric_value)
) for i, value in enumerate(scale.values))
workspace = replace(workspace,
    response_format=ResponseFormat.PAIRWISE,
    scale_options=options,
    questions=(replace(workspace.questions[0],
        left_name="Community trust", right_name="Cost effectiveness"),),
    answers=st.session_state.get("test:saved", INITIAL_ANSWERS),
)
class RecordingSave:
    def execute(self, command):
        st.session_state["test:command"] = command
        saved = dict(workspace.answers)
        for qid in command.remove_question_definition_ids:
            saved.pop(qid, None)
        for answer in command.answers:
            saved[answer.question_definition_id] = answer.raw_value_json
        st.session_state["test:saved"] = saved
        return SimpleNamespace(submission_id="submission-1")
context.container.submissions.save_draft = RecordingSave()
_render_pairwise(context, workspace, "token")
"""
)


def _source(count, *, saved=None):
    answers = (
        {} if saved is None else {"question-1": {"selected_scale_value_id": saved}}
    )
    return _PAIRWISE_APP.replace("SCALE_COUNT", str(count)).replace(
        "INITIAL_ANSWERS", repr(answers)
    )


def _select(app, value):
    # AppTest omits v2 widgets from its state snapshot. Include the browser's
    # component state on every rerun, alongside any pending native button click.
    states = app._tree.get_widget_states()
    widget = states.widgets.add()
    widget.id = app.get("bidi_component")[0].proto.id
    widget.json_value = json.dumps({"selected": value})
    return app._run(widget_state=states)


def _button(app, label):
    return next(button for button in app.button if button.label == label)


@pytest.mark.parametrize("count", [5, 7])
def test_blank_equal_save_and_clear_round_trip(count):
    app = AppTest.from_string(_source(count)).run()
    assert not app.exception
    assert not app.select_slider
    component = app.get("bidi_component")[0]
    data = json.loads(component.proto.json)
    assert len(data["choices"]) == count
    assert data["selected"] is None
    assert _button(app, "Save and review").disabled

    _select(app, f"value-{count // 2}")
    assert not app.exception
    assert not _button(app, "Save and review").disabled
    _button(app, "Save draft").click()
    _select(app, f"value-{count // 2}")
    command = app.session_state["test:command"]
    assert command.answers[0].raw_value_json == {
        "selected_scale_value_id": f"value-{count // 2}"
    }

    _select(app, None)
    assert _button(app, "Save and review").disabled
    _button(app, "Save draft").click()
    _select(app, None)
    assert app.session_state["test:command"].answers == ()
    assert app.session_state["test:command"].remove_question_definition_ids == (
        "question-1",
    )
    assert not app.exception


@pytest.mark.parametrize("count", [5, 7])
def test_saved_answers_restore_but_do_not_overwrite_live_edits(count):
    app = AppTest.from_string(_source(count, saved="value-0")).run()
    assert not app.exception
    assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] == "value-0"
    _select(app, f"value-{count - 1}")
    _select(app, f"value-{count - 1}")
    assert (
        json.loads(app.get("bidi_component")[0].proto.json)["selected"]
        == f"value-{count - 1}"
    )
    _button(app, "Save draft").click()
    _select(app, f"value-{count - 1}")
    assert app.session_state["test:command"].answers[0].raw_value_json == {
        "selected_scale_value_id": f"value-{count - 1}"
    }
    _select(app, None)
    _select(app, None)
    assert json.loads(app.get("bidi_component")[0].proto.json)["selected"] is None
    assert not app.exception


def test_unknown_frontend_value_does_not_satisfy_required_answer():
    app = AppTest.from_string(_source(7)).run()
    _select(app, "foreign-scale-value")
    assert not app.exception
    assert _button(app, "Save and review").disabled
    _button(app, "Save draft").click()
    _select(app, "foreign-scale-value")
    assert app.session_state["test:command"].answers == ()
