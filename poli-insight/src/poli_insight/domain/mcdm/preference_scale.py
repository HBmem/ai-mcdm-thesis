from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real

from poli_insight.domain.enums import (
    PreferenceElicitationMethod,
    PreferenceScale,
)


class PreferenceScaleError(ValueError):
    """Base class for invalid preference-scale operations."""


class UnknownPreferenceScaleError(PreferenceScaleError):
    """Raised when a requested scale or option does not exist."""


class InvalidPreferenceScaleError(PreferenceScaleError):
    """Raised when a scale definition violates a domain rule."""


@dataclass(frozen=True, slots=True)
class TriangularFuzzyNumber:
    lower: float
    modal: float
    upper: float


@dataclass(frozen=True, slots=True)
class ScaleOption:
    option_id: str
    label: str
    numeric_value: float
    fuzzy_value: TriangularFuzzyNumber


@dataclass(frozen=True, slots=True)
class PreferenceScaleDefinition:
    elicitation_method: PreferenceElicitationMethod
    preference_scale: PreferenceScale
    version: str
    ordered: bool
    values: tuple[ScaleOption, ...]


ScaleKey = tuple[PreferenceElicitationMethod, PreferenceScale]
ScaleCatalog = Mapping[ScaleKey, PreferenceScaleDefinition]


def get_scale(
    catalog: ScaleCatalog,
    elicitation_method: PreferenceElicitationMethod,
    preference_scale: PreferenceScale,
) -> PreferenceScaleDefinition:
    key = (elicitation_method, preference_scale)

    try:
        return catalog[key]
    except KeyError as error:
        raise UnknownPreferenceScaleError(
            "No scale is defined for "
            f"{elicitation_method.value!r} and "
            f"{preference_scale.value!r}."
        ) from error


def get_option(
    scale: PreferenceScaleDefinition,
    option_id: str,
) -> ScaleOption:
    for option in scale.values:
        if option.option_id == option_id:
            return option

    raise UnknownPreferenceScaleError(
        f"Unknown option {option_id!r} for the {scale.preference_scale.value!r} scale."
    )


EXPECTED_SCALE_SIZE = {
    PreferenceScale.FIVE_POINT: 5,
    PreferenceScale.SEVEN_POINT: 7,
}

EXPECTED_PAIRWISE_VALUES = {
    PreferenceScale.FIVE_POINT: (5, 3, 1, 1 / 3, 1 / 5),
    PreferenceScale.SEVEN_POINT: (
        7,
        5,
        3,
        1,
        1 / 3,
        1 / 5,
        1 / 7,
    ),
}


def validate_scale(scale: PreferenceScaleDefinition) -> None:
    """Validate a complete direct-rating or pairwise scale definition."""

    if not isinstance(scale.version, str) or not scale.version.strip():
        raise InvalidPreferenceScaleError("Preference scale version cannot be blank.")

    expected_size = EXPECTED_SCALE_SIZE.get(scale.preference_scale)
    if expected_size is None:
        raise InvalidPreferenceScaleError(
            f"Unsupported preference scale: {scale.preference_scale!r}."
        )

    if len(scale.values) != expected_size:
        raise InvalidPreferenceScaleError(
            "Preference scale size mismatch: "
            f"expected {expected_size}, got {len(scale.values)}."
        )

    option_ids: set[str] = set()
    labels: set[str] = set()

    for option in scale.values:
        if not isinstance(option, ScaleOption):
            raise InvalidPreferenceScaleError(
                "Scale values must be ScaleOption instances."
            )

        if not option.option_id.strip():
            raise InvalidPreferenceScaleError("Scale option ID cannot be blank.")
        if option.option_id in option_ids:
            raise InvalidPreferenceScaleError(
                f"Duplicate option ID: {option.option_id!r}."
            )
        option_ids.add(option.option_id)

        if not option.label.strip():
            raise InvalidPreferenceScaleError(
                f"Scale option label cannot be blank for option {option.option_id!r}."
            )
        if option.label in labels:
            raise InvalidPreferenceScaleError(
                f"Duplicate scale option label: {option.label!r}."
            )
        labels.add(option.label)

        if not _is_finite_real(option.numeric_value):
            raise InvalidPreferenceScaleError(
                f"Scale option numeric value must be finite for {option.option_id!r}."
            )
        if option.numeric_value <= 0:
            raise InvalidPreferenceScaleError(
                f"Scale option numeric value must be positive for {option.option_id!r}."
            )

        fuzzy = option.fuzzy_value
        if not isinstance(fuzzy, TriangularFuzzyNumber):
            raise InvalidPreferenceScaleError(
                "Scale option fuzzy value must be a TriangularFuzzyNumber."
            )
        if not all(
            _is_finite_real(component)
            for component in (fuzzy.lower, fuzzy.modal, fuzzy.upper)
        ):
            raise InvalidPreferenceScaleError(
                f"Scale option fuzzy value must be finite for {option.option_id!r}."
            )
        if not fuzzy.lower <= fuzzy.modal <= fuzzy.upper:
            raise InvalidPreferenceScaleError(
                "Scale option fuzzy value must satisfy "
                "lower <= modal <= upper for "
                f"{option.option_id!r}."
            )

    if scale.elicitation_method == PreferenceElicitationMethod.DIRECT_RATING:
        _validate_direct_scale(scale)
    elif scale.elicitation_method == PreferenceElicitationMethod.PAIRWISE_COMPARISON:
        _validate_pairwise_scale(scale)
    else:
        raise InvalidPreferenceScaleError(
            f"Unsupported preference elicitation method: {scale.elicitation_method!r}."
        )


def _validate_direct_scale(scale: PreferenceScaleDefinition) -> None:
    numeric_values = tuple(option.numeric_value for option in scale.values)

    if scale.ordered and numeric_values != tuple(range(1, len(scale.values) + 1)):
        raise InvalidPreferenceScaleError(
            "Ordered direct-rating values must be consecutive, starting at one."
        )

    for option in scale.values:
        fuzzy = option.fuzzy_value
        if not 0 <= fuzzy.lower <= fuzzy.modal <= fuzzy.upper <= 1:
            raise InvalidPreferenceScaleError(
                "Direct-rating fuzzy values must stay within [0, 1] "
                f"for {option.option_id!r}."
            )


def _validate_pairwise_scale(scale: PreferenceScaleDefinition) -> None:
    if len(scale.values) % 2 != 1:
        raise InvalidPreferenceScaleError(
            "Pairwise scales must contain an odd number of options."
        )

    expected_values = EXPECTED_PAIRWISE_VALUES[scale.preference_scale]
    actual_values = tuple(option.numeric_value for option in scale.values)
    if scale.ordered and not _sequences_close(
        actual_values,
        expected_values,
    ):
        raise InvalidPreferenceScaleError(
            "Pairwise scale values must match the declared sequence."
        )

    equality_options = tuple(
        option for option in scale.values if math.isclose(option.numeric_value, 1.0)
    )
    if len(equality_options) != 1:
        raise InvalidPreferenceScaleError(
            "Pairwise scales must contain exactly one equality option."
        )

    equality = equality_options[0].fuzzy_value
    if not _sequences_close(
        (equality.lower, equality.modal, equality.upper),
        (1.0, 1.0, 1.0),
    ):
        raise InvalidPreferenceScaleError(
            "The equality option fuzzy value must be (1, 1, 1)."
        )

    for option in scale.values:
        fuzzy = option.fuzzy_value
        if fuzzy.lower <= 0:
            raise InvalidPreferenceScaleError(
                "Pairwise fuzzy values must be strictly positive for "
                f"{option.option_id!r}."
            )
        if math.isclose(option.numeric_value, 1.0):
            continue

        reciprocal = next(
            (
                candidate
                for candidate in scale.values
                if math.isclose(
                    candidate.numeric_value,
                    1.0 / option.numeric_value,
                )
            ),
            None,
        )
        if reciprocal is None:
            raise InvalidPreferenceScaleError(
                f"Missing reciprocal option for {option.option_id!r}."
            )

        expected_fuzzy = (
            1.0 / option.fuzzy_value.upper,
            1.0 / option.fuzzy_value.modal,
            1.0 / option.fuzzy_value.lower,
        )
        reciprocal_fuzzy = reciprocal.fuzzy_value
        if not _sequences_close(
            (
                reciprocal_fuzzy.lower,
                reciprocal_fuzzy.modal,
                reciprocal_fuzzy.upper,
            ),
            expected_fuzzy,
        ):
            raise InvalidPreferenceScaleError(
                f"Fuzzy reciprocal pair mismatch for {option.option_id!r}."
            )


def _is_finite_real(value: object) -> bool:
    return (
        isinstance(value, Real)
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _sequences_close(
    values: tuple[float, ...],
    expected: tuple[float, ...],
) -> bool:
    return len(values) == len(expected) and all(
        math.isclose(actual, target, rel_tol=1e-9, abs_tol=1e-9)
        for actual, target in zip(values, expected, strict=True)
    )


def _option(
    option_id: str,
    label: str,
    numeric_value: float,
    fuzzy_value: tuple[float, float, float],
) -> ScaleOption:
    return ScaleOption(
        option_id=option_id,
        label=label,
        numeric_value=numeric_value,
        fuzzy_value=TriangularFuzzyNumber(*fuzzy_value),
    )


DIRECT_FIVE_POINT = PreferenceScaleDefinition(
    elicitation_method=PreferenceElicitationMethod.DIRECT_RATING,
    preference_scale=PreferenceScale.FIVE_POINT,
    version="1.0",
    ordered=True,
    values=(
        _option("direct_1", "Very Low", 1, (0.0, 0.1, 0.25)),
        _option("direct_2", "Low", 2, (0.15, 0.3, 0.45)),
        _option("direct_3", "Medium", 3, (0.35, 0.5, 0.65)),
        _option("direct_4", "High", 4, (0.55, 0.7, 0.85)),
        _option("direct_5", "Very High", 5, (0.75, 0.9, 1.0)),
    ),
)

DIRECT_SEVEN_POINT = PreferenceScaleDefinition(
    elicitation_method=PreferenceElicitationMethod.DIRECT_RATING,
    preference_scale=PreferenceScale.SEVEN_POINT,
    version="1.0",
    ordered=True,
    values=(
        _option("direct_1", "Very Low", 1, (0.0, 0.1, 0.2)),
        _option("direct_2", "Low", 2, (0.1333, 0.2333, 0.3333)),
        _option(
            "direct_3",
            "Moderately Low",
            3,
            (0.2667, 0.3667, 0.4667),
        ),
        _option("direct_4", "Medium", 4, (0.4, 0.5, 0.6)),
        _option(
            "direct_5",
            "Moderately High",
            5,
            (0.5333, 0.6333, 0.7333),
        ),
        _option("direct_6", "High", 6, (0.6667, 0.7667, 0.8667)),
        _option("direct_7", "Very High", 7, (0.8, 0.9, 1.0)),
    ),
)

PAIRWISE_FIVE_POINT = PreferenceScaleDefinition(
    elicitation_method=PreferenceElicitationMethod.PAIRWISE_COMPARISON,
    preference_scale=PreferenceScale.FIVE_POINT,
    version="1.0",
    ordered=True,
    values=(
        _option("pairwise_1", "Left criterion is more important", 5, (4, 5, 6)),
        _option(
            "pairwise_2",
            "Left criterion is slightly more important",
            3,
            (2, 3, 4),
        ),
        _option(
            "pairwise_3",
            "Both criteria are equally important",
            1,
            (1, 1, 1),
        ),
        _option(
            "pairwise_4",
            "Right criterion is slightly more important",
            1 / 3,
            (1 / 4, 1 / 3, 1 / 2),
        ),
        _option(
            "pairwise_5",
            "Right criterion is more important",
            1 / 5,
            (1 / 6, 1 / 5, 1 / 4),
        ),
    ),
)

PAIRWISE_SEVEN_POINT = PreferenceScaleDefinition(
    elicitation_method=PreferenceElicitationMethod.PAIRWISE_COMPARISON,
    preference_scale=PreferenceScale.SEVEN_POINT,
    version="1.0",
    ordered=True,
    values=(
        _option("pairwise_1", "Left criterion is much more important", 7, (6, 7, 8)),
        _option("pairwise_2", "Left criterion is more important", 5, (4, 5, 6)),
        _option(
            "pairwise_3", "Left criterion is slightly more important", 3, (2, 3, 4)
        ),
        _option("pairwise_4", "Both criteria are equally important", 1, (1, 1, 1)),
        _option(
            "pairwise_5",
            "Right criterion is slightly more important",
            1 / 3,
            (1 / 4, 1 / 3, 1 / 2),
        ),
        _option(
            "pairwise_6",
            "Right criterion is more important",
            1 / 5,
            (1 / 6, 1 / 5, 1 / 4),
        ),
        _option(
            "pairwise_7",
            "Right criterion is much more important",
            1 / 7,
            (1 / 8, 1 / 7, 1 / 6),
        ),
    ),
)

SCALE_CATALOG: dict[ScaleKey, PreferenceScaleDefinition] = {
    (
        PreferenceElicitationMethod.DIRECT_RATING,
        PreferenceScale.FIVE_POINT,
    ): DIRECT_FIVE_POINT,
    (
        PreferenceElicitationMethod.DIRECT_RATING,
        PreferenceScale.SEVEN_POINT,
    ): DIRECT_SEVEN_POINT,
    (
        PreferenceElicitationMethod.PAIRWISE_COMPARISON,
        PreferenceScale.FIVE_POINT,
    ): PAIRWISE_FIVE_POINT,
    (
        PreferenceElicitationMethod.PAIRWISE_COMPARISON,
        PreferenceScale.SEVEN_POINT,
    ): PAIRWISE_SEVEN_POINT,
}

for _scale_definition in SCALE_CATALOG.values():
    validate_scale(_scale_definition)
