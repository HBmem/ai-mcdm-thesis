"""Real Streamlit forms backed by the manual-report service and database."""

import pytest
from streamlit.testing.v1 import AppTest

from tests.integration.test_manual_reporting import (
    ADMIN,
    approve,
    complete_revision,
    study,  # noqa: F401
)
from tests.presentation.test_package_reporting import REPORTS_APP


@pytest.fixture(autouse=True)
def stateful_tabs(monkeypatch):
    # Streamlit 1.58 AppTest omits tab-container state from browser events.
    # Send the same selected label that the real frontend sends on form submit.
    from streamlit.proto.WidgetStates_pb2 import WidgetState
    from streamlit.testing.v1 import element_tree

    original = element_tree.get_widget_state

    def widget_state(node):
        if node.type == "tab_container" and node.proto.tab_container.id:
            return WidgetState(
                id=node.proto.tab_container.id,
                string_value=node.root._runner.session_state["reports:tab"],
            )
        return original(node)

    monkeypatch.setattr(element_tree, "get_widget_state", widget_state)


def _app(container, *, public=False, release_id=None, access=None):
    source = f"""
from types import SimpleNamespace
import streamlit as st
from poli_insight.bootstrap import create_container
from poli_insight.config import Settings
from poli_insight.presentation.streamlit.auth.models import Principal
from poli_insight.presentation.streamlit.pages.admin import reports
from poli_insight.presentation.streamlit.pages.public import published_results
container = create_container(Settings(database_url={container.settings.database_url!r}, app_timezone="UTC"))
context = SimpleNamespace(container=container, queries=container.page_queries,
    principal=Principal("report-admin", "Moderator", frozenset({{"admin"}})), routes={{}})
{"published_results" if public else "reports"}.render(context)
"""
    app = AppTest.from_string(source, default_timeout=20)
    if release_id:
        app.query_params["report"] = release_id
    if access:
        app.query_params["access"] = access
    return app.run()


def _button(app, label):
    return next(button for button in app.button if button.label == label)


def test_manual_editor_concurrent_sessions_and_public_private_views(study):  # noqa: F811
    container, _, package_id, enrolled = study
    report = container.reporting.create_report(
        ADMIN, package_run_id=package_id, title="UI report"
    )
    revision = complete_revision(container.reporting, report)
    first = _app(container)
    second = _app(container)
    assert not first.exception and not second.exception
    assert tuple(tab.label for tab in first.tabs) == (
        "AI Analysis",
        "Report Publication",
        "LLM Configuration",
    )
    assert not first.text_area and not second.text_area
    for app in (first, second):
        _button(app, "Go to Report Publication").click().run()
        assert not app.exception
        assert not app.text_area
        _button(app, "Edit report").click().run()
        assert not app.exception
    next(
        field for field in first.text_area if field.label == "Executive summary"
    ).set_value("New summary from first editor.")
    next(
        field for field in first.text_input if field.label == "Change summary"
    ).set_value("Update summary")
    _button(first, "Save new draft revision").click().run()
    assert not first.exception
    next(
        field for field in second.text_area if field.label == "Executive summary"
    ).set_value("Old editor overwrite attempt.")
    next(
        field for field in second.text_input if field.label == "Change summary"
    ).set_value("Stale edit")
    _button(second, "Save new draft revision").click().run()
    assert not second.exception
    assert any("Reload before saving" in error.value for error in second.error)
    latest = container.reporting.history(ADMIN, report.report_id)["revisions"][0]
    assert latest.sections["Executive summary"] == "New summary from first editor."
    assert latest.parent_revision_id == revision.revision_id
    approve(container.reporting, latest)
    public = container.reporting.publish(
        ADMIN, revision_id=latest.revision_id, audience="public"
    )
    container.reporting.publish(
        ADMIN, revision_id=latest.revision_id, audience="participant"
    )
    catalog = _app(container, public=True)
    assert not catalog.exception
    assert any(item.value == "UI report" for item in catalog.subheader)
    public_view = _app(container, public=True, release_id=public.release_id)
    assert not public_view.exception
    assert "Private respondent" not in "\n".join(
        item.value for item in public_view.text
    )
    private_view = _app(container, public=True, access=enrolled[0].access_token)
    assert not private_view.exception
    assert any(item.value == "Shared session report" for item in private_view.subheader)
    container.reporting.withdraw(
        ADMIN, release_id=public.release_id, reason="Withdrawn"
    )
    unavailable = _app(container, public=True, release_id=public.release_id)
    assert not unavailable.exception
    assert any("unavailable" in warning.value for warning in unavailable.warning)


def test_session_search_can_reach_beyond_first_hundred():
    source = REPORTS_APP.replace(
        'title="Transit priorities",', "title=f\"Session page {arguments['page']}\","
    )
    source = source.replace(
        "return PageResult((item,), 1, 100, 1)",
        "return PageResult((item,), arguments['page'], arguments['page_size'], 140)",
    )
    app = AppTest.from_string(source, default_timeout=15).run()
    assert not app.exception
    next(
        field for field in app.number_input if field.label == "Session search page"
    ).set_value(6).run()
    assert not app.exception
    assert any(
        "Session page 6" in field.options
        for field in app.selectbox
        if field.label == "Session"
    )


def test_empty_search_has_no_editor_exception():
    source = REPORTS_APP.replace(
        "return PageResult((item,), 1, 100, 1)", "return PageResult((), 1, 20, 0)"
    )
    app = AppTest.from_string(source, default_timeout=15).run()
    assert not app.exception
    assert len(app.tabs) == 3
    assert not app.text_area


def test_report_actions_open_focused_dialogs(study):  # noqa: F811
    container, _, package_id, _ = study
    report = container.reporting.create_report(
        ADMIN, package_run_id=package_id, title="Dialog report"
    )
    revision = complete_revision(container.reporting, report)
    app = _app(container)
    _button(app, "Go to Report Publication").click().run()
    assert not app.exception
    assert not app.get("download_button")
    _button(app, "Review revision").click().run()
    assert not app.exception
    assert any(
        "acknowledgement" in item.value.lower() or "review" in item.value.lower()
        for item in [*app.markdown, *app.caption]
    )
    assert any(button.label == "Submit for review" for button in app.button)
    # A fresh browser session verifies export generation is requested explicitly.
    app = _app(container)
    _button(app, "Go to Report Publication").click().run()
    _button(app, "Export report").click().run()
    assert not app.exception
    assert {item.proto.label for item in app.get("download_button")} == {
        "Export report HTML",
        "Export deterministic audit report HTML",
        "Export report and evidence",
    }
    assert (
        container.reporting.history(ADMIN, report.report_id)["revisions"][0] == revision
    )
