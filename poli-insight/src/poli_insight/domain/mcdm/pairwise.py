from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from numbers import Real

from poli_insight.domain.enums import (
    PreferenceElicitationMethod,
    ScenarioType,
)
from poli_insight.domain.mcdm.preference_scale import (
    PreferenceScaleDefinition,
    PreferenceScaleError,
    TriangularFuzzyNumber,
    UnknownPreferenceScaleError,
    get_option,
    validate_scale,
)

CriterionPair = tuple[str, str]
CrispPairwiseMatrix = tuple[tuple[float, ...], ...]
FuzzyPairwiseMatrix = tuple[
    tuple[TriangularFuzzyNumber, ...],
    ...,
]


class PairwiseRuleViolation(ValueError):
    """Raised when pairwise questions or answers violate a domain rule."""


@dataclass(frozen=True, slots=True)
class PairwiseQuestion:
    left_criterion_id: str
    right_criterion_id: str

    @property
    def pair(self) -> CriterionPair:
        return (self.left_criterion_id, self.right_criterion_id)


@dataclass(frozen=True, slots=True)
class PairwiseAnswer:
    left_criterion_id: str
    right_criterion_id: str
    option_id: str

    @property
    def pair(self) -> CriterionPair:
        return (self.left_criterion_id, self.right_criterion_id)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> PairwiseAnswer:
        """Deserialize the canonical pairwise-answer payload shape."""

        try:
            left_criterion_id = value["left_criterion_id"]
            right_criterion_id = value["right_criterion_id"]
            option_id = value["option_id"]
        except KeyError as error:
            raise PairwiseRuleViolation(
                f"Pairwise answer is missing {error.args[0]!r}."
            ) from error

        if (
            not isinstance(left_criterion_id, str)
            or not isinstance(right_criterion_id, str)
            or not isinstance(option_id, str)
        ):
            raise PairwiseRuleViolation("Pairwise answer IDs must be strings.")

        return cls(
            left_criterion_id=left_criterion_id,
            right_criterion_id=right_criterion_id,
            option_id=option_id,
        )


@dataclass(frozen=True, slots=True)
class PairwiseValidationDiagnostics:
    expected_question_count: int
    submitted_answer_count: int
    missing_pairs: tuple[CriterionPair, ...] = ()
    duplicate_pairs: tuple[CriterionPair, ...] = ()
    reversed_pairs: tuple[CriterionPair, ...] = ()
    unknown_pairs: tuple[CriterionPair, ...] = ()
    self_comparisons: tuple[CriterionPair, ...] = ()
    unknown_options: tuple[tuple[str, str, str], ...] = ()
    scale_errors: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return not self.errors

    @property
    def completion_ratio(self) -> float:
        if self.expected_question_count == 0:
            return 1.0

        completed = self.expected_question_count - len(self.missing_pairs)
        return completed / self.expected_question_count

    @property
    def errors(self) -> tuple[str, ...]:
        errors: list[str] = list(self.scale_errors)
        errors.extend(
            f"Missing comparison {left!r} vs {right!r}."
            for left, right in self.missing_pairs
        )
        errors.extend(
            f"Duplicate comparison {left!r} vs {right!r}."
            for left, right in self.duplicate_pairs
        )
        errors.extend(
            "Reversed comparison "
            f"{left!r} vs {right!r}; submit it in the generated order."
            for left, right in self.reversed_pairs
        )
        errors.extend(
            f"Comparison references unknown criteria: {left!r} vs {right!r}."
            for left, right in self.unknown_pairs
        )
        errors.extend(
            f"A criterion cannot be compared with itself: {left!r}."
            for left, _ in self.self_comparisons
        )
        errors.extend(
            f"Unknown scale option {option_id!r} for {left!r} vs {right!r}."
            for left, right, option_id in self.unknown_options
        )
        return tuple(errors)

    def require_valid(self) -> None:
        if not self.is_valid:
            raise PairwiseRuleViolation(" ".join(self.errors))


def sort_criteria(
    criteria: Iterable[Mapping[str, object]],
    *,
    scenario_type: ScenarioType = ScenarioType.STANDARD,
) -> tuple[str, ...]:
    """Return criterion IDs ordered by display order and then by ID."""

    if scenario_type == ScenarioType.HIERARCHICAL:
        raise PairwiseRuleViolation(
            "Hierarchical scenarios are not supported until questions can "
            "be generated separately for each sibling group."
        )
    if scenario_type != ScenarioType.STANDARD:
        raise PairwiseRuleViolation(f"Unsupported scenario type: {scenario_type!r}.")

    sortable: list[tuple[float, str]] = []
    seen_ids: set[str] = set()

    for criterion in criteria:
        try:
            criterion_id = criterion["id"]
            display_order = criterion["display_order"]
        except KeyError as error:
            raise PairwiseRuleViolation(
                f"Criterion is missing {error.args[0]!r}."
            ) from error

        if not isinstance(criterion_id, str) or not criterion_id.strip():
            raise PairwiseRuleViolation("Criterion ID must be a non-blank string.")
        if criterion_id in seen_ids:
            raise PairwiseRuleViolation(f"Duplicate criterion ID: {criterion_id!r}.")
        seen_ids.add(criterion_id)

        if (
            not isinstance(display_order, Real)
            or isinstance(display_order, bool)
            or not math.isfinite(float(display_order))
        ):
            raise PairwiseRuleViolation(
                f"Criterion display_order must be a finite number for {criterion_id!r}."
            )

        sortable.append((float(display_order), criterion_id))

    if not sortable:
        raise PairwiseRuleViolation(
            "At least one criterion is required for pairwise comparison."
        )

    sortable.sort(key=lambda item: (item[0], item[1]))
    return tuple(criterion_id for _, criterion_id in sortable)


def expected_question_count(criterion_count: int) -> int:
    """Return n(n-1)/2, the number of unique unordered pairs."""

    if (
        not isinstance(criterion_count, int)
        or isinstance(criterion_count, bool)
        or criterion_count < 0
    ):
        raise PairwiseRuleViolation("Criterion count must be a non-negative integer.")
    return criterion_count * (criterion_count - 1) // 2


def generate_pairwise_questions(
    criteria_order: Sequence[str],
) -> tuple[PairwiseQuestion, ...]:
    """Generate every unique comparison in canonical orientation."""

    normalized_order = _validate_criteria_order(criteria_order)
    return tuple(
        PairwiseQuestion(left, right)
        for left, right in combinations(normalized_order, 2)
    )


def validate_pairwise_answers(
    criteria_order: Sequence[str],
    answers: Sequence[PairwiseAnswer],
    scale: PreferenceScaleDefinition,
) -> PairwiseValidationDiagnostics:
    """Validate coverage, orientation, uniqueness, and scale options."""

    normalized_order = _validate_criteria_order(criteria_order)
    expected_pairs = tuple(
        question.pair for question in generate_pairwise_questions(normalized_order)
    )
    expected_pair_set = set(expected_pairs)
    criterion_ids = set(normalized_order)
    exact_pair_counts: Counter[CriterionPair] = Counter()
    reversed_pairs: list[CriterionPair] = []
    unknown_pairs: list[CriterionPair] = []
    self_comparisons: list[CriterionPair] = []
    unknown_options: list[tuple[str, str, str]] = []

    scale_errors = _pairwise_scale_errors(scale)

    for answer in answers:
        if not isinstance(answer, PairwiseAnswer):
            raise PairwiseRuleViolation("Answers must be PairwiseAnswer instances.")

        pair = answer.pair
        left, right = pair

        if left == right:
            self_comparisons.append(pair)
        elif left not in criterion_ids or right not in criterion_ids:
            unknown_pairs.append(pair)
        elif pair in expected_pair_set:
            exact_pair_counts[pair] += 1
        elif (right, left) in expected_pair_set:
            reversed_pairs.append(pair)
        else:
            unknown_pairs.append(pair)

        try:
            get_option(scale, answer.option_id)
        except (UnknownPreferenceScaleError, AttributeError):
            unknown_options.append((left, right, answer.option_id))

    missing_pairs = tuple(
        pair for pair in expected_pairs if exact_pair_counts[pair] == 0
    )
    duplicate_pairs = tuple(
        pair for pair in expected_pairs if exact_pair_counts[pair] > 1
    )

    return PairwiseValidationDiagnostics(
        expected_question_count=len(expected_pairs),
        submitted_answer_count=len(answers),
        missing_pairs=missing_pairs,
        duplicate_pairs=duplicate_pairs,
        reversed_pairs=tuple(reversed_pairs),
        unknown_pairs=tuple(unknown_pairs),
        self_comparisons=tuple(self_comparisons),
        unknown_options=tuple(unknown_options),
        scale_errors=scale_errors,
    )


def build_crisp_pairwise_matrix(
    criteria_order: tuple[str, ...],
    answers: tuple[PairwiseAnswer, ...],
    scale: PreferenceScaleDefinition,
) -> CrispPairwiseMatrix:
    """Construct a complete reciprocal AHP matrix from pairwise answers."""

    diagnostics = validate_pairwise_answers(
        criteria_order,
        answers,
        scale,
    )
    diagnostics.require_valid()

    size = len(criteria_order)
    indexes = {criterion_id: index for index, criterion_id in enumerate(criteria_order)}
    matrix = [[1.0 for _ in range(size)] for _ in range(size)]

    for answer in answers:
        row = indexes[answer.left_criterion_id]
        column = indexes[answer.right_criterion_id]
        value = float(get_option(scale, answer.option_id).numeric_value)
        matrix[row][column] = value
        matrix[column][row] = 1.0 / value

    result = tuple(tuple(row) for row in matrix)
    _assert_crisp_matrix_invariants(result)
    return result


def build_fuzzy_pairwise_matrix(
    criteria_order: tuple[str, ...],
    answers: tuple[PairwiseAnswer, ...],
    scale: PreferenceScaleDefinition,
) -> FuzzyPairwiseMatrix:
    """Construct a complete triangular-fuzzy reciprocal AHP matrix."""

    diagnostics = validate_pairwise_answers(
        criteria_order,
        answers,
        scale,
    )
    diagnostics.require_valid()

    size = len(criteria_order)
    indexes = {criterion_id: index for index, criterion_id in enumerate(criteria_order)}
    equality = TriangularFuzzyNumber(1.0, 1.0, 1.0)
    matrix = [[equality for _ in range(size)] for _ in range(size)]

    for answer in answers:
        row = indexes[answer.left_criterion_id]
        column = indexes[answer.right_criterion_id]
        value = get_option(scale, answer.option_id).fuzzy_value
        matrix[row][column] = value
        matrix[column][row] = reciprocal_fuzzy_number(value)

    result = tuple(tuple(row) for row in matrix)
    _assert_fuzzy_matrix_invariants(result)
    return result


def reciprocal_fuzzy_number(
    value: TriangularFuzzyNumber,
) -> TriangularFuzzyNumber:
    """Return the reciprocal of a positive triangular fuzzy number."""

    if value.lower <= 0:
        raise PairwiseRuleViolation(
            "A triangular fuzzy reciprocal requires positive components."
        )

    return TriangularFuzzyNumber(
        lower=1.0 / value.upper,
        modal=1.0 / value.modal,
        upper=1.0 / value.lower,
    )


def _validate_criteria_order(
    criteria_order: Sequence[str],
) -> tuple[str, ...]:
    normalized = tuple(criteria_order)
    if not normalized:
        raise PairwiseRuleViolation(
            "At least one criterion is required for pairwise comparison."
        )
    if any(
        not isinstance(criterion_id, str) or not criterion_id.strip()
        for criterion_id in normalized
    ):
        raise PairwiseRuleViolation("Criterion IDs must be non-blank strings.")
    if len(normalized) != len(set(normalized)):
        raise PairwiseRuleViolation("Criteria order cannot contain duplicate IDs.")
    return normalized


def _pairwise_scale_errors(
    scale: PreferenceScaleDefinition,
) -> tuple[str, ...]:
    errors: list[str] = []
    if scale.elicitation_method != PreferenceElicitationMethod.PAIRWISE_COMPARISON:
        errors.append(
            "Pairwise matrix construction requires a pairwise-comparison scale."
        )

    try:
        validate_scale(scale)
    except PreferenceScaleError as error:
        errors.append(str(error))

    return tuple(errors)


def _assert_crisp_matrix_invariants(
    matrix: CrispPairwiseMatrix,
) -> None:
    size = len(matrix)
    if any(len(row) != size for row in matrix):
        raise PairwiseRuleViolation("Pairwise matrix must be square.")

    for row in range(size):
        if not math.isclose(matrix[row][row], 1.0):
            raise PairwiseRuleViolation(
                "Crisp pairwise matrix diagonal must contain ones."
            )
        for column in range(row + 1, size):
            if not math.isclose(
                matrix[row][column] * matrix[column][row],
                1.0,
                rel_tol=1e-9,
                abs_tol=1e-9,
            ):
                raise PairwiseRuleViolation("Crisp pairwise matrix must be reciprocal.")


def _assert_fuzzy_matrix_invariants(
    matrix: FuzzyPairwiseMatrix,
) -> None:
    size = len(matrix)
    if any(len(row) != size for row in matrix):
        raise PairwiseRuleViolation("Pairwise matrix must be square.")

    equality = (1.0, 1.0, 1.0)
    for row in range(size):
        diagonal = matrix[row][row]
        if not _fuzzy_components_close(diagonal, equality):
            raise PairwiseRuleViolation(
                "Fuzzy pairwise matrix diagonal must contain (1, 1, 1)."
            )
        for column in range(row + 1, size):
            expected = reciprocal_fuzzy_number(matrix[row][column])
            actual = matrix[column][row]
            if not _fuzzy_components_close(
                actual,
                (expected.lower, expected.modal, expected.upper),
            ):
                raise PairwiseRuleViolation("Fuzzy pairwise matrix must be reciprocal.")


def _fuzzy_components_close(
    value: TriangularFuzzyNumber,
    expected: tuple[float, float, float],
) -> bool:
    return all(
        math.isclose(actual, target, rel_tol=1e-9, abs_tol=1e-9)
        for actual, target in zip(
            (value.lower, value.modal, value.upper),
            expected,
            strict=True,
        )
    )
