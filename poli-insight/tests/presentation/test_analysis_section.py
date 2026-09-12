from __future__ import annotations

import inspect

from streamlit.testing.v1 import AppTest

from poli_insight.presentation.streamlit.pages.admin import analysis_section

ANALYSIS_APP = r"""
from datetime import UTC, datetime
from types import SimpleNamespace

from poli_insight.domain.enum import RunStatus
from poli_insight.presentation.streamlit.pages.admin.analysis_section import render_analysis_stage


class History:
    def execute(self, session_id):
        return ()


source = SimpleNamespace(
    processing_run_id="processing-1",
    matrices=(
        SimpleNamespace(level="stakeholder_group", stakeholder_group_id="group-1", criterion_ids=("cost", "access")),
        SimpleNamespace(level="session", stakeholder_group_id=None, criterion_ids=("cost", "access")),
    ),
    submissions=(
        SimpleNamespace(inclusion_status=SimpleNamespace(value="included")),
        SimpleNamespace(inclusion_status=SimpleNamespace(value="included")),
    ),
)
ranking = SimpleNamespace(
    ranking_run_id="ranking-1",
    source_processing_run_id="processing-1",
    status=RunStatus.SUCCEEDED,
    run_number=3,
    algorithm_implementation_id="TOPSIS 1.0",
    completed_at=datetime(2026, 9, 8, tzinfo=UTC),
    output_hash="a" * 64,
    results=(SimpleNamespace(level="session", alternatives=(1, 2, 3)),),
)
context = SimpleNamespace(
    container=SimpleNamespace(
        settings=SimpleNamespace(app_timezone="UTC"),
        analysis=SimpleNamespace(run_selected=SimpleNamespace(), list_runs=History())
    ),
    principal=SimpleNamespace(subject="admin-1"),
    queries=SimpleNamespace(),
)
detail = SimpleNamespace(summary=SimpleNamespace(session_id="session-1"))
render_analysis_stage(context, detail, (source,), (ranking,), read_only=False)
"""

ANALYSIS_RESULTS_APP = r"""
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace

import streamlit as st

from poli_insight.application.queries.page_queries import (
    AnalysisCaseView,
    AnalysisLevelSummaryView,
    AnalysisScopeView,
    PageResult,
)
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    ArtifactType,
    RunStatus,
)
from poli_insight.presentation.streamlit.pages.admin.analysis_section import render_analysis_stage

card_selector_module = importlib.import_module("streamlit_extras.card_selector")
card_selector_module._CARD_SELECTOR_COMPONENT = lambda **arguments: None
st.session_state["processing:analysis_result_level:analysis-1"] = {
    "selected": [SELECTED_LEVEL]
}

now = datetime(2026, 9, 9, tzinfo=UTC)
source = SimpleNamespace(
    processing_run_id="processing-1",
    matrices=(
        SimpleNamespace(level="stakeholder_group", stakeholder_group_id="group-1", criterion_ids=("cost", "access")),
        SimpleNamespace(level="session", stakeholder_group_id=None, criterion_ids=("cost", "access")),
    ),
    submissions=(
        SimpleNamespace(inclusion_status=SimpleNamespace(value="included")),
    ),
)
ranking = SimpleNamespace(
    ranking_run_id="ranking-1",
    source_processing_run_id="processing-1",
    status=RunStatus.SUCCEEDED,
    run_number=3,
    algorithm_implementation_id="TOPSIS 1.0",
    completed_at=now,
    output_hash="a" * 64,
    results=(SimpleNamespace(level="session", alternatives=(1, 2, 3)),),
)
analysis = SimpleNamespace(
    analysis_run_id="analysis-1",
    source_processing_run_id="processing-1",
    source_ranking_run_id="ranking-1",
    method=AnalysisMethod.PARTICIPANT_INFLUENCE,
    status=RunStatus.SUCCEEDED,
    run_number=1,
    failure_detail=None,
    input_hash="b" * 64,
    output_hash="c" * 64,
    parameter_json={},
    environment_json={},
    created_at=now,
    completed_at=now,
    correlation_id="correlation-1",
    artifacts=(
        SimpleNamespace(
            artifact_type=ArtifactType.STRUCTURED_RESULT,
            content_json={
                "summary": {
                    "evaluated_count": 1,
                    "not_evaluable_count": 0,
                    "top_set_change_count": 1,
                    "strict_reversal_count": 0,
                    "instability_detected": True,
                }
            },
        ),
    ),
)


class History:
    def execute(self, session_id):
        return (analysis,)


class Queries:
    def list_analysis_scopes(self, analysis_run_id):
        return (AnalysisScopeView("participant", "group-1", "Community"),)

    def summarize_analysis_level(self, analysis_run_id, **arguments):
        return AnalysisLevelSummaryView(
            result_level=arguments["result_level"],
            stakeholder_group_id=arguments.get("stakeholder_group_id"),
            stakeholder_group_label="Community",
            case_count=1,
            evaluated_count=1,
            not_evaluable_count=0,
            top_set_change_count=1,
            strict_reversal_count=0,
            maximum_rank_displacement=1,
            warning_count=0,
            displacement_distribution={1: 1},
        )

    def list_analysis_cases(self, analysis_run_id, **arguments):
        case = AnalysisCaseView(
            analysis_case_id="case-1",
            sequence=1,
            status=AnalysisCaseStatus.EVALUATED,
            scope_type="participant",
            scope_id="group-1",
            scope_label="Community",
            subject_type="participant",
            subject_id="participant-secret",
            subject_label="Participant SECRET",
            inputs={"omitted_participant_id": "participant-secret"},
            results={
                "session_metrics": {
                    "top_set_changed": True,
                    "kendall_tau_b": "0.8",
                    "maximum_rank_displacement": 1,
                },
                "group_metrics": {
                    "top_set_changed": False,
                    "kendall_tau_b": "1",
                    "maximum_rank_displacement": 0,
                },
            },
            warnings=(),
            content_hash="d" * 64,
        )
        return PageResult((case,), 1, 25, 1)


context = SimpleNamespace(
    container=SimpleNamespace(
        settings=SimpleNamespace(app_timezone="UTC"),
        analysis=SimpleNamespace(run_selected=SimpleNamespace(), list_runs=History()),
    ),
    principal=SimpleNamespace(subject="admin-1"),
    queries=Queries(),
)
detail = SimpleNamespace(summary=SimpleNamespace(session_id="session-1"))
render_analysis_stage(context, detail, (source,), (ranking,), read_only=False)
"""


def test_analysis_stage_separates_all_five_selectable_tests() -> None:
    app = AppTest.from_string(ANALYSIS_APP, default_timeout=10).run()

    assert not app.exception
    assert {item.label for item in app.checkbox} == {
        "Weight perturbation",
        "Criterion removal",
        "Rank reversal",
        "Stakeholder-group influence",
        "Participant influence",
    }
    assert tuple(item.label for item in app.tabs) == (
        "Weight perturbation",
        "Criterion removal",
        "Rank reversal",
        "Stakeholder-group influence",
        "Participant influence",
    )
    assert next(
        item for item in app.button if item.label == "Run selected tests"
    ).disabled
    assert len(app.info) == 5


def test_weight_perturbation_controls_default_to_standard() -> None:
    app = AppTest.from_string(ANALYSIS_APP, default_timeout=10).run()
    app = (
        next(item for item in app.checkbox if item.label == "Weight perturbation")
        .set_value(True)
        .run()
    )

    assert not app.exception
    preset = next(item for item in app.selectbox if item.label == "Range preset")
    assert preset.value == "Standard"
    assert any(
        item.label == "Weight perturbation configuration" for item in app.expander
    )


def test_analysis_execution_declares_two_progress_bars() -> None:
    source = inspect.getsource(analysis_section._execute)

    assert source.count("st.progress(") == 2
    assert "st.status(" in source


def test_result_levels_are_method_specific_and_have_no_combined_scope() -> None:
    assert analysis_section._available_result_levels(
        analysis_section.AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION
    ) == ("session", "stakeholder_group")
    assert analysis_section._available_result_levels(
        analysis_section.AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE
    ) == ("session",)
    assert analysis_section._available_result_levels(
        analysis_section.AnalysisMethod.PARTICIPANT_INFLUENCE
    ) == ("session", "stakeholder_group", "participant")
    source = inspect.getsource(analysis_section)
    assert '"Result scope"' not in source
    assert '"All scopes"' not in source


def test_sampled_stability_rows_follow_selected_level_and_group() -> None:
    summary = {
        "sampled_stability": (
            {"scope_type": "session", "scope_id": None, "criterion_id": "cost"},
            {
                "scope_type": "stakeholder_group",
                "scope_id": "group-1",
                "criterion_id": "cost",
            },
            {
                "scope_type": "stakeholder_group",
                "scope_id": "group-2",
                "criterion_id": "cost",
            },
        )
    }

    session = analysis_section._stability_rows(summary, level="session", group_id=None)
    group = analysis_section._stability_rows(
        summary, level="stakeholder_group", group_id="group-2"
    )

    assert [item["scope_type"] for item in session] == ["session"]
    assert [item["scope_id"] for item in group] == ["group-2"]


def test_participant_aggregate_views_never_render_aliases() -> None:
    session_app = AppTest.from_string(
        ANALYSIS_RESULTS_APP.replace("SELECTED_LEVEL", "0"), default_timeout=10
    ).run()
    group_app = AppTest.from_string(
        ANALYSIS_RESULTS_APP.replace("SELECTED_LEVEL", "1"), default_timeout=10
    ).run()

    for app in (session_app, group_app):
        assert not app.exception
        assert "Participant SECRET" not in _rendered_text(app)
        assert not app.get("download_button")
    assert "Stakeholder group" not in tuple(
        item.label for item in session_app.selectbox
    )
    group_selector = next(
        item for item in group_app.selectbox if item.label == "Stakeholder group"
    )
    assert group_selector.value == "group-1"


def test_participant_aliases_are_confined_to_individual_group_view() -> None:
    app = AppTest.from_string(
        ANALYSIS_RESULTS_APP.replace("SELECTED_LEVEL", "2"), default_timeout=10
    ).run()

    assert not app.exception
    selector = next(
        item
        for item in app.selectbox
        if item.label == "Filter individuals by stakeholder group"
    )
    assert selector.value == "group-1"
    assert "Participant SECRET" in _rendered_text(app)
    source = inspect.getsource(analysis_section._participant_case_page)
    assert "participant:{group_id}" in source


def _rendered_text(app) -> str:
    return " ".join(
        [item.value for item in app.markdown]
        + [item.value for item in app.caption]
        + [str(item.value) for item in app.dataframe]
        + [str(item.value) for item in app.json]
    )
