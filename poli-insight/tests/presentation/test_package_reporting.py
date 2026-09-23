from __future__ import annotations

import inspect

from streamlit.testing.v1 import AppTest

from poli_insight.presentation.streamlit.pages.admin import package_section, reports
from poli_insight.presentation.streamlit.pages.public import published_results

REPORTS_APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace
import streamlit as st
from poli_insight.application.queries.page_queries import PageResult
from poli_insight.presentation.streamlit.auth.models import Principal
from poli_insight.presentation.streamlit.pages.admin.reports import render

package = SimpleNamespace(
    package_run_id="package-1", session_id="session-1", run_number=1,
    source_analysis_run_ids=("analysis-1",), source_roster_hash="roster-1",
    configuration_version_id="configuration-1", output_hash="a"*64,
    completed_at=datetime(2026,9,12,tzinfo=UTC),
)
class Queries:
    def list_session_scenarios(self): return ()
    def list_scenario_domains(self): return ()
    def list_processing_sessions(self, **arguments):
        st.session_state["test:queries"] = st.session_state.get("test:queries",0)+1
        item = SimpleNamespace(session_id="session-1", title="Transit priorities",
            current_roster_hash="roster-1", active_configuration_version_id="configuration-1")
        return PageResult((item,), 1, 100, 1)
class Reporting:
    admin_role="admin"
    def package_options(self, actor, session_id): return (package,)
    def workspace(self, actor, session_id, **kwargs):
        st.session_state["test:workspace"] = st.session_state.get("test:workspace",0)+1
        assert kwargs.get("include_documents") is False, "Overview must not load documents"
        return {"reports":(), "releases":()}
context = SimpleNamespace(queries=Queries(),
    container=SimpleNamespace(settings=SimpleNamespace(app_timezone="UTC"),reporting=Reporting()),
    principal=Principal("admin-1","Admin",frozenset({"admin"})))
render(context)
"""


def test_package_stage_retains_processing_but_report_workspace_has_no_legacy_exports():
    source = inspect.getsource(package_section.render_package_stage)
    assert '"Identity-linked moderator bundle"' in source
    source = inspect.getsource(reports)
    for removed in (
        "Export complete bundle",
        "Generate readable report",
        "Moderator-only participant directory",
        "_variant_workspace",
        "_participant_release_controls",
    ):
        assert removed not in source


def test_reporting_tabs_are_available_without_loading_inactive_workspaces():
    app = AppTest.from_string(REPORTS_APP).run()
    assert not app.exception
    assert tuple(t.label for t in app.tabs) == (
        "AI Analysis",
        "Report Publication",
        "LLM Configuration",
    )
    assert app.session_state["test:queries"] == 1
    assert "test:workspace" not in app.session_state
    assert not app.get("download_button")
    start = next(b for b in app.button if b.label == "Start AI analysis")
    assert start.disabled
    next(b for b in app.button if b.label == "Go to Report Publication").click().run()
    assert not app.exception
    assert app.session_state["reports:tab"] == "Report Publication"
    assert app.session_state["test:workspace"] == 1


def test_configuration_placeholder_works_without_sessions_or_report_queries():
    app = AppTest.from_string(REPORTS_APP)
    app.session_state["reports:tab"] = "LLM Configuration"
    app.run()
    assert not app.exception
    assert "test:queries" not in app.session_state
    assert "test:workspace" not in app.session_state
    assert not app.text_input
    assert any("No API keys" in c.value for c in app.caption)


def test_configuration_and_reporting_are_admin_only():
    app = AppTest.from_string(
        REPORTS_APP.replace('frozenset({"admin"})', "frozenset()")
    )
    app.session_state["reports:tab"] = "LLM Configuration"
    app.run()
    assert not app.exception
    assert any("Administrator access" in e.value for e in app.error)
    assert "test:queries" not in app.session_state


def test_participant_result_page_preserves_private_breakdown():
    source = inspect.getsource(published_results._render_private_result)
    assert '"Download my readable report"' in source
    assert "participant_access.execute" in source
    assert "Export complete bundle" not in source
