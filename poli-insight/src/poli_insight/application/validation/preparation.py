"""Algorithm-independent conversion of answers into comparison matrices."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from poli_insight.application.ports.validator import (
    PreparedComparisonMatrix,
    ValidationRequest,
)
from poli_insight.domain.enum import QuestionType, ResponseFormat
from poli_insight.domain.submission import SubmissionAnswer
from poli_insight.domain.validation import (
    ValidationNormalizedAnswer,
    ValidationPreparedMatrix,
)

_STORAGE_QUANTUM = Decimal("1e-18")


def _stored_decimal(value: Decimal) -> Decimal:
    quantized = value.quantize(_STORAGE_QUANTUM)
    return Decimal(0) if quantized.is_zero() else quantized.normalize()


def _decimal_string(value: Decimal) -> str:
    """Serialize a finite matrix value without exponent ambiguity."""

    normalized = Decimal(0) if value.is_zero() else value.normalize()
    return format(normalized, "f")


@dataclass(frozen=True, slots=True)
class PreparationFinding:
    code: str
    safe_message: str
    question_definition_id: str | None = None


class InputPreparationError(ValueError):
    """Expected structural failure in participant-authored input."""

    def __init__(
        self,
        findings: tuple[PreparationFinding, ...],
        *,
        completion_ratio: Decimal,
    ) -> None:
        self.findings = findings
        self.completion_ratio = completion_ratio
        super().__init__(findings[0].safe_message if findings else "Invalid input.")


class CrispSubmissionInputPreparer:
    """Prepare crisp direct-rating and pairwise criterion matrices."""

    version = "crisp-comparison-matrix-v1"

    def prepare(self, request: ValidationRequest) -> PreparedComparisonMatrix:
        configuration = request.configuration
        if configuration.response_format not in {
            ResponseFormat.DIRECT_RATING,
            ResponseFormat.PAIRWISE,
        }:
            raise InputPreparationError(
                (
                    PreparationFinding(
                        "response_format.unsupported",
                        "The configured response format is not supported for weighting.",
                    ),
                ),
                completion_ratio=Decimal(0),
            )

        questions = tuple(
            sorted(
                configuration.question_definitions,
                key=lambda item: (item.display_order, item.question_definition_id),
            )
        )
        answers_by_question = {
            answer.question_definition_id: answer
            for answer in request.submission.answers
        }
        required = tuple(question for question in questions if question.required)
        answered_required = sum(
            question.question_definition_id in answers_by_question
            for question in required
        )
        completion = (
            Decimal(1)
            if not required
            else Decimal(answered_required) / Decimal(len(required))
        )
        missing = tuple(
            question
            for question in required
            if question.question_definition_id not in answers_by_question
        )
        if missing:
            raise InputPreparationError(
                tuple(
                    PreparationFinding(
                        "answers.required_missing",
                        "A required response is missing.",
                        question.question_definition_id,
                    )
                    for question in missing
                ),
                completion_ratio=completion,
            )

        criterion_ids = self._criterion_order(request)
        if configuration.response_format == ResponseFormat.DIRECT_RATING:
            return self._prepare_direct(
                request, questions, answers_by_question, criterion_ids
            )
        return self._prepare_pairwise(
            request, questions, answers_by_question, criterion_ids
        )

    def _criterion_order(self, request: ValidationRequest) -> tuple[str, ...]:
        referenced: set[str] = set()
        for question in request.configuration.question_definitions:
            if (
                request.configuration.response_format
                == ResponseFormat.DIRECT_RATING
                and question.question_type
                == QuestionType.CRITERION_RATING
                and question.criterion_id is not None
            ):
                referenced.add(question.criterion_id)
            if (
                request.configuration.response_format
                == ResponseFormat.PAIRWISE
                and question.question_type == QuestionType.CRITERION_PAIR
            ):
                if question.left_criterion_id is not None:
                    referenced.add(question.left_criterion_id)
                if question.right_criterion_id is not None:
                    referenced.add(question.right_criterion_id)
        ordered = tuple(
            criterion.criterion_id
            for criterion in sorted(
                request.scenario_snapshot.criteria,
                key=lambda item: (item.display_order, item.criterion_id),
            )
            if criterion.criterion_id in referenced
        )
        if not ordered or set(ordered) != referenced:
            raise InputPreparationError(
                (
                    PreparationFinding(
                        "criteria.invalid",
                        "The response questions do not reference a valid criterion set.",
                    ),
                ),
                completion_ratio=Decimal(0),
            )
        return ordered

    def _prepare_direct(
        self,
        request: ValidationRequest,
        questions: tuple,
        answers_by_question: dict,
        criterion_ids: tuple[str, ...],
    ) -> PreparedComparisonMatrix:
        rating_questions = tuple(
            question
            for question in questions
            if question.question_type == QuestionType.CRITERION_RATING
        )
        question_by_criterion = {
            question.criterion_id: question
            for question in rating_questions
        }
        if (
            set(question_by_criterion) != set(criterion_ids)
            or len(question_by_criterion) != len(rating_questions)
        ):
            raise InputPreparationError(
                (
                    PreparationFinding(
                        "criteria.rating_coverage",
                        "Direct ratings must contain one question per criterion.",
                    ),
                ),
                completion_ratio=Decimal(0),
            )
        ratings: list[Decimal] = []
        resolved: list[tuple[SubmissionAnswer, Decimal]] = []
        for criterion_id in criterion_ids:
            question = question_by_criterion[criterion_id]
            answer = answers_by_question[question.question_definition_id]
            value = self._resolve_value(request, question, answer)
            if value <= 0:
                raise self._positive_value_error(question.question_definition_id)
            ratings.append(value)
            resolved.append((answer, value))
        total = sum(ratings, Decimal(0))
        normalized = tuple(value / total for value in ratings)
        # q_j / q_k is algebraically r_j / r_k. Use the latter form to avoid
        # Decimal context rounding twice while still retaining q as evidence.
        values = tuple(
            tuple(left / right for right in ratings) for left in ratings
        )
        normalized_answers = tuple(
            ValidationNormalizedAnswer(
                validation_id=request.validation_id,
                submission_answer_id=answer.submission_answer_id,
                normalized_value_json={
                    "resolved_rating": rating,
                    "normalized_rating": normalized[index],
                    "canonical_crisp_value": _stored_decimal(
                        normalized[index]
                    ),
                },
                normalizer_version=self.version,
                crisp_value=_stored_decimal(normalized[index]),
            )
            for index, (answer, rating) in enumerate(resolved)
        )
        return self._result(request, criterion_ids, values, normalized_answers)

    def _prepare_pairwise(
        self,
        request: ValidationRequest,
        questions: tuple,
        answers_by_question: dict,
        criterion_ids: tuple[str, ...],
    ) -> PreparedComparisonMatrix:
        index = {
            criterion_id: position
            for position, criterion_id in enumerate(criterion_ids)
        }
        expected_pairs = tuple(
            (criterion_ids[left], criterion_ids[right])
            for left in range(len(criterion_ids))
            for right in range(left + 1, len(criterion_ids))
        )
        pair_questions = tuple(
            question
            for question in questions
            if question.question_type == QuestionType.CRITERION_PAIR
        )
        question_by_pair = {
            frozenset(
                (question.left_criterion_id, question.right_criterion_id)
            ): question
            for question in pair_questions
        }
        if (
            set(question_by_pair)
            != {frozenset(pair) for pair in expected_pairs}
            or len(question_by_pair) != len(pair_questions)
        ):
            raise InputPreparationError(
                (
                    PreparationFinding(
                        "criteria.pairwise_coverage",
                        "Pairwise responses must cover every criterion pair exactly once.",
                    ),
                ),
                completion_ratio=Decimal(0),
            )
        matrix = [
            [Decimal(1) if row == column else Decimal(0) for column in range(len(criterion_ids))]
            for row in range(len(criterion_ids))
        ]
        normalized_answers: list[ValidationNormalizedAnswer] = []
        for pair in expected_pairs:
            question = question_by_pair[frozenset(pair)]
            answer = answers_by_question[question.question_definition_id]
            value = self._resolve_value(request, question, answer)
            if value <= 0:
                raise self._positive_value_error(question.question_definition_id)
            left_criterion_id = question.left_criterion_id
            right_criterion_id = question.right_criterion_id
            if (
                left_criterion_id not in index
                or right_criterion_id not in index
            ):
                raise InputPreparationError(
                    (
                        PreparationFinding(
                            "criteria.pairwise_foreign",
                            "A pairwise response references an unknown criterion.",
                            question.question_definition_id,
                        ),
                    ),
                    completion_ratio=Decimal(0),
                )
            left = index[left_criterion_id]
            right = index[right_criterion_id]
            matrix[left][right] = value
            matrix[right][left] = Decimal(1) / value
            normalized_answers.append(
                ValidationNormalizedAnswer(
                    validation_id=request.validation_id,
                    submission_answer_id=answer.submission_answer_id,
                    normalized_value_json={
                        "pairwise_ratio": value,
                        "canonical_crisp_value": _stored_decimal(value),
                        "left_criterion_id": left_criterion_id,
                        "right_criterion_id": right_criterion_id,
                    },
                    normalizer_version=self.version,
                    crisp_value=_stored_decimal(value),
                )
            )
        return self._result(
            request,
            criterion_ids,
            tuple(tuple(row) for row in matrix),
            tuple(normalized_answers),
        )

    def _result(
        self,
        request: ValidationRequest,
        criterion_ids: tuple[str, ...],
        values: tuple[tuple[Decimal, ...], ...],
        normalized_answers: tuple[ValidationNormalizedAnswer, ...],
    ) -> PreparedComparisonMatrix:
        matrix = ValidationPreparedMatrix.create(
            validation_id=request.validation_id,
            response_format=request.configuration.response_format.value,
            value_shape="crisp",
            criterion_ids=criterion_ids,
            matrix_json={
                "values": [
                    [_decimal_string(value) for value in row]
                    for row in values
                ]
            },
            preparer_version=self.version,
        )
        return PreparedComparisonMatrix(matrix, normalized_answers)

    @staticmethod
    def _resolve_value(request: ValidationRequest, question, answer) -> Decimal:
        if answer.numeric_value is not None:
            if not answer.numeric_value.is_finite():
                raise InputPreparationError(
                    (
                        PreparationFinding(
                            "answers.numeric_nonfinite",
                            "A numeric response must be finite.",
                            question.question_definition_id,
                        ),
                    ),
                    completion_ratio=Decimal(1),
                )
            return answer.numeric_value
        selected_id = answer.selected_scale_value_id
        for scale in request.scenario_snapshot.scales:
            if scale.scale_id != question.scale_id:
                continue
            for scale_value in scale.values:
                if scale_value.scale_value_id == selected_id:
                    if scale_value.numeric_value is None:
                        break
                    return scale_value.numeric_value
        raise InputPreparationError(
            (
                PreparationFinding(
                    "answers.scale_value_invalid",
                    "A response references an unavailable numeric scale value.",
                    question.question_definition_id,
                ),
            ),
            completion_ratio=Decimal(1),
        )

    @staticmethod
    def _positive_value_error(question_definition_id: str) -> InputPreparationError:
        return InputPreparationError(
            (
                PreparationFinding(
                    "answers.nonpositive",
                    "A comparison value must be greater than zero.",
                    question_definition_id,
                ),
            ),
            completion_ratio=Decimal(1),
        )
