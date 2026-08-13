from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from poli_insight.application.queries.page_queries import (
    AuthoredAnswerDetail,
    CriterionWeightDetail,
)
from poli_insight.domain.enum import QuestionType, ResponseFormat, ValidationStatus
from poli_insight.presentation.streamlit.pages.admin.manage_sessions import (
    _safe_submission_json,
    _submission_matrix_rows,
    _submission_response_rows,
)

NOW = datetime(2026, 8, 5, 12, tzinfo=UTC)


def _answer(
    order: int,
    *,
    criterion_id: str | None = None,
    criterion_label: str | None = None,
    left_id: str | None = None,
    left_label: str | None = None,
    right_id: str | None = None,
    right_label: str | None = None,
    normalized: str | None = None,
) -> AuthoredAnswerDetail:
    return AuthoredAnswerDetail(
        submission_answer_id=f"answer-{order}",
        question_definition_id=f"question-{order}",
        display_order=order,
        prompt=f"Question {order}",
        question_type=(
            QuestionType.CRITERION_PAIR
            if left_id is not None
            else QuestionType.CRITERION_RATING
        ),
        criterion_id=criterion_id,
        criterion_label=criterion_label,
        left_criterion_id=left_id,
        left_criterion_label=left_label,
        right_criterion_id=right_id,
        right_criterion_label=right_label,
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


def test_direct_rating_rows_show_authored_normalized_and_weights() -> None:
    submission = SimpleNamespace(
        response_format=ResponseFormat.DIRECT_RATING,
        authored_answers=(
            _answer(0, criterion_id="cost", criterion_label="Cost", normalized="0.25"),
            _answer(1, criterion_id="access", criterion_label="Access", normalized="0.75"),
        ),
        criterion_weights=(
            CriterionWeightDetail("cost", "Cost", 0, "0.25", None, None, None, {}),
            CriterionWeightDetail("access", "Access", 1, "0.75", None, None, None, {}),
        ),
    )

    responses = _submission_response_rows(submission)
    matrix, note = _submission_matrix_rows(submission)

    assert [row["Target"] for row in responses] == ["Cost", "Access"]
    assert responses[0]["Authored response"] == "Rating 0"
    assert responses[0]["Derived normalized value"] == "0.25"
    assert [row["Criterion"] for row in matrix] == ["Cost", "Access"]
    assert [row["Derived weight"] for row in matrix] == ["0.25", "0.75"]
    assert "authored and derived" in note


def test_pairwise_matrix_is_deterministic_and_does_not_guess_reciprocals() -> None:
    submission = SimpleNamespace(
        response_format=ResponseFormat.PAIRWISE,
        authored_answers=(
            _answer(
                0,
                left_id="cost",
                left_label="Cost",
                right_id="access",
                right_label="Access",
                normalized="3",
            ),
            _answer(
                1,
                left_id="cost",
                left_label="Cost",
                right_id="equity",
                right_label="Equity",
                normalized="5",
            ),
        ),
        criterion_weights=(),
    )

    matrix, note = _submission_matrix_rows(submission)

    assert [row["Criterion"] for row in matrix] == ["Cost", "Access", "Equity"]
    assert matrix[0] == {
        "Criterion": "Cost",
        "Cost": "1",
        "Access": "3",
        "Equity": "5",
    }
    assert matrix[1]["Cost"] == "—"
    assert "reciprocal cells remain blank" in note


def test_incomplete_pairwise_draft_does_not_fabricate_derived_values() -> None:
    submission = SimpleNamespace(
        response_format=ResponseFormat.PAIRWISE,
        authored_answers=(
            _answer(
                0,
                left_id="cost",
                left_label="Cost",
                right_id="access",
                right_label="Access",
                normalized=None,
            ),
        ),
        criterion_weights=(),
    )

    matrix, note = _submission_matrix_rows(submission)

    assert matrix[0]["Access"] == "—"
    assert "unavailable until successful validation" in note


def test_safe_json_export_excludes_credentials_and_unsafe_validation_internals() -> None:
    submission = SimpleNamespace(
        summary=SimpleNamespace(
            submission_id="submission-1",
            participant_label="Participant TEST",
            group_name="Community",
            attempt_number=2,
            status=SimpleNamespace(value="superseded"),
            validation_status=ValidationStatus.VALID,
            consistency_ratio="0.08",
        ),
        participant_id="participant-1",
        response_format=ResponseFormat.DIRECT_RATING,
        answers_hash="a" * 64,
        answer_schema_version=1,
        previous_submission_id="submission-0",
        authored_answers=(
            _answer(0, criterion_id="cost", criterion_label="Cost", normalized="1"),
        ),
        completion_ratio="1",
        consistency_threshold="0.1",
        validator_version="validator-v1",
        validation_messages=("Safe finding",),
        criterion_weights=(
            CriterionWeightDetail("cost", "Cost", 0, "1", None, None, None, {}),
        ),
        access_token="must-not-export",
        token_digest="b" * 64,
        failure_detail="unsafe-validator-stack",
    )

    exported = _safe_submission_json(submission)

    assert "must-not-export" not in exported
    assert "token_digest" not in exported
    assert "unsafe-validator-stack" not in exported
    assert "Safe finding" in exported
