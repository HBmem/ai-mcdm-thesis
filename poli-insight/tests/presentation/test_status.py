from __future__ import annotations

import unittest

from poli_insight.domain.enum import (
    ReportApprovalStatus,
    RunStatus,
    ScenarioSnapshotStatus,
    SessionStatus,
    ValidationStatus,
)
from poli_insight.presentation.streamlit.components.status import (
    StatusTone,
    status_presentation,
)


class StatusPresentationTests(unittest.TestCase):
    def test_independent_workflow_states_have_distinct_semantics(self) -> None:
        self.assertEqual(
            status_presentation(SessionStatus.OPEN).tone,
            StatusTone.SUCCESS,
        )
        self.assertEqual(
            status_presentation(ValidationStatus.INVALID).tone,
            StatusTone.ERROR,
        )
        self.assertEqual(
            status_presentation(RunStatus.RUNNING).tone,
            StatusTone.INFO,
        )
        self.assertEqual(
            status_presentation(ReportApprovalStatus.REVIEW_REQUIRED).tone,
            StatusTone.WARNING,
        )
        self.assertEqual(
            status_presentation(ScenarioSnapshotStatus.READY).tone,
            StatusTone.SUCCESS,
        )
        self.assertEqual(
            status_presentation(ScenarioSnapshotStatus.INVALID).tone,
            StatusTone.ERROR,
        )


if __name__ == "__main__":
    unittest.main()
