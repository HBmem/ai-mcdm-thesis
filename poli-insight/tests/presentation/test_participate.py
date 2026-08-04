from __future__ import annotations

import unittest

from streamlit.testing.v1 import AppTest

ENROLLMENT_APP = """
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import (
    ParticipationGroupOption,
    PublicParticipationSession,
)
from poli_insight.domain.enum import (
    AccessCodeMode,
    EnrollmentMode,
    StakeholderSelectionMode,
)
from poli_insight.presentation.streamlit.pages.public.participate import (
    _render_enrollment,
)


session = PublicParticipationSession(
    session_id="session-1",
    public_slug="public-study",
    title="Public study",
    description="A public questionnaire.",
    enrollment_mode=EnrollmentMode.OPEN,
    access_code_mode=AccessCodeMode.NONE,
    stakeholder_selection_mode=StakeholderSelectionMode.SELF_SELECT,
    identity_policy="pseudonymous",
    groups=(ParticipationGroupOption("group-1", "Community", "Community members"),),
)

class Queries:
    def get_public_participation_session(self, slug):
        return session

context = SimpleNamespace(
    principal=SimpleNamespace(is_authenticated=False, subject=None),
    queries=Queries(),
)
_render_enrollment(context, "public-study")
"""

PARTICIPATION_WORKSPACE_APP = """
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import (
    ParticipationGroupOption,
    ParticipationQuestion,
    ParticipationScaleOption,
    ParticipationWorkspace,
    PublicParticipationSession,
)
from poli_insight.domain.enum import (
    AccessCodeMode,
    EnrollmentMode,
    QuestionType,
    ResponseFormat,
    StakeholderSelectionMode,
    SubmissionStatus,
)
from poli_insight.presentation.streamlit.pages.public.participate import (
    _render_authenticated_workspace,
)


steps_module = importlib.import_module("streamlit_extras.steps")
steps_module._STEPS_COMPONENT = lambda **arguments: None

session = PublicParticipationSession(
    session_id="session-1",
    public_slug="public-study",
    title="Public study",
    description="A public questionnaire.",
    enrollment_mode=EnrollmentMode.OPEN,
    access_code_mode=AccessCodeMode.NONE,
    stakeholder_selection_mode=StakeholderSelectionMode.SELF_SELECT,
    identity_policy="pseudonymous",
    groups=(ParticipationGroupOption("group-1", "Community", "Community members"),),
)
workspace = ParticipationWorkspace(
    participant_id="participant-1",
    session=session,
    response_format=ResponseFormat.DIRECT_RATING,
    questions=(
        ParticipationQuestion(
            question_definition_id="question-1",
            question_type=QuestionType.CRITERION_RATING,
            prompt="Rate access to services.",
            required=True,
            display_order=0,
            target_name="Access",
            target_description="Access to public services.",
            left_name=None,
            right_name=None,
        ),
    ),
    scale_name="Five point rating",
    scale_options=(
        ParticipationScaleOption("scale-value-1", "Low", 0, "1"),
        ParticipationScaleOption("scale-value-2", "High", 1, "5"),
    ),
    consent_required=False,
    consent_version="1",
    consent_title="Research consent",
    consent_statement="",
    consent_completed=False,
    submission_id="submission-1",
    submission_status=SubmissionStatus.DRAFT,
    attempt_number=1,
    answers={"question-1": {"selected_scale_value_id": "scale-value-1"}},
    last_saved_at=datetime.now(tz=UTC),
)

class Resume:
    def execute(self, token):
        return SimpleNamespace(participant_id="participant-1")

class Queries:
    def get_participation_workspace(self, participant_id):
        return workspace

class SaveDraft:
    def execute(self, command):
        return SimpleNamespace(submission_id="submission-1")

context = SimpleNamespace(
    container=SimpleNamespace(
        participation=SimpleNamespace(resume=Resume()),
        submissions=SimpleNamespace(save_draft=SaveDraft()),
        settings=SimpleNamespace(app_timezone="UTC"),
    ),
    queries=Queries(),
)
_render_authenticated_workspace(context, "private-resume-token")
"""


class ParticipatePageTests(unittest.TestCase):
    def test_enrollment_without_access_code_enables_when_requirements_met(
        self,
    ) -> None:
        app = AppTest.from_string(ENROLLMENT_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        self.assertEqual(
            tuple(item.label for item in app.text_input),
            ("Participant alias (optional)",),
        )
        enroll = next(
            button for button in app.button if button.label == "Enroll and continue"
        )
        self.assertTrue(enroll.disabled)

        app.selectbox[0].select("Community").run()
        next(
            checkbox
            for checkbox in app.checkbox
            if checkbox.label.startswith("I understand")
        ).check().run()

        enroll = next(
            button for button in app.button if button.label == "Enroll and continue"
        )
        self.assertFalse(enroll.disabled)

    def test_enrollment_waits_for_group_selection(self) -> None:
        app = AppTest.from_string(ENROLLMENT_APP, default_timeout=10).run()

        next(
            checkbox
            for checkbox in app.checkbox
            if checkbox.label.startswith("I understand")
        ).check().run()
        enroll = next(
            button for button in app.button if button.label == "Enroll and continue"
        )

        self.assertFalse(app.exception)
        self.assertTrue(enroll.disabled)

    def test_enrollment_waits_for_resume_link_confirmation(self) -> None:
        app = AppTest.from_string(ENROLLMENT_APP, default_timeout=10).run()

        app.selectbox[0].select("Community").run()
        enroll = next(
            button for button in app.button if button.label == "Enroll and continue"
        )

        self.assertFalse(app.exception)
        self.assertTrue(enroll.disabled)

    def test_access_code_field_is_configuration_driven_and_validated(self) -> None:
        code_app = ENROLLMENT_APP.replace(
            "access_code_mode=AccessCodeMode.NONE,",
            "access_code_mode=AccessCodeMode.SHARED_SESSION_CODE,",
        )
        app = AppTest.from_string(code_app, default_timeout=10).run()

        self.assertIn("Access code", tuple(item.label for item in app.text_input))
        app.selectbox[0].select("Community").run()
        next(
            checkbox
            for checkbox in app.checkbox
            if checkbox.label.startswith("I understand")
        ).check().run()
        enroll = next(
            button for button in app.button if button.label == "Enroll and continue"
        )

        self.assertFalse(app.exception)
        self.assertTrue(enroll.disabled)

        next(
            item for item in app.text_input if item.label == "Access code"
        ).input("study-code").run()
        enroll = next(
            button for button in app.button if button.label == "Enroll and continue"
        )
        self.assertFalse(enroll.disabled)

    def test_questionnaire_workspace_renders_steps_and_review(self) -> None:
        app = AppTest.from_string(
            PARTICIPATION_WORKSPACE_APP,
            default_timeout=10,
        ).run()

        self.assertFalse(app.exception)
        markdown = tuple(item.value for item in app.markdown)
        self.assertTrue(any("Study consent" in value for value in markdown))
        app.button[0].click().run()
        markdown = tuple(item.value for item in app.markdown)
        self.assertTrue(any("Rate each criterion" in value for value in markdown))
        next(
            button for button in app.button if button.label == "Save and review"
        ).click().run()
        markdown = tuple(item.value for item in app.markdown)
        self.assertTrue(any("Review your responses" in value for value in markdown))
        self.assertIn(
            "Submit questionnaire",
            tuple(button.label for button in app.button),
        )


if __name__ == "__main__":
    unittest.main()
