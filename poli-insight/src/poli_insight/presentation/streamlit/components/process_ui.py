"""Accessible native controls shared by processing and administration."""

from __future__ import annotations

from contextlib import contextmanager

import streamlit as st

from poli_insight.presentation.streamlit.components.layout import (
    admin_surface,
    render_section_heading,
)
from poli_insight.presentation.streamlit.components.workflow import (
    STEP_TITLES,
    WorkflowState,
    workflow_key,
)


@contextmanager
def process_action_panel(
    *,
    key: str,
    title: str,
    description: str = "",
    blockers=(),
    next_step: str | None = None,
):
    with admin_surface(key=key, variant="action"):
        render_section_heading(title, level=3)
        if description:
            st.write(description)
        for blocker in blockers:
            st.warning(blocker)
        if next_step:
            st.caption(f"On success: {next_step}.")
        yield


def process_button(
    label: str,
    *,
    key: str,
    description: str = "",
    blockers=(),
    disabled=False,
    next_step=None,
    icon=":material/play_arrow:",
) -> bool:
    with process_action_panel(
        key=key,
        title=label,
        description=description,
        blockers=blockers,
        next_step=next_step,
    ):
        error = st.session_state.pop(f"{key}:error", None)
        if error:
            st.error(error)
        return st.button(
            "Begin Process",
            key=key,
            type="primary",
            help=label,
            disabled=disabled
            or bool(blockers)
            or bool(st.session_state.get(key, False)),
            width="stretch",
        )


def render_workflow_header(
    state: WorkflowState, selected: int, session_id: str
) -> None:
    render_section_heading("Session Processing Steps", level=2)
    st.html(
        f'<div role="status" aria-live="polite" aria-atomic="true"><h2 id="pi-workflow-current-step" tabindex="-1">Step {selected + 1} of 6 · {STEP_TITLES[selected]}</h2></div>'
    )
    if st.session_state.pop(workflow_key(session_id, "focus"), False):
        # Only our own stable heading is targeted; never reach into widget internals.
        st.html(
            """<script>
        requestAnimationFrame(() => {
            const heading = document.getElementById('pi-workflow-current-step');
            if (heading) {
                heading.focus({preventScroll: true});
                heading.scrollIntoView({block: 'start', behavior: 'instant'});
            }
        });
        </script>""",
            unsafe_allow_javascript=True,
        )
    st.progress(state.completed / 6, text=f"{state.completed} of 6 steps complete")

    def step_button(index, step, suffix):
        icon = "✓" if step.status == "complete" else str(index + 1)
        if st.button(
            f"{icon} · {step.title} — {step.status.title()}",
            disabled=index > state.current,
            key=workflow_key(session_id, f"step:{suffix}:{index}"),
            width="stretch",
        ):
            st.session_state[workflow_key(session_id, "viewed")] = index
            st.rerun()

    with st.container(key="pi_workflow_desktop"):
        for start in (0, 3):
            columns = st.columns(3)
            for index in range(start, start + 3):
                with columns[index - start]:
                    step_button(index, state.steps[index], "desktop")
    with st.container(key="pi_workflow_compact"):
        with st.expander("All processing steps", expanded=False):
            for index, step in enumerate(state.steps):
                step_button(index, step, "compact")
    for blocker in state.steps[selected].blockers:
        st.warning(blocker)


def render_completion_receipt(session_id: str) -> None:
    receipt = st.session_state.get(workflow_key(session_id, "receipt"))
    if not receipt:
        return
    st.info(receipt["message"], icon=":material/task_alt:")
    if st.button(
        f"View {STEP_TITLES[receipt['step']]} results",
        key=workflow_key(session_id, "receipt:view"),
    ):
        st.session_state[workflow_key(session_id, "viewed")] = receipt["step"]
        st.rerun()


def admin_action_button(label: str, *, panel_key: str, **kwargs) -> bool:
    """Keep native callback/key/confirmation semantics inside an action surface."""
    with process_action_panel(key=kwargs.get("key", panel_key), title=label):
        return st.button(label, **kwargs)


def admin_form_submit_button(label: str, *, panel_key: str, **kwargs) -> bool:
    with process_action_panel(key=kwargs.get("key", panel_key), title=label):
        kwargs.setdefault("type", "primary")
        return st.form_submit_button(label, **kwargs)


def fail_process(key: str, message: str) -> None:
    """Render the failure on a fresh pass so the processing control can retry."""
    st.session_state[f"{key}:error"] = message
    st.rerun()
