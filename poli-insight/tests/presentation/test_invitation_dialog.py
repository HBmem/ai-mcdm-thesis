from __future__ import annotations

import unittest
from datetime import UTC, datetime

from streamlit.testing.v1 import AppTest

from poli_insight.application.use_cases.import_invitations import (
    AppliedInvitation,
    ApplyInvitationImportResult,
)
from poli_insight.application.use_cases.manage_invitations import (
    IssuedInvitationResult,
)
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _invitation_credentials_csv,
)

INVITATION_DIALOG_APP = """
from datetime import UTC, datetime
from types import SimpleNamespace

import streamlit as st

from poli_insight.application.use_cases.manage_invitations import (
    IssuedInvitationResult,
)
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _INVITATION_RESULT_KEY,
    _render_issued_invitation_dialog,
)

if "invitation-dialog:initialized" not in st.session_state:
    st.session_state["invitation-dialog:initialized"] = True
    st.session_state[_INVITATION_RESULT_KEY] = IssuedInvitationResult(
        invitation_id="invitation-1",
        token="private-invitation-token",
        token_hint="…token",
        access_code="study-code",
        expires_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
    )

context = SimpleNamespace(
    container=SimpleNamespace(
        settings=SimpleNamespace(
            public_base_url="http://localhost:8501",
            app_timezone="UTC",
        ),
    ),
)
detail = SimpleNamespace(
    summary=SimpleNamespace(public_slug="test4"),
)
if _INVITATION_RESULT_KEY in st.session_state:
    _render_issued_invitation_dialog(context, detail)
else:
    st.write("Invitation credential cleared")
"""


class InvitationDialogTests(unittest.TestCase):
    def test_dialog_shows_complete_url_and_requires_acknowledgement(self) -> None:
        app = AppTest.from_string(INVITATION_DIALOG_APP, default_timeout=10).run()

        self.assertFalse(app.exception)
        code_values = tuple(item.value for item in app.code)
        self.assertIn(
            "http://localhost:8501/participate?"
            "session=test4&invitation=private-invitation-token",
            code_values,
        )
        self.assertIn("study-code", code_values)
        done = next(item for item in app.button if item.label == "Done")
        self.assertTrue(done.disabled)

        acknowledgement = next(
            item
            for item in app.checkbox
            if item.label.startswith("I have saved")
        )
        app = acknowledgement.check().run()
        done = next(item for item in app.button if item.label == "Done")
        self.assertFalse(done.disabled)
        app = done.click().run()

        self.assertFalse(app.exception)
        self.assertTrue(
            any(
                "Invitation credential cleared" in item.value
                for item in app.markdown
            )
        )

    def test_batch_credentials_csv_contains_complete_participation_url(self) -> None:
        result = ApplyInvitationImportResult(
            batch_id="batch-1",
            file_hash="file-hash",
            imported_count=1,
            duplicate_count=0,
            invalid_count=0,
            invitations=(
                AppliedInvitation(
                    reference="participant@example.test",
                    invitation=IssuedInvitationResult(
                        invitation_id="invitation-1",
                        token="private+token/with?delimiters",
                        token_hint="…ters",
                        access_code=None,
                        expires_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
                    ),
                ),
            ),
        )

        csv_content = _invitation_credentials_csv(
            result,
            "https://research.example.test/poli-insight/",
            "budget study/2026",
        ).decode("utf-8")

        self.assertIn(
            "https://research.example.test/poli-insight/participate?"
            "session=budget+study%2F2026&"
            "invitation=private%2Btoken%2Fwith%3Fdelimiters",
            csv_content,
        )


if __name__ == "__main__":
    unittest.main()
