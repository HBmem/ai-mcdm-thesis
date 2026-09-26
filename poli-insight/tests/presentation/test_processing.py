from __future__ import annotations

import inspect
import json
import unittest
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from poli_insight.application.queries.page_queries import SessionValidationOverview
from poli_insight.domain.enum import RunStatus, SessionStatus
from poli_insight.presentation.streamlit.pages.admin import manage_sessions, processing

PROCESSING_WORKSPACE_APP = """
import importlib
from dataclasses import asdict
from datetime import UTC, datetime
from types import SimpleNamespace

import streamlit as st

from poli_insight.application.queries.page_queries import (
    PageResult,
    ProcessingGroupSubmissionSummary,
    ProcessingSubmissionContext,
    SessionValidationOverview,
)
from poli_insight.application.use_cases.validate_current_submissions import ValidateCurrentSubmissionsResult
from poli_insight.domain.enum import RunStatus, ScenarioSnapshotStatus, SessionStatus
from poli_insight.presentation.streamlit.auth.models import Principal
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.pages.admin.processing import render

steps_module = importlib.import_module("streamlit_extras.steps")
steps_module._STEPS_COMPONENT = lambda **arguments: None
card_selector_module = importlib.import_module("streamlit_extras.card_selector")
card_selector_module._CARD_SELECTOR_COMPONENT = lambda **arguments: None
st.session_state["processing:session_id"] = "session-1"
st.session_state["processing:submission_level:session-1"] = {"selected": [2]}


class Queries:
    def get_session_validation_overview(self, session_id):
        return SessionValidationOverview(
            session_id=session_id,
            session_status=SessionStatus.CLOSED,
            has_active_configuration=True,
            effective_submitted_count=2,
            unvalidated_count=2,
            active_count=0,
            valid_count=0,
            warned_count=0,
            invalid_count=0,
            error_count=0,
            warning_decisions_required=0,
            latest_batch_id=None,
            latest_batch_number=None,
            latest_batch_status=None,
            latest_batch_created_at=None,
            latest_batch_roster_hash=None,
            current_roster_hash="a" * 64,
            roster_is_current=False,
        )

    def get_admin_session_detail(self, session_id):
        return SimpleNamespace(
            summary=SimpleNamespace(
                session_id=session_id,
                scenario_snapshot_id="snapshot-1",
                title="Transit priorities",
                public_slug="transit-priorities",
                status=SessionStatus.CLOSED,
                scenario_title="Transit",
                scenario_version="1.0",
                scenario_status=ScenarioSnapshotStatus.READY,
            ),
            configuration=None,
            group_progress=(),
            audit_events=(),
        )

    def get_processing_submission_context(self, session_id):
        return ProcessingSubmissionContext(
            session_id,
            (
                ProcessingGroupSubmissionSummary(
                    "group-1", "Community", "1", 3, 2, 0, 0, 0, 0, 2,
                    1, 1, 0, 1,
                ),
            ),
        )

    def list_validation_queue(self, session_id, **arguments):
        return PageResult((), arguments["page"], arguments["page_size"], 0)

    def list_participant_validation_matrices(self, session_id):
        return ()

    def list_run_matrices(self, run_id):
        return ()

    def get_session_algorithm_configuration(self, session_id, role):
        return SimpleNamespace(
            conceptual_method="TOPSIS",
            stable_key="pydecision.topsis",
            provider="pydecision",
            library_name="pyDecision",
            library_version="5.1.1",
            parameters={},
        )


class ValidateCurrent:
    def execute(self, command):
        st.session_state["processing_test:session_id"] = command.session_id
        st.session_state["processing_test:actor_id"] = command.actor_id
        return ValidateCurrentSubmissionsResult(
            processing_run_id="run-1",
            run_number=1,
            roster_hash="a" * 64,
            total=2,
            valid=1,
            warned=1,
            invalid=0,
            error=0,
            excluded_disabled=0,
            reused=1,
            executed=1,
        )


class ListBundles:
    def execute(self, session_id):
        return ()


context = PageContext(
    container=SimpleNamespace(validation=SimpleNamespace(
        list_bundles=ListBundles(),
        validate_current=ValidateCurrent(),
    )),
    queries=Queries(),
    principal=Principal("admin-1", "Admin", frozenset({"admin"})),
    authentication=None,
    routes={"manage_sessions": "pages/manage_sessions.py"},
)
render(context)
"""

PROCESSED_WORKSPACE_APP = """
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace

import streamlit as st

from poli_insight.application.queries.page_queries import (
    ProcessingSubmissionContext,
    SessionValidationOverview,
)
from poli_insight.domain.enum import RunStatus, ScenarioSnapshotStatus, SessionStatus
from poli_insight.presentation.streamlit.auth.models import Principal
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.pages.admin.processing import render

steps_module = importlib.import_module("streamlit_extras.steps")
steps_module._STEPS_COMPONENT = lambda **arguments: None
st.session_state["processing:session_id"] = "session-processed"

run = SimpleNamespace(
    processing_run_id="run-4",
    session_id="session-processed",
    run_number=4,
    status=RunStatus.SUCCEEDED,
    created_at=datetime(2026, 8, 20, tzinfo=UTC),
    completed_at=datetime(2026, 8, 20, tzinfo=UTC),
    submissions=(),
    roster_hash="a" * 64,
    input_hash="b" * 64,
    output_hash="c" * 64,
    algorithm_implementation_id="algorithm-1",
    parameter_json={"wd": "geometric"},
    environment_json={"provider": "pyDecision"},
    artifacts=(),
    failure_code=None,
    failure_detail=None,
)


class Queries:
    def get_session_validation_overview(self, session_id):
        return SessionValidationOverview(
            session_id=session_id,
            session_status=SessionStatus.ARCHIVED,
            has_active_configuration=True,
            effective_submitted_count=2,
            unvalidated_count=0,
            active_count=0,
            valid_count=2,
            warned_count=0,
            invalid_count=0,
            error_count=0,
            warning_decisions_required=0,
            latest_batch_id="run-4",
            latest_batch_number=4,
            latest_batch_status=RunStatus.SUCCEEDED,
            latest_batch_created_at=run.created_at,
            latest_batch_roster_hash="a" * 64,
            current_roster_hash="a" * 64,
            roster_is_current=True,
        )

    def get_admin_session_detail(self, session_id):
        return SimpleNamespace(
            summary=SimpleNamespace(
                session_id=session_id,
                scenario_snapshot_id="snapshot-1",
                title="Archived priorities",
                public_slug="archived-priorities",
                status=SessionStatus.ARCHIVED,
                scenario_title="Transit",
                scenario_version="1.0",
                scenario_status=ScenarioSnapshotStatus.READY,
            ),
            configuration=None,
            group_progress=(),
            audit_events=(),
        )

    def get_processing_submission_context(self, session_id):
        return ProcessingSubmissionContext(session_id, ())

    def list_run_matrices(self, run_id):
        return ()

    def get_session_algorithm_configuration(self, session_id, role):
        return SimpleNamespace(
            conceptual_method="TOPSIS",
            stable_key="pydecision.topsis",
            provider="pydecision",
            library_name="pyDecision",
            library_version="5.1.1",
            parameters={},
        )


class ListBundles:
    def execute(self, session_id):
        return (run,)


context = PageContext(
    container=SimpleNamespace(validation=SimpleNamespace(list_bundles=ListBundles())),
    queries=Queries(),
    principal=Principal("admin-1", "Admin", frozenset({"admin"})),
    authentication=None,
    routes={"manage_sessions": "pages/manage_sessions.py"},
)
render(context)
"""

MATRIX_BROWSER_APP = """
from poli_insight.application.queries.page_queries import ProcessingMatrixView
from poli_insight.presentation.streamlit.pages.admin.processing import _render_matrix_browser

matrices = (
    ProcessingMatrixView(
        matrix_id="matrix-1",
        level="participant",
        label="Participant ABCD · Community",
        participant_label="Participant ABCD",
        stakeholder_group_id="group-1",
        stakeholder_group_label="Community",
        validation_id="validation-1",
        criterion_ids=("cost", "access"),
        criterion_labels=("Cost", "Access"),
        values=(("1", "2"), ("0.5", "1")),
        weights=("0.6", "0.4"),
        diagnostics={"consistency_ratio": "0.12"},
        normalized_answers=({"criterion_id": "cost", "value": "0.6"},),
        matrix_hash="a" * 64,
        warnings=("consistency.threshold_exceeded",),
        participant_count=1,
    ),
)
_render_matrix_browser(
    matrices,
    title="Participant matrices",
    key="matrix-test",
    group_filter=True,
)
"""
MALFORMED_WEIGHT_APP = MATRIX_BROWSER_APP.replace(
    'weights=("0.6", "0.4"),',
    "weights=(\"{'__poli_insight_type__': 'decimal', 'value': '0.6'}\", \"0.4\"),",
).replace(
    'warnings=("consistency.threshold_exceeded",),',
    "warnings=(),",
)

PROCESSING_QUEUE_APP = """
from datetime import UTC, datetime
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import (
    PageResult,
    ProcessingQueueMode,
    ProcessingSessionSummary,
)
from poli_insight.domain.enum import RunStatus, ScenarioSnapshotStatus, SessionStatus
from poli_insight.presentation.streamlit.pages.admin.processing import (
    _render_processing_queue,
)

now = datetime(2026, 8, 24, tzinfo=UTC)
items = (
    ProcessingSessionSummary(
        session_id="session-ready",
        title="Transit priorities",
        public_slug="transit-priorities",
        status=SessionStatus.CLOSED,
        scenario_title="Transit",
        scenario_version="1.0",
        scenario_status=ScenarioSnapshotStatus.READY,
        has_active_configuration=True,
        effective_submission_count=5,
        current_roster_hash="a" * 64,
        latest_run_id=None,
        latest_run_number=None,
        latest_run_status=None,
        latest_run_created_at=None,
        last_processing_activity_at=now,
        latest_run_roster_hash=None,
        roster_is_current=False,
        successful_run_count=0,
        next_stage="submission_validation",
        blockers=(),
        opens_at=now,
        closes_at=now,
        created_at=now,
        updated_at=now,
    ),
    ProcessingSessionSummary(
        session_id="session-blocked",
        title="Housing allocation",
        public_slug="housing-allocation",
        status=SessionStatus.CLOSED,
        scenario_title="Housing",
        scenario_version="2.0",
        scenario_status=ScenarioSnapshotStatus.READY,
        has_active_configuration=True,
        effective_submission_count=3,
        current_roster_hash="b" * 64,
        latest_run_id="run-2",
        latest_run_number=2,
        latest_run_status=RunStatus.FAILED,
        latest_run_created_at=now,
        last_processing_activity_at=now,
        latest_run_roster_hash="c" * 64,
        roster_is_current=False,
        successful_run_count=1,
        next_stage="session_validation",
        blockers=("The roster changed",),
        opens_at=now,
        closes_at=now,
        created_at=now,
        updated_at=now,
    ),
)


class Queries:
    def list_session_scenarios(self):
        return ()

    def list_scenario_domains(self):
        return ()

    def list_processing_sessions(self, **arguments):
        return PageResult(
            items,
            arguments["page"],
            arguments["page_size"],
            len(items),
        )


context = SimpleNamespace(
    queries=Queries(),
    container=SimpleNamespace(
        settings=SimpleNamespace(app_timezone="UTC"),
    ),
)
_render_processing_queue(context, ProcessingQueueMode.IN_PROGRESS)
"""

MIXED_MATRIX_BROWSER_APP = """
import importlib

import streamlit as st

from poli_insight.application.queries.page_queries import ProcessingMatrixView
from poli_insight.presentation.streamlit.pages.admin.processing import (
    _render_matrix_browser,
)

card_selector_module = importlib.import_module("streamlit_extras.card_selector")
card_selector_module._CARD_SELECTOR_COMPONENT = lambda **arguments: None


def matrix(
    matrix_id,
    level,
    label,
    participant_label=None,
    group_label=None,
    validation_id=None,
    participant_count=None,
    voting_power=None,
):
    return ProcessingMatrixView(
        matrix_id=matrix_id,
        level=level,
        label=label,
        participant_label=participant_label,
        stakeholder_group_id="group-1" if group_label else None,
        stakeholder_group_label=group_label,
        validation_id=validation_id,
        criterion_ids=("cost", "access"),
        criterion_labels=("Cost", "Access"),
        values=(("1", "2"), ("0.5", "1")),
        weights=("0.6", "0.4"),
        diagnostics={"consistency_ratio": "0.01"},
        normalized_answers=(
            {"criterion_id": "cost", "private_marker": "individual-only"},
        ),
        matrix_hash=matrix_id[0] * 64,
        warnings=(),
        participant_count=participant_count,
        voting_power=voting_power,
    )


matrices = (
    matrix(
        "participant-1",
        "participant",
        "Participant SECRET · Community",
        participant_label="Participant SECRET",
        group_label="Community",
        validation_id="validation-secret",
        participant_count=1,
    ),
    matrix(
        "group-1",
        "stakeholder_group",
        "Community aggregate",
        participant_label="Participant SECRET",
        group_label="Community",
        validation_id="validation-secret",
        participant_count=4,
        voting_power="0.6",
    ),
    matrix(
        "session-1",
        "session",
        "Session aggregate",
        participant_label="Participant SECRET",
        validation_id="validation-secret",
        participant_count=7,
    ),
)
st.session_state["mixed:level"] = {"selected": [SELECTED_LEVEL]}
_render_matrix_browser(matrices, title="Run matrices", key="mixed")
"""

RANKING_BROWSER_APP = """
import importlib

import streamlit as st

from poli_insight.application.queries.page_queries import (
    RankingAlternativeView,
    RankingResultView,
)
from poli_insight.presentation.streamlit.pages.admin.processing import (
    _render_ranking_result_browser,
)

card_selector_module = importlib.import_module("streamlit_extras.card_selector")
card_selector_module._CARD_SELECTOR_COMPONENT = lambda **arguments: None


def result(result_id, level, label, participant=None, validation=None):
    return RankingResultView(
        ranking_result_id=result_id,
        ranking_run_id="ranking-1",
        source_processing_matrix_id="matrix-" + result_id,
        level=level,
        label=label,
        participant_label=participant,
        stakeholder_group_id="group-1" if level != "session" else None,
        stakeholder_group_label="Community" if level != "session" else None,
        validation_id=validation,
        metric_label="Preference",
        alternatives=(
            RankingAlternativeView(
                "alternative-1", "Option A", 1, "0.8", {"metric": "0.8"}
            ),
        ),
        diagnostics={"provider": "test"},
        result_hash=result_id[0] * 64,
    )


results = (
    result(
        "participant-1", "participant", "Participant SECRET",
        participant="Participant SECRET", validation="validation-secret",
    ),
    result("group-1", "stakeholder_group", "Community aggregate"),
    result("session-1", "session", "Session aggregate"),
)
st.session_state["rank-test:level"] = {"selected": [SELECTED_LEVEL]}
_render_ranking_result_browser(results, key="rank-test")
"""


class SessionProcessingPageTests(unittest.TestCase):
    def test_processing_owns_submission_validation_commands(self) -> None:
        processing_source = inspect.getsource(processing)
        manage_source = inspect.getsource(manage_sessions)

        self.assertIn("ValidateCurrentSubmissionsCommand", processing_source)
        self.assertIn("ReviewSubmissionCommand", processing_source)
        self.assertIn('"Validate current submissions"', processing_source)
        self.assertNotIn("ValidateCurrentSubmissionsCommand", manage_source)
        self.assertNotIn("ReviewSubmissionCommand", manage_source)
        self.assertNotIn('"Submission validation"', manage_source)

    def test_stage_reconstruction_keeps_archived_success_inspectable(self) -> None:
        overview = SessionValidationOverview(
            session_id="session-1",
            session_status=SessionStatus.ARCHIVED,
            has_active_configuration=True,
            effective_submitted_count=1,
            unvalidated_count=0,
            active_count=0,
            valid_count=1,
            warned_count=0,
            invalid_count=0,
            error_count=0,
            warning_decisions_required=0,
            latest_batch_id="run-1",
            latest_batch_number=1,
            latest_batch_status=RunStatus.SUCCEEDED,
            latest_batch_created_at=None,
            latest_batch_roster_hash="a" * 64,
            current_roster_hash="a" * 64,
            roster_is_current=True,
        )
        run = SimpleNamespace(processing_run_id="run-1", status=RunStatus.SUCCEEDED)

        self.assertEqual(processing._current_stage_index(overview, (run,)), 3)

    def test_archived_failed_run_remains_inspectable_at_persisted_stage(self) -> None:
        overview = SessionValidationOverview(
            session_id="session-1",
            session_status=SessionStatus.ARCHIVED,
            has_active_configuration=True,
            effective_submitted_count=1,
            unvalidated_count=0,
            active_count=0,
            valid_count=1,
            warned_count=0,
            invalid_count=0,
            error_count=0,
            warning_decisions_required=0,
            latest_batch_id="run-1",
            latest_batch_number=1,
            latest_batch_status=RunStatus.FAILED,
            latest_batch_created_at=None,
            latest_batch_roster_hash="a" * 64,
            current_roster_hash="a" * 64,
            roster_is_current=True,
        )
        run = SimpleNamespace(processing_run_id="run-1", status=RunStatus.FAILED)

        highest = processing._current_stage_index(overview, (run,))
        statuses = processing._stage_statuses(
            selected_index=highest,
            highest_viewable=highest,
            overview=overview,
            runs=(run,),
        )

        self.assertEqual(highest, 2)
        self.assertEqual(statuses[:3], ("complete", "complete", "failed"))
        self.assertEqual(statuses[3:], ("unavailable",) * 3)

    def test_submission_validation_runs_for_selected_closed_session(self) -> None:
        app = AppTest.from_string(PROCESSING_WORKSPACE_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        labels = tuple(item.label for item in app.button)
        self.assertIn("Begin Process", labels)
        self.assertEqual(app.session_state["processing:workflow:session-1:viewed"], 1)
        confirmation = next(
            item
            for item in app.checkbox
            if item.label.startswith("Create a new immutable")
        )
        app = confirmation.set_value(True).run()
        app = (
            next(
                item
                for item in app.button
                if item.key == "processing:validate:session-1"
            )
            .click()
            .run()
        )

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["processing_test:session_id"], "session-1")
        self.assertEqual(app.session_state["processing_test:actor_id"], "admin-1")

    def test_validation_stage_separates_aggregate_and_individual_evidence(self) -> None:
        aggregate_app = AppTest.from_string(
            PROCESSING_WORKSPACE_APP,
            default_timeout=10,
        ).run()
        individual_app = AppTest.from_string(
            PROCESSING_WORKSPACE_APP.replace('{"selected": [2]}', '{"selected": [0]}'),
            default_timeout=10,
        ).run()

        self.assertFalse(aggregate_app.exception)
        self.assertFalse(individual_app.exception)
        aggregate_text = " ".join(item.value for item in aggregate_app.markdown)
        individual_text = " ".join(item.value for item in individual_app.markdown)
        self.assertIn("Session aggregate", aggregate_text)
        self.assertNotIn("Individual participant evidence", aggregate_text)
        self.assertIn("Individual participant evidence", individual_text)
        self.assertNotIn("#### Session aggregate", individual_text)

    def test_processing_queue_uses_direct_session_cards(self) -> None:
        app = AppTest.from_string(PROCESSING_QUEUE_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertFalse(app.dataframe)
        self.assertNotIn("Select session", tuple(item.label for item in app.selectbox))
        self.assertEqual(
            tuple(
                item.label for item in app.button if item.label == "Resume processing"
            ),
            ("Resume processing", "Resume processing"),
        )
        rendered = " ".join(
            (
                *[item.value for item in app.markdown],
                *[item.value for item in app.caption],
            )
        )
        self.assertIn("Transit priorities", rendered)
        self.assertIn("Housing allocation", rendered)
        self.assertIn("Run 2 · Failed", rendered)

        app = (
            next(item for item in app.button if item.label == "Resume processing")
            .click()
            .run()
        )
        self.assertEqual(app.session_state["processing:session_id"], "session-ready")
        self.assertEqual(
            app.session_state["processing:workspace_mode"],
            "in_progress",
        )

    def test_processed_session_opens_at_latest_completed_stage(self) -> None:
        app = AppTest.from_string(PROCESSED_WORKSPACE_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["processing:workflow:session-processed:viewed"], 3)
        markdown = " ".join(item.value for item in app.markdown)
        self.assertIn("Create Ranking", markdown)
        self.assertIn("Session Processing Steps", markdown)
        self.assertIn("Session Processing Details", markdown)
        bundle_preview = next(
            item
            for item in app.expander
            if item.label == "Current State of Final Bundle"
        )
        self.assertFalse(bundle_preview.proto.expanded)
        self.assertNotIn("Generate weights", tuple(item.label for item in app.button))

    def test_matrix_browser_exposes_evidence_charts_and_safe_downloads(self) -> None:
        app = AppTest.from_string(MATRIX_BROWSER_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertEqual(
            tuple(item.label for item in app.selectbox),
            ("Filter individuals by stakeholder group", "Individual matrix"),
        )
        self.assertIn(
            "Individual evidence",
            " ".join(item.value for item in app.markdown),
        )
        self.assertTrue(app.dataframe)
        self.assertTrue(app.warning)
        self.assertEqual(
            tuple(item.label for item in app.get("download_button")),
            ("Download matrix CSV", "Download safe matrix JSON"),
        )

    def test_matrix_partitions_are_stable_and_never_mix_levels(self) -> None:
        matrices = (
            SimpleNamespace(matrix_id="session", level="session"),
            SimpleNamespace(matrix_id="participant", level="participant"),
            SimpleNamespace(matrix_id="group", level="stakeholder_group"),
            SimpleNamespace(matrix_id="future", level="future_level"),
        )

        partitions = processing._partition_matrices_by_level(matrices)

        self.assertEqual(
            tuple(level for level, _items in partitions),
            ("participant", "stakeholder_group", "session", "future_level"),
        )
        self.assertTrue(
            all(
                all(item.level == level for item in items)
                for level, items in partitions
            )
        )

    def test_aggregate_matrix_views_hide_individual_identifiers(self) -> None:
        group_app = AppTest.from_string(
            MIXED_MATRIX_BROWSER_APP.replace("SELECTED_LEVEL", "1"),
            default_timeout=10,
        ).run()
        session_app = AppTest.from_string(
            MIXED_MATRIX_BROWSER_APP.replace("SELECTED_LEVEL", "2"),
            default_timeout=10,
        ).run()

        for app, selector_label, heading in (
            (group_app, "Stakeholder-group matrix", "Stakeholder-group aggregate"),
            (session_app, "Session aggregate matrix", "Session aggregate"),
        ):
            self.assertFalse(app.exception)
            self.assertEqual(
                tuple(item.label for item in app.selectbox),
                (selector_label,),
            )
            visible_text = " ".join(
                [item.value for item in app.markdown]
                + [item.value for item in app.caption]
                + [str(item.value) for item in app.metric]
                + [str(item.value) for item in app.json]
            )
            self.assertIn(heading, visible_text)
            self.assertNotIn("Participant SECRET", visible_text)
            self.assertNotIn("validation-secret", visible_text)
            self.assertNotIn("individual-only", visible_text)

    def test_matrix_browser_contains_malformed_weight_without_page_failure(
        self,
    ) -> None:
        app = AppTest.from_string(MALFORMED_WEIGHT_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertTrue(
            any(
                "persisted weights could not be charted: Cost" in item.value
                for item in app.warning
            )
        )

    def test_aggregate_ranking_browser_hides_individual_identifiers(self) -> None:
        app = AppTest.from_string(
            RANKING_BROWSER_APP.replace("SELECTED_LEVEL", "1"),
            default_timeout=10,
        ).run()

        self.assertFalse(app.exception)
        self.assertEqual(
            tuple(item.label for item in app.selectbox),
            ("Stakeholder-group ranking",),
        )
        rendered = " ".join(
            [item.value for item in app.markdown]
            + [item.value for item in app.caption]
            + [str(item.value) for item in app.metric]
            + [str(item.value) for item in app.json]
        )
        self.assertIn("Stakeholder-group aggregate rankings", rendered)
        self.assertNotIn("Participant SECRET", rendered)
        self.assertNotIn("validation-secret", rendered)
        self.assertEqual(
            tuple(item.label for item in app.get("download_button")),
            ("Download ranking CSV", "Download safe ranking JSON"),
        )

    def test_weighting_preview_redacts_all_individual_evidence(self) -> None:
        artifact = SimpleNamespace(
            artifact_type=SimpleNamespace(value="analysis_bundle"),
            schema_version=1,
            content_hash="f" * 64,
            content_json={
                "algorithm": {"implementation_id": "weighting-1"},
                "ordered_criteria": ["cost", "access"],
                "submissions": [
                    {
                        "participant_id": "participant-secret",
                        "submission_id": "submission-secret",
                        "validation_id": "validation-secret",
                    }
                ],
                "stakeholder_groups": [
                    {
                        "group_key": "community",
                        "included_participant_count": 2,
                        "validation_id": "validation-secret",
                    }
                ],
                "matrices": [
                    {
                        "level": "participant",
                        "participant_id": "participant-secret",
                        "normalized_answers": ["private-answer"],
                    },
                    {
                        "level": "stakeholder_group",
                        "matrix_hash": "a" * 64,
                        "validation_id": "validation-secret",
                    },
                    {"level": "session", "matrix_hash": "b" * 64},
                ],
                "warnings": [],
            },
        )

        redacted = processing._redacted_weighting_artifact(artifact)
        rendered = json.dumps(redacted)

        self.assertNotIn("participant-secret", rendered)
        self.assertNotIn("submission-secret", rendered)
        self.assertNotIn("validation-secret", rendered)
        self.assertNotIn("private-answer", rendered)
        self.assertIn("stakeholder_group", rendered)
        self.assertIn('"level": "session"', rendered)

    def test_successful_current_ranking_advances_to_sensitivity_stage(self) -> None:
        overview = SessionValidationOverview(
            session_id="session-1",
            session_status=SessionStatus.CLOSED,
            has_active_configuration=True,
            effective_submitted_count=1,
            unvalidated_count=0,
            active_count=0,
            valid_count=1,
            warned_count=0,
            invalid_count=0,
            error_count=0,
            warning_decisions_required=0,
            latest_batch_id="weighting-1",
            latest_batch_number=1,
            latest_batch_status=RunStatus.SUCCEEDED,
            latest_batch_created_at=None,
            latest_batch_roster_hash="a" * 64,
            current_roster_hash="a" * 64,
            roster_is_current=True,
        )
        weighting = SimpleNamespace(
            processing_run_id="weighting-1",
            status=RunStatus.SUCCEEDED,
        )
        ranking = SimpleNamespace(
            source_processing_run_id="weighting-1",
            roster_hash="a" * 64,
            status=RunStatus.SUCCEEDED,
        )

        self.assertEqual(
            processing._current_stage_index(overview, (weighting,), (ranking,)),
            4,
        )

    def test_ranking_preview_omits_all_individual_results(self) -> None:
        alternative = SimpleNamespace(
            to_manifest=lambda: {
                "alternative_id": "alternative-1",
                "rank": 1,
                "preference_value": "0.8",
            }
        )
        participant_result = SimpleNamespace(
            level="participant",
            stakeholder_group_id="group-1",
            validation_id="validation-secret",
            metric_label="Preference",
            result_hash="a" * 64,
            alternatives=(alternative,),
        )
        group_result = SimpleNamespace(
            level="stakeholder_group",
            stakeholder_group_id="group-1",
            validation_id=None,
            metric_label="Preference",
            result_hash="b" * 64,
            alternatives=(alternative,),
        )
        run = SimpleNamespace(
            ranking_run_id="ranking-1",
            source_processing_run_id="weighting-1",
            status=RunStatus.SUCCEEDED,
            algorithm_implementation_id="algorithm-1",
            implementation_version="1.0.0",
            adapter_version="1.0.0",
            parameter_json={},
            input_hash="c" * 64,
            output_hash="d" * 64,
            results=(participant_result, group_result),
        )

        rendered = json.dumps(processing._redacted_ranking_run(run))

        self.assertNotIn("validation-secret", rendered)
        self.assertNotIn('"level": "participant"', rendered)
        self.assertIn('"level": "stakeholder_group"', rendered)


if __name__ == "__main__":
    unittest.main()
