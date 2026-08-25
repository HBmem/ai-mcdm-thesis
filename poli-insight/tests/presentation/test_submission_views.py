from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import AuthoredAnswerDetail
from poli_insight.domain.enum import QuestionType, ResponseFormat
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _safe_submission_json,
    _submission_response_rows,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _answer(order: int, *, normalized: str | None = None) -> AuthoredAnswerDetail:
    return AuthoredAnswerDetail(
        submission_answer_id=f"answer-{order}",
        question_definition_id=f"question-{order}",
        display_order=order,
        prompt=f"Question {order}",
        question_type=QuestionType.CRITERION_RATING,
        criterion_id=f"criterion-{order}",
        criterion_label=f"Criterion {order}",
        left_criterion_id=None,
        left_criterion_label=None,
        right_criterion_id=None,
        right_criterion_label=None,
        alternative_id=None,
        alternative_label=None,
        selected_scale_value_id=f"scale-{order}",
        selected_scale_label=f"Rating {order}",
        selected_scale_numeric_value=str(order + 1),
        raw_value={"selected_scale_value_id": f"scale-{order}"},
        numeric_value=None,
        rank_value=None,
        answered_at=NOW,
        response_time_ms=1500 + order,
        normalized_value=(None if normalized is None else {"crisp": normalized}),
        normalized_crisp_value=normalized,
        normalizer_version=(None if normalized is None else "normalizer-v1"),
    )


def test_manage_submission_rows_only_show_authored_values() -> None:
    submission = SimpleNamespace(authored_answers=(_answer(0, normalized="0.25"),))

    responses = _submission_response_rows(submission)

    assert responses[0]["Target"] == "Criterion 0"
    assert responses[0]["Authored response"] == "Rating 0"
    assert "Derived normalized value" not in responses[0]


def test_safe_json_export_excludes_validation_evidence_and_credentials() -> None:
    submission = SimpleNamespace(
        summary=SimpleNamespace(
            submission_id="submission-1",
            participant_label="Participant TEST",
            group_name="Community",
            attempt_number=2,
            status=SimpleNamespace(value="submitted"),
        ),
        participant_id="participant-1",
        response_format=ResponseFormat.DIRECT_RATING,
        answers_hash="a" * 64,
        answer_schema_version=1,
        previous_submission_id="submission-0",
        authored_answers=(_answer(0, normalized="1"),),
        validation_messages=("must-not-export",),
        criterion_weights=(SimpleNamespace(crisp_weight="1"),),
        access_token="must-not-export",
    )

    exported = json.loads(_safe_submission_json(submission))

    assert set(exported) == {"schema_version", "submission", "responses"}
    assert "validation" not in exported
    assert "normalized_value" not in exported["responses"][0]
    assert "must-not-export" not in json.dumps(exported)
