from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest

EMPTY_LIBRARY_APP = """
import importlib
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import (
    PageResult,
    ScenarioLibraryMetrics,
    SessionCatalogMetrics,
)
from poli_insight.application.ports.bundled_scenarios import ScenarioTemplateArchive
from poli_insight.presentation.streamlit.auth.models import Principal
from poli_insight.presentation.streamlit.context import PageContext
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import render


# AppTest imports the page module before installing its component registry.
# Replace only the visual mount; StepsState navigation remains under test.
steps_module = importlib.import_module("streamlit_extras.steps")
steps_module._STEPS_COMPONENT = lambda **arguments: None


class EmptyScenarioQueries:
    def get_session_catalog_metrics(self, **arguments):
        return SessionCatalogMetrics(0, 0, 0)

    def list_session_scenarios(self):
        return ()

    def list_admin_sessions(self, **arguments):
        return PageResult(
            items=(),
            page=arguments["page"],
            page_size=arguments["page_size"],
            total=0,
        )

    def get_scenario_library_metrics(self):
        return ScenarioLibraryMetrics(0, 0, 0, 0)

    def list_scenario_domains(self):
        return ()

    def list_scenario_snapshots(self, **arguments):
        return PageResult(
            items=(),
            page=arguments["page"],
            page_size=arguments["page_size"],
            total=0,
        )

    def list_audit_actions(self):
        return ()

    def list_admin_audit_events(self, **arguments):
        return PageResult(
            items=(),
            page=arguments["page"],
            page_size=arguments["page_size"],
            total=0,
        )


class BundledScenarios:
    def template_archive(self):
        return ScenarioTemplateArchive(
            filename="template.zip",
            content=b"zip",
            file_paths=("scenario-template/scenario.jsonc",),
        )


container = SimpleNamespace(
    settings=SimpleNamespace(app_timezone="UTC"),
    import_scenario=None,
    import_bundled_scenarios=BundledScenarios(),
)
context = PageContext(
    container=container,
    queries=EmptyScenarioQueries(),
    principal=Principal("admin", "Admin", frozenset({"admin"})),
    authentication=None,
    routes={},
)
render(context)
"""


CREATE_DIALOG_APP = """
import importlib
from types import SimpleNamespace

from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _render_create_session_dialog,
)


steps_module = importlib.import_module("streamlit_extras.steps")
steps_module._STEPS_COMPONENT = lambda **arguments: None

summary = SimpleNamespace(
    scenario_snapshot_id="snapshot-1",
    title="School closure",
    scenario_key="school-closure",
    declared_version="2026.1",
    domain="Education",
    summary="Evaluate school consolidation alternatives.",
    alternative_count=2,
    criterion_count=1,
    scale_count=1,
    file_count=3,
)
detail = SimpleNamespace(
    summary=summary,
    policy_question="Which consolidation plan should be selected?",
    alternatives=(),
    criteria=(),
    scales=(),
)


class Queries:
    def list_scenario_snapshots(self, **arguments):
        return SimpleNamespace(items=(summary,))

    def get_scenario_snapshot_detail(self, scenario_snapshot_id):
        return detail if scenario_snapshot_id == "snapshot-1" else None


context = SimpleNamespace(
    queries=Queries(),
    container=SimpleNamespace(
        settings=SimpleNamespace(app_timezone="UTC"),
    ),
)
_render_create_session_dialog(context)
"""


CONFIGURATION_DIALOG_APP = """
import importlib
from types import SimpleNamespace

import streamlit as st

from poli_insight.domain.enum import AlgorithmRole, ResponseFormat, SessionStatus
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _render_configuration_dialog,
)


steps_module = importlib.import_module("streamlit_extras.steps")
steps_module._STEPS_COMPONENT = lambda **arguments: None

detail = SimpleNamespace(
    summary=SimpleNamespace(
        session_id="session-1",
        scenario_snapshot_id="snapshot-1",
        status=SessionStatus.DRAFT,
    ),
)
scenario = SimpleNamespace(
    default_response_format=ResponseFormat.PAIRWISE,
    default_scale_key="pairwise_seven_point_v1",
    stakeholder_group_defaults=(
        SimpleNamespace(
            group_key="students",
            name="Students",
            description="Affected students",
            allocation_units=10000,
            required=True,
        ),
    ),
    scales=(
        SimpleNamespace(
            scale_id="direct-5",
            scale_key="direct_five_point_v1",
            name="Direct Rating Five Point V1",
            scale_type="direct_rating",
            value_count=5,
            is_application_defined=True,
        ),
        SimpleNamespace(
            scale_id="direct-7",
            scale_key="direct_seven_point_v1",
            name="Direct Rating Seven Point V1",
            scale_type="direct_rating",
            value_count=7,
            is_application_defined=True,
        ),
        SimpleNamespace(
            scale_id="pairwise-5",
            scale_key="pairwise_five_point_v1",
            name="Pairwise Five Point V1",
            scale_type="pairwise",
            value_count=5,
            is_application_defined=True,
        ),
        SimpleNamespace(
            scale_id="pairwise-7",
            scale_key="pairwise_seven_point_v1",
            name="Pairwise Seven Point V1",
            scale_type="pairwise",
            value_count=7,
            is_application_defined=True,
        ),
    ),
)


class Queries:
    def get_admin_session_detail(self, session_id):
        return detail if session_id == "session-1" else None

    def get_scenario_snapshot_detail(self, snapshot_id):
        return scenario if snapshot_id == "snapshot-1" else None

    def list_active_algorithm_implementations(self, *, role):
        if role == AlgorithmRole.WEIGHTING:
            return (
                SimpleNamespace(
                    algorithm_implementation_id="weighting-1",
                    conceptual_method="AHP",
                    library_name="pyDecision",
                    library_version="5.1.1",
                ),
            )
        return (
            SimpleNamespace(
                algorithm_implementation_id="ranking-1",
                conceptual_method="TOPSIS",
                library_name="pyDecision",
                library_version="5.1.1",
            ),
        )


st.session_state["session_config:generation"] = 1
st.session_state["session_config:session_id"] = "session-1"
context = SimpleNamespace(
    queries=Queries(),
    principal=SimpleNamespace(subject="admin"),
    container=SimpleNamespace(),
)
_render_configuration_dialog(context)
"""


OPERATIONAL_EMPTY_APP = """
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import PageResult
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _render_session_invitations,
    _render_session_participants,
    _render_session_submissions,
    _render_validation_queue,
)


class Queries:
    def get_session_participant_metrics(self, session_id):
        return SimpleNamespace(
            total_enrolled=0,
            never_started=0,
            active_drafts=0,
            completion_rate=0.0,
            stale_drafts=0,
            resume_links_expiring_soon=0,
        )

    def list_session_invitations(self, session_id, **arguments):
        return PageResult((), arguments["page"], arguments["page_size"], 0)

    def list_session_participants(self, session_id, **arguments):
        return PageResult((), arguments["page"], arguments["page_size"], 0)

    def list_session_submissions(self, session_id, **arguments):
        return PageResult((), arguments["page"], arguments["page_size"], 0)

    def list_validation_queue(self, session_id, **arguments):
        return PageResult((), arguments["page"], arguments["page_size"], 0)


detail = SimpleNamespace(
    summary=SimpleNamespace(
        session_id="session-1",
        public_slug="study-one",
    ),
    configuration=None,
    group_progress=(),
)
context = SimpleNamespace(
    queries=Queries(),
    principal=SimpleNamespace(subject="admin"),
    container=SimpleNamespace(
        settings=SimpleNamespace(app_timezone="UTC"),
        operations=SimpleNamespace(
            invitations=SimpleNamespace(),
        ),
    ),
)
_render_session_invitations(context, detail)
_render_session_participants(context, detail)
_render_session_submissions(context, detail)
_render_validation_queue(context, detail)
"""


VALIDATION_REVIEW_FORM_APP = """
from types import SimpleNamespace

from poli_insight.domain.enum import SubmissionReviewStatus
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _render_review_form,
)


class ReviewSubmission:
    def execute(self, command):
        return command


context = SimpleNamespace(
    principal=SimpleNamespace(subject="admin"),
    container=SimpleNamespace(
        operations=SimpleNamespace(
            review_submission=ReviewSubmission(),
        ),
    ),
)
detail = SimpleNamespace(summary=SimpleNamespace(session_id="session-1"))
submission = SimpleNamespace(
    summary=SimpleNamespace(
        submission_id="submission-1",
        participant_label="Participant SAMPLE",
        attempt_number=1,
    ),
    review_status=SubmissionReviewStatus.PENDING,
    validation_id=None,
)
_render_review_form(context, detail, submission)
"""


CONFIGURATION_RULES_FORM_APP = """
from decimal import Decimal

import streamlit as st

from poli_insight.domain.enum import MissingGroupPolicy
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _ConfigurationRulesDraft,
    _render_configuration_rules_step,
)


prefix = "rules-test"
st.session_state[f"{prefix}:rules_draft"] = _ConfigurationRulesDraft(
    allow_resubmissions=False,
    max_submissions_per_participant=1,
    allow_incomplete_submission=False,
    minimum_valid_submissions=1,
    missing_group_policy=MissingGroupPolicy.FAIL,
    consistency_threshold=Decimal("0.1"),
    consent_required=False,
    consent_version="1",
    consent_title="Research participation consent",
    consent_statement="Consent statement",
)
_render_configuration_rules_step(prefix, "rules-test:step")
"""


class ManageSessionsPageTests(unittest.TestCase):
    def test_validation_review_submit_updates_with_confirmation(self) -> None:
        app = AppTest.from_string(
            VALIDATION_REVIEW_FORM_APP,
            default_timeout=10,
        ).run()

        submit = _button(app, "Record decision")
        self.assertTrue(submit.disabled)

        confirmation = next(
            item
            for item in app.checkbox
            if item.label.startswith("I confirm this review decision")
        )
        app = confirmation.set_value(True).run()
        self.assertFalse(app.exception)
        self.assertFalse(_button(app, "Record decision").disabled)

    def test_configuration_form_has_no_reactive_disabled_fields(self) -> None:
        app = AppTest.from_string(
            CONFIGURATION_RULES_FORM_APP,
            default_timeout=10,
        ).run()

        self.assertFalse(app.exception)
        maximum = next(
            item
            for item in app.number_input
            if item.label == "Maximum submissions per participant"
        )
        self.assertFalse(maximum.disabled)
        for label in ("Consent version", "Consent title"):
            self.assertFalse(_text_input(app, label).disabled)
        consent_statement = next(
            item for item in app.text_area if item.label == "Consent statement"
        )
        self.assertFalse(consent_statement.disabled)

    def test_operational_empty_states_render_without_data(self) -> None:
        app = AppTest.from_string(OPERATIONAL_EMPTY_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        markdown = " ".join(item.value for item in app.markdown)
        self.assertIn("Invitation management", markdown)
        self.assertIn("Participants", markdown)
        self.assertIn("Submissions", markdown)
        self.assertIn("Validation review queue", markdown)

    def test_empty_scenario_library_renders_metrics_and_import_action(self) -> None:
        app = AppTest.from_string(EMPTY_LIBRARY_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertIn(
            "Scenario Library",
            tuple(item.value for item in app.subheader),
        )
        self.assertEqual(
            tuple((item.label, item.value) for item in app.metric)[-4:],
            (
                ("Definitions", "0"),
                ("Snapshots", "0"),
                ("Ready", "0"),
                ("Needs attention", "0"),
            ),
        )
        self.assertIn(
            "Upload ZIP",
            tuple(item.label for item in app.button),
        )
        self.assertIn(
            "Create session",
            tuple(item.label for item in app.button),
        )
        self.assertIn(
            "Scan bundled scenarios",
            tuple(item.label for item in app.button),
        )
        self.assertIn(
            "Download scenario template",
            tuple(item.label for item in app.get("download_button")),
        )

    def test_successful_batch_result_state(self) -> None:
        app = _render_batch_result(imported=2, skipped=0, failed=0)

        self.assertFalse(app.exception)
        self.assertTrue(app.success)
        self.assertEqual(_metric_values(app), ("2", "2", "0", "0"))

    def test_mixed_batch_result_state(self) -> None:
        app = _render_batch_result(imported=1, skipped=0, failed=1)

        self.assertFalse(app.exception)
        self.assertTrue(app.warning)
        self.assertEqual(_metric_values(app), ("2", "1", "0", "1"))

    def test_duplicate_batch_result_state(self) -> None:
        app = _render_batch_result(imported=0, skipped=2, failed=0)

        self.assertFalse(app.exception)
        self.assertTrue(app.info)
        self.assertEqual(_metric_values(app), ("2", "0", "2", "0"))

    def test_create_dialog_uses_steps_and_handles_empty_library(self) -> None:
        app = AppTest.from_string(EMPTY_LIBRARY_APP, default_timeout=10).run()
        create_button = next(
            item for item in app.button if item.label == "Create session"
        )

        app = create_button.click().run()

        self.assertFalse(app.exception)
        self.assertIn(
            "#### Choose a ready scenario snapshot",
            tuple(item.value for item in app.markdown),
        )
        self.assertTrue(
            any("No ready scenarios" in item.value for item in app.subheader)
        )

    def test_creation_scenario_preview_remains_visible(self) -> None:
        source = """
from types import SimpleNamespace

from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _render_creation_scenario_preview,
)

detail = SimpleNamespace(
    summary=SimpleNamespace(
        title="School closure",
        scenario_key="school-closure",
        declared_version="2026.1",
        domain="Education",
        summary="Evaluate school consolidation alternatives.",
        alternative_count=2,
        criterion_count=1,
        scale_count=1,
        file_count=3,
    ),
    policy_question="Which consolidation plan should be selected?",
    alternatives=(
        SimpleNamespace(
            name="Plan A",
            alternative_key="plan-a",
            description="First plan",
        ),
    ),
    criteria=(
        SimpleNamespace(
            name="Cost",
            criterion_key="cost",
            direction=SimpleNamespace(value="cost"),
            required=True,
        ),
    ),
    scales=(
        SimpleNamespace(
            name="Importance",
            scale_key="importance",
            scale_type="numeric",
            value_count=5,
        ),
    ),
)
_render_creation_scenario_preview(detail)
"""

        app = AppTest.from_string(source, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertIn(
            "#### School closure",
            tuple(item.value for item in app.markdown),
        )
        self.assertEqual(
            tuple((item.label, item.value) for item in app.metric),
            (
                ("Alternatives", "2"),
                ("Criteria", "1"),
                ("Scales", "1"),
                ("Files", "3"),
            ),
        )
        self.assertIn(
            "Which consolidation plan should be selected?",
            tuple(item.value for item in app.info),
        )

    def test_create_dialog_retains_values_through_review(self) -> None:
        app = AppTest.from_string(CREATE_DIALOG_APP, default_timeout=10).run()

        app = _button(app, "Continue to details").click().run()
        _text_input(app, "Session title").set_value("Retained title")
        _text_input(app, "Public slug").set_value("retained-title")
        app = _button(app, "Continue to access").click().run()
        app = _button(app, "Review draft").click().run()

        self.assertFalse(app.exception)
        review = dict(
            app.dataframe[-1]
            .value[["Setting", "Value"]]
            .itertuples(
                index=False,
                name=None,
            )
        )
        self.assertEqual(review["Title"], "Retained title")
        self.assertEqual(review["Public slug"], "retained-title")
        self.assertIn("School closure", review["Scenario"])

    def test_configuration_dialog_retains_widget_values_for_review(self) -> None:
        app = AppTest.from_string(
            CONFIGURATION_DIALOG_APP,
            default_timeout=10,
        ).run()

        self.assertEqual(
            next(
                item
                for item in app.selectbox
                if item.label == "Participant response method"
            ).value,
            "Compare criteria in pairs",
        )
        app = _button(app, "Continue to stakeholders").click().run()
        self.assertEqual(app.dataframe[-1].value.iloc[0]["Group key"], "students")
        app = _button(app, "Continue to rules").click().run()
        app = _button(app, "Review configuration").click().run()

        self.assertFalse(app.exception)
        self.assertIn(
            "#### Review immutable version",
            tuple(item.value for item in app.markdown),
        )
        review = dict(
            app.dataframe[-1]
            .value[["Setting", "Value"]]
            .itertuples(
                index=False,
                name=None,
            )
        )
        self.assertEqual(review["Scale"], "Pairwise Seven Point V1")
        self.assertEqual(review["Minimum valid submissions"], "1")

    def test_questioning_method_filters_response_scale_family(self) -> None:
        app = AppTest.from_string(
            CONFIGURATION_DIALOG_APP,
            default_timeout=10,
        ).run()

        pairwise_scale = next(
            item for item in app.selectbox if item.label == "Response scale"
        )
        self.assertEqual(pairwise_scale.value, "pairwise-7")
        self.assertEqual(
            pairwise_scale.options,
            [
                "Application · Pairwise Five Point V1 · 5 values",
                "Scenario default · Pairwise Seven Point V1 · 7 values",
            ],
        )

        method = next(
            item
            for item in app.selectbox
            if item.label == "Participant response method"
        )
        app = method.select("Rate criteria").run()
        direct_scale = next(
            item for item in app.selectbox if item.label == "Response scale"
        )
        self.assertEqual(direct_scale.value, "direct-5")
        self.assertEqual(
            direct_scale.options,
            [
                "Application · Direct Rating Five Point V1 · 5 values",
                "Application · Direct Rating Seven Point V1 · 7 values",
            ],
        )


def _render_batch_result(
    *,
    imported: int,
    skipped: int,
    failed: int,
) -> AppTest:
    statuses = ["IMPORTED"] * imported + ["SKIPPED"] * skipped + ["FAILED"] * failed
    outcome_expressions = ",\n".join(
        _outcome_expression(index, status)
        for index, status in enumerate(statuses, start=1)
    )
    source = f"""
from poli_insight.application.use_cases.import_bundled_scenarios import (
    BundledScenarioImportOutcome,
    BundledScenarioOutcomeStatus,
    ImportBundledScenariosResult,
)
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _render_batch_result,
)

result = ImportBundledScenariosResult(
    correlation_id="batch-reference",
    discovered_count={len(statuses)},
    imported_count={imported},
    skipped_duplicate_count={skipped},
    failed_count={failed},
    outcomes=({outcome_expressions},),
)
_render_batch_result(result)
"""
    return AppTest.from_string(source, default_timeout=10).run()


def _outcome_expression(index: int, status: str) -> str:
    snapshot_id = None if status == "FAILED" else f"snapshot-{index}"
    error_message = "Safe validation failure" if status == "FAILED" else None
    return (
        "BundledScenarioImportOutcome("
        f"display_name='Package {index}', "
        f"relative_directory='package-{index}', "
        "declared_version='1.0', "
        f"status=BundledScenarioOutcomeStatus.{status}, "
        f"snapshot_id={snapshot_id!r}, "
        f"error_message={error_message!r})"
    )


def _metric_values(app: AppTest) -> tuple[str, ...]:
    return tuple(item.value for item in app.metric)


def _button(app: AppTest, label: str):
    return next(item for item in app.button if item.label == label)


def _text_input(app: AppTest, label: str):
    return next(item for item in app.text_input if item.label == label)


if __name__ == "__main__":
    unittest.main()
