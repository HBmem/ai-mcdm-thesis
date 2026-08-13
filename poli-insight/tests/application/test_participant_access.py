from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import poli_insight.domain.session as session_module
from poli_insight.application.use_cases.participant_access import require_consent
from poli_insight.domain.participation import Participant


def test_consent_guard_accepts_configuration_created_before_module_reload(
    monkeypatch,
) -> None:
    configuration = object.__new__(session_module.SessionConfigurationVersion)
    object.__setattr__(configuration, "configuration_json", {})
    object.__setattr__(
        configuration,
        "configuration_version_id",
        "configuration-1",
    )
    monkeypatch.setattr(
        session_module,
        "SessionConfigurationVersion",
        type("ReloadedSessionConfigurationVersion", (), {}),
    )
    unit_of_work = SimpleNamespace(consents=Mock())
    participant = cast(
        Participant,
        SimpleNamespace(participant_id="participant-1"),
    )

    require_consent(unit_of_work, participant, configuration)

    unit_of_work.consents.get_for_participant.assert_not_called()
