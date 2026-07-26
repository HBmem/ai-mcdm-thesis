from __future__ import annotations

import math

import pytest

from poli_insight.domain.enums import ScenarioType
from poli_insight.domain.mcdm.pairwise import (
    PairwiseAnswer,
    PairwiseRuleViolation,
    build_crisp_pairwise_matrix,
    build_fuzzy_pairwise_matrix,
    expected_question_count,
    generate_pairwise_questions,
    sort_criteria,
    validate_pairwise_answers,
)
from poli_insight.domain.mcdm.preference_scale import (
    DIRECT_FIVE_POINT,
    PAIRWISE_FIVE_POINT,
    TriangularFuzzyNumber,
)

CRITERIA_ORDER = ("cost", "safety", "trust")
COMPLETE_ANSWERS = (
    PairwiseAnswer("cost", "safety", "pairwise_2"),
    PairwiseAnswer("cost", "trust", "pairwise_3"),
    PairwiseAnswer("safety", "trust", "pairwise_4"),
)


def test_sort_criteria_uses_display_order_then_id() -> None:
    criteria = (
        {"id": "trust", "display_order": 2},
        {"id": "safety", "display_order": 2},
        {"id": "cost", "display_order": 1},
    )

    assert sort_criteria(criteria) == ("cost", "safety", "trust")


def test_sort_criteria_rejects_hierarchical_scenarios() -> None:
    with pytest.raises(PairwiseRuleViolation, match="Hierarchical"):
        sort_criteria(
            ({"id": "cost", "display_order": 1},),
            scenario_type=ScenarioType.HIERARCHICAL,
        )


def test_generate_all_unique_questions_in_canonical_order() -> None:
    questions = generate_pairwise_questions(CRITERIA_ORDER)

    assert expected_question_count(len(CRITERIA_ORDER)) == 3
    assert tuple(question.pair for question in questions) == (
        ("cost", "safety"),
        ("cost", "trust"),
        ("safety", "trust"),
    )


def test_validate_complete_answers() -> None:
    diagnostics = validate_pairwise_answers(
        CRITERIA_ORDER,
        COMPLETE_ANSWERS,
        PAIRWISE_FIVE_POINT,
    )

    assert diagnostics.is_valid
    assert diagnostics.completion_ratio == 1.0
    assert diagnostics.errors == ()


def test_validate_reports_missing_duplicate_and_reversed_pairs() -> None:
    answers = (
        PairwiseAnswer("cost", "safety", "pairwise_2"),
        PairwiseAnswer("cost", "safety", "pairwise_3"),
        PairwiseAnswer("trust", "cost", "pairwise_4"),
    )

    diagnostics = validate_pairwise_answers(
        CRITERIA_ORDER,
        answers,
        PAIRWISE_FIVE_POINT,
    )

    assert not diagnostics.is_valid
    assert diagnostics.missing_pairs == (
        ("cost", "trust"),
        ("safety", "trust"),
    )
    assert diagnostics.duplicate_pairs == (("cost", "safety"),)
    assert diagnostics.reversed_pairs == (("trust", "cost"),)


def test_validate_reports_unknown_self_and_option_errors() -> None:
    answers = (
        PairwiseAnswer("cost", "missing", "not_an_option"),
        PairwiseAnswer("safety", "safety", "pairwise_3"),
    )

    diagnostics = validate_pairwise_answers(
        CRITERIA_ORDER,
        answers,
        PAIRWISE_FIVE_POINT,
    )

    assert diagnostics.unknown_pairs == (("cost", "missing"),)
    assert diagnostics.self_comparisons == (("safety", "safety"),)
    assert diagnostics.unknown_options == (("cost", "missing", "not_an_option"),)


def test_build_crisp_reciprocal_matrix() -> None:
    matrix = build_crisp_pairwise_matrix(
        CRITERIA_ORDER,
        COMPLETE_ANSWERS,
        PAIRWISE_FIVE_POINT,
    )

    assert matrix == (
        (1.0, 3.0, 1.0),
        (1 / 3, 1.0, 1 / 3),
        (1.0, 3.0, 1.0),
    )


def test_build_fuzzy_reciprocal_matrix() -> None:
    matrix = build_fuzzy_pairwise_matrix(
        CRITERIA_ORDER,
        COMPLETE_ANSWERS,
        PAIRWISE_FIVE_POINT,
    )

    assert matrix[0][1] == TriangularFuzzyNumber(2, 3, 4)
    assert matrix[1][0] == TriangularFuzzyNumber(1 / 4, 1 / 3, 1 / 2)
    assert matrix[1][2] == TriangularFuzzyNumber(1 / 4, 1 / 3, 1 / 2)
    assert matrix[2][1] == TriangularFuzzyNumber(2, 3, 4)
    assert all(math.isclose(matrix[index][index].modal, 1.0) for index in range(3))


def test_matrix_builder_rejects_direct_rating_scale() -> None:
    with pytest.raises(
        PairwiseRuleViolation,
        match="pairwise-comparison scale",
    ):
        build_crisp_pairwise_matrix(
            CRITERIA_ORDER,
            COMPLETE_ANSWERS,
            DIRECT_FIVE_POINT,
        )


def test_pairwise_answer_deserializes_canonical_payload() -> None:
    answer = PairwiseAnswer.from_mapping(
        {
            "left_criterion_id": "cost",
            "right_criterion_id": "safety",
            "option_id": "pairwise_2",
        }
    )

    assert answer == PairwiseAnswer("cost", "safety", "pairwise_2")
