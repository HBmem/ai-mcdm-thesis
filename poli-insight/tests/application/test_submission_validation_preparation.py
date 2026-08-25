from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from poli_insight.application.validation.preparation import (
    CrispSubmissionInputPreparer,
    InputPreparationError,
)
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    CriterionDataType,
    CriterionDirection,
    QuestionType,
    ResponseFormat,
)
from poli_insight.domain.scenario import (
    ScenarioCriterion,
    ScenarioScale,
    ScenarioScaleValue,
)
from poli_insight.domain.session import ResponseQuestionDefinition
from poli_insight.domain.submission import SubmissionAnswer

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _criterion(criterion_id: str, order: int) -> ScenarioCriterion:
    return ScenarioCriterion(
        criterion_id=criterion_id,
        criterion_key=criterion_id,
        name=criterion_id,
        direction=CriterionDirection.BENEFIT,
        data_type=CriterionDataType.ORDINAL,
        display_order=order,
    )


def _question(question_id: str, criterion_id: str, order: int):
    return ResponseQuestionDefinition(
        question_definition_id=question_id,
        configuration_version_id="configuration-1",
        question_key=question_id,
        question_type=QuestionType.CRITERION_RATING,
        display_order=order,
        required=True,
        prompt_snapshot=question_id,
        criterion_id=criterion_id,
        scale_id="scale-1",
    )


def _answer(answer_id: str, question, scale_value_id: str):
    raw = {"selected_scale_value_id": scale_value_id}
    return SubmissionAnswer(
        submission_answer_id=answer_id,
        submission_id="submission-1",
        question_definition_id=question.question_definition_id,
        raw_value_json=raw,
        value_schema_version=1,
        raw_value_hash=hash_json(raw),
        answered_at=NOW,
        selected_scale_value_id=scale_value_id,
    )


def _request(ratings: tuple[Decimal, ...]):
    criteria = tuple(
        _criterion(f"criterion-{index}", index)
        for index in range(len(ratings))
    )
    questions = tuple(
        _question(f"question-{index}", criterion.criterion_id, index)
        for index, criterion in enumerate(criteria)
    )
    scale_values = tuple(
        ScenarioScaleValue(
            scale_value_id=f"value-{index}",
            scale_id="scale-1",
            stable_value_key=f"value-{index}",
            label=f"Value {index}",
            ordinal=index,
            metadata_json={},
            numeric_value=rating,
        )
        for index, rating in enumerate(ratings)
    )
    scale = ScenarioScale(
        scale_id="scale-1",
        scale_key="scale",
        name="Scale",
        scale_type="numeric",
        ordered=True,
        definition_version=1,
        metadata_json={},
        values=scale_values,
    )
    return SimpleNamespace(
        validation_id="validation-1",
        configuration=SimpleNamespace(
            response_format=ResponseFormat.DIRECT_RATING,
            question_definitions=questions,
        ),
        submission=SimpleNamespace(
            answers=tuple(
                _answer(f"answer-{index}", question, f"value-{index}")
                for index, question in enumerate(questions)
            )
        ),
        scenario_snapshot=SimpleNamespace(criteria=criteria, scales=(scale,)),
    )


def test_direct_ratings_are_normalized_then_converted_to_reciprocal_matrix():
    prepared = CrispSubmissionInputPreparer().prepare(
        _request((Decimal(2), Decimal(4), Decimal(8)))
    )

    assert prepared.values == (
        (Decimal(1), Decimal("0.5"), Decimal("0.25")),
        (Decimal(2), Decimal(1), Decimal("0.5")),
        (Decimal(4), Decimal(2), Decimal(1)),
    )
    assert [item.crisp_value for item in prepared.normalized_answers] == [
        Decimal("0.142857142857142857"),
        Decimal("0.285714285714285714"),
        Decimal("0.571428571428571429"),
    ]


def test_direct_rating_matrix_is_scale_invariant():
    preparer = CrispSubmissionInputPreparer()
    first = preparer.prepare(_request((Decimal(2), Decimal(4), Decimal(8))))
    second = preparer.prepare(_request((Decimal(20), Decimal(40), Decimal(80))))

    assert first.values == second.values


def test_nonpositive_direct_rating_is_structurally_invalid():
    with pytest.raises(InputPreparationError, match="greater than zero"):
        CrispSubmissionInputPreparer().prepare(
            _request((Decimal(1), Decimal(0), Decimal(2)))
        )


def test_duplicate_direct_question_for_criterion_is_structurally_invalid():
    request = _request((Decimal(1), Decimal(2)))
    original = request.configuration.question_definitions[0]
    duplicate = replace(
        original,
        question_definition_id="question-duplicate",
        question_key="question-duplicate",
    )
    duplicate_answer = _answer(
        "answer-duplicate",
        duplicate,
        "value-0",
    )
    request.configuration.question_definitions = (
        *request.configuration.question_definitions,
        duplicate,
    )
    request.submission.answers = (
        *request.submission.answers,
        duplicate_answer,
    )

    with pytest.raises(InputPreparationError, match="one question per criterion"):
        CrispSubmissionInputPreparer().prepare(request)


def test_pairwise_orientation_uses_question_left_and_right_targets():
    criteria = (
        _criterion("criterion-z", 0),
        _criterion("criterion-a", 1),
    )
    question = ResponseQuestionDefinition(
        question_definition_id="question-pair",
        configuration_version_id="configuration-1",
        question_key="question-pair",
        question_type=QuestionType.CRITERION_PAIR,
        display_order=0,
        required=True,
        prompt_snapshot="Compare criteria",
        left_criterion_id="criterion-a",
        right_criterion_id="criterion-z",
        scale_id="scale-1",
    )
    raw = {"numeric_value": "3"}
    answer = SubmissionAnswer(
        submission_answer_id="answer-pair",
        submission_id="submission-1",
        question_definition_id=question.question_definition_id,
        raw_value_json=raw,
        value_schema_version=1,
        raw_value_hash=hash_json(raw),
        answered_at=NOW,
        numeric_value=Decimal(3),
    )
    request = SimpleNamespace(
        validation_id="validation-1",
        configuration=SimpleNamespace(
            response_format=ResponseFormat.PAIRWISE,
            question_definitions=(question,),
        ),
        submission=SimpleNamespace(answers=(answer,)),
        scenario_snapshot=SimpleNamespace(criteria=criteria, scales=()),
    )

    prepared = CrispSubmissionInputPreparer().prepare(request)

    assert prepared.criterion_ids == ("criterion-z", "criterion-a")
    assert prepared.values == (
        (Decimal(1), Decimal(1) / Decimal(3)),
        (Decimal(3), Decimal(1)),
    )
