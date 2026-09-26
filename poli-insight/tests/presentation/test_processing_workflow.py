"""Coherent lineage and navigation behavior, independent of presentation layout."""

from dataclasses import replace
from types import SimpleNamespace as NS

import pandas as pd
from streamlit.testing.v1 import AppTest

from poli_insight.application.queries.page_queries import SessionValidationOverview
from poli_insight.domain.enum import ArtifactType, RunStatus, SessionStatus
from poli_insight.presentation.streamlit.components.charts import (
    ChartSpec,
    chart_data,
    vega_spec,
)
from poli_insight.presentation.streamlit.components.workflow import resolve_workflow
from tests.presentation.test_analysis_section import ANALYSIS_APP


def evidence():
    overview = SessionValidationOverview(
        session_id="session",
        session_status=SessionStatus.CLOSED,
        has_active_configuration=True,
        effective_submitted_count=3,
        unvalidated_count=0,
        active_count=0,
        valid_count=3,
        warned_count=0,
        invalid_count=0,
        error_count=0,
        warning_decisions_required=0,
        latest_batch_id="weight",
        latest_batch_number=1,
        latest_batch_status=RunStatus.SUCCEEDED,
        latest_batch_created_at=None,
        latest_batch_roster_hash="roster",
        current_roster_hash="roster",
        roster_is_current=True,
    )
    weighting = NS(processing_run_id="weight", status=RunStatus.SUCCEEDED)
    ranking = NS(
        ranking_run_id="rank",
        source_processing_run_id="weight",
        roster_hash="roster",
        status=RunStatus.SUCCEEDED,
    )
    analysis = NS(
        analysis_run_id="analysis",
        source_ranking_run_id="rank",
        status=RunStatus.SUCCEEDED,
        artifacts=(
            NS(
                artifact_type=ArtifactType.STRUCTURED_RESULT,
                content_json={"summary": {"evaluated_count": 3}},
            ),
        ),
    )
    package = NS(
        package_run_id="package",
        source_processing_run_id="weight",
        source_ranking_run_id="rank",
        source_analysis_run_ids=("analysis",),
        status=RunStatus.SUCCEEDED,
    )
    return overview, (weighting,), (ranking,), (analysis,), (package,)


def test_each_step_reconstructs_from_current_persisted_evidence():
    overview, weights, rankings, analyses, packages = evidence()
    assert (
        resolve_workflow(replace(overview, has_active_configuration=False)).current == 0
    )
    assert (
        resolve_workflow(
            replace(overview, latest_batch_id=None, unvalidated_count=3)
        ).current
        == 1
    )
    awaiting = (NS(processing_run_id="weight", status=RunStatus.AWAITING_REVIEW),)
    assert resolve_workflow(overview, awaiting).current == 2
    assert resolve_workflow(overview, weights).current == 3
    assert resolve_workflow(overview, weights, rankings).current == 4
    assert resolve_workflow(overview, weights, rankings, analyses).current == 5
    complete = resolve_workflow(overview, weights, rankings, analyses, packages)
    assert complete.completed == 6
    assert complete.package_id == "package"


def test_stale_roster_and_new_validation_cannot_inherit_old_completion():
    overview, weights, rankings, analyses, packages = evidence()
    stale = resolve_workflow(
        replace(overview, roster_is_current=False, current_roster_hash="new"),
        weights,
        rankings,
        analyses,
        packages,
    )
    assert stale.current == 1
    assert stale.completed == 1
    assert stale.steps[3].status == "stale"
    new = NS(processing_run_id="new-weight", status=RunStatus.AWAITING_REVIEW)
    fresh = resolve_workflow(
        replace(overview, latest_batch_id="new-weight"),
        (new, *weights),
        rankings,
        analyses,
        packages,
    )
    assert fresh.current == 2
    assert fresh.package_id is None
    assert (
        resolve_workflow(
            overview, weights, rankings, analyses, packages, scenario_ready=False
        ).current
        == 0
    )


def test_required_reviews_and_no_evaluable_cases_stop_progress():
    overview, weights, rankings, analyses, packages = evidence()
    state = resolve_workflow(
        replace(overview, warning_decisions_required=1),
        weights,
        rankings,
        analyses,
        packages,
    )
    assert state.current == 1
    assert state.steps[1].status == "needs review"
    analyses[0].artifacts[0].content_json["summary"]["evaluated_count"] = 0
    state = resolve_workflow(overview, weights, rankings, analyses, packages)
    assert state.current == 4
    assert state.steps[4].status == "needs review"
    assert state.package_id is None


def test_package_must_match_the_current_analysis_and_weighting_lineage():
    overview, weights, rankings, analyses, packages = evidence()
    packages[0].source_analysis_run_ids = ("historical-analysis",)
    assert (
        resolve_workflow(overview, weights, rankings, analyses, packages).completed == 5
    )
    rankings[0].source_processing_run_id = "historical-weight"
    assert (
        resolve_workflow(overview, weights, rankings, analyses, packages).current == 3
    )


def test_pending_navigation_is_scoped_and_does_not_move_historical_or_manual_views():
    source = """
import streamlit as st
from poli_insight.presentation.streamlit.components.workflow import *
from tests.presentation.test_processing_workflow import evidence
state = resolve_workflow(*evidence())
if st.button("Complete historical ranking"):
    record_completion("session", 3, "Historical result", evidence_id="old")
if st.button("Complete current ranking"):
    record_completion("session", 3, "Current result", evidence_id="rank")
apply_pending_navigation("session", state)
st.write(st.session_state.get(workflow_key("session", "viewed")))
"""
    app = AppTest.from_string(source).run()
    app.button[0].click().run()
    assert app.session_state["processing:workflow:session:viewed"] == 3
    app.button[1].click().run()
    assert app.session_state["processing:workflow:session:viewed"] == 4
    app.session_state["processing:workflow:session:viewed"] = 1
    app.run()
    assert app.session_state["processing:workflow:session:viewed"] == 1
    assert "processing:workflow:other:viewed" not in app.session_state


def test_percentage_point_inputs_convert_once_to_domain_weight_units():
    app = AppTest.from_string(ANALYSIS_APP).run()
    app.checkbox[0].check().run()
    next(item for item in app.selectbox if item.label == "Range preset").select(
        "Advanced"
    ).run()
    assert [item.value for item in app.number_input] == [20.0, 20.0, 1.0]
    source = """
import streamlit as st
from poli_insight.presentation.streamlit.pages.admin.analysis_section import _perturbation_configuration
values = _perturbation_configuration("points", True)
st.session_state["result"] = values
"""
    app = AppTest.from_string(source).run()
    app.selectbox[0].select("Advanced").run()
    app.number_input[0].set_value(5.0).run()
    assert str(app.session_state["result"]["lower_delta"]) == "0.05"
    assert str(app.session_state["result"]["step"]) == "0.01"


def test_chart_contract_keeps_missing_values_and_explicit_units():
    spec = ChartSpec(
        "Weights",
        "Criterion",
        "Normalized weight (%)",
        "Group A",
        "Relative importance",
        horizontal=True,
        scale="percent",
    )
    data = chart_data(
        pd.Series({"Cost": 0.25, "Access": None, "Other": 0}, name="Weight"), spec
    )
    assert data["Value"].iloc[0] == 25
    assert pd.isna(data["Value"].iloc[1])
    assert data["Value"].iloc[2] == 0
    chart = vega_spec(spec, ["Weight"])
    assert chart["encoding"]["x"]["axis"]["title"] == "Normalized weight (%)"
    assert chart["encoding"]["x"]["scale"]["domain"] == [0, 100]
    assert chart["layer"][1]["transform"][0]["filter"] == "datum.Value === 0"


def test_analysis_batch_requires_each_selected_test_to_have_evaluated_evidence():
    from poli_insight.application.use_cases.run_selected_analyses import AnalysisOutcome
    from poli_insight.domain.enum import AnalysisMethod

    for status, evaluated, advance in (
        (RunStatus.SUCCEEDED, 2, True),
        (RunStatus.SUCCEEDED, 0, False),
        (RunStatus.FAILED, 0, False),
    ):
        source = """
import streamlit as st
from types import SimpleNamespace
from poli_insight.presentation.streamlit.pages.admin.analysis_section import _execute
from poli_insight.domain.enum import AnalysisMethod
class Executor:
    def execute(self, command, on_progress):
        return SimpleNamespace(outcomes=(st.session_state["outcome"],))
context = SimpleNamespace(principal=SimpleNamespace(subject="admin"), container=SimpleNamespace(analysis=SimpleNamespace(run_selected=Executor())))
if st.button("Execute"):
    _execute(context, "session", "rank", (AnalysisMethod.CRITERION_REMOVAL,), {})
"""
        app = AppTest.from_string(source)
        app.session_state["outcome"] = AnalysisOutcome(
            AnalysisMethod.CRITERION_REMOVAL, "analysis", 1, status, False, evaluated, 0
        )
        app.run().button[0].click().run()
        assert not app.exception
        assert (
            app.session_state["processing:workflow:session:pending"]["advance"]
            == advance
        )
        assert app.session_state["processing:analysis_feedback:session"]["empty"] == (
            evaluated == 0
        )


def test_package_completion_opens_registered_reports_route_with_session_selected(
    tmp_path,
):
    from tests.integration.test_manual_reporting import seed_reporting

    container, session_id, _, _ = seed_reporting(tmp_path / "route-regression.sqlite")
    source = f"""
import streamlit as st
from types import SimpleNamespace
from poli_insight.bootstrap import create_container
from poli_insight.config import Settings
from poli_insight.presentation.streamlit.navigation import _admin_pages
from poli_insight.presentation.streamlit.pages.admin import processing
from tests.integration.test_manual_reporting import ADMIN
container = create_container(Settings(database_url={container.settings.database_url!r}, app_timezone="UTC"))
routes = {{}}
context = SimpleNamespace(container=container, queries=container.page_queries, principal=ADMIN, routes=routes)
routes.update(_admin_pages(container=container,
    authentication=SimpleNamespace(current_principal=lambda: ADMIN),
    authorization=SimpleNamespace(can_access_admin=lambda principal: True),
    principal=ADMIN, routes=routes))
def process_page():
    processing.render(context)
st.session_state.setdefault("processing:session_id", {session_id!r})
st.session_state.setdefault("processing:workspace_mode", "processed")
st.navigation([st.Page(process_page, title="Processing", default=True), routes["reports"]]).run()
"""
    app = AppTest.from_string(source, default_timeout=30).run()
    assert not app.exception
    assert any("All 6 steps complete" in item.value for item in app.success)
    next(
        button for button in app.button if button.label == "Open Reports & Publication"
    ).click().run()
    assert not app.exception
    assert not app.error
    assert any(title.value == "Reports & Publication" for title in app.title)
    assert app.session_state["reports:session_id"] == session_id


def test_newer_failed_ranking_does_not_inherit_older_success():
    overview, weights, rankings, analyses, packages = evidence()
    failed = NS(
        ranking_run_id="failed",
        source_processing_run_id="weight",
        roster_hash="roster",
        status=RunStatus.FAILED,
    )
    state = resolve_workflow(overview, weights, (failed, *rankings), analyses, packages)
    assert state.current == 3
    assert state.steps[3].status == "failed"
    assert state.ranking_id is None
