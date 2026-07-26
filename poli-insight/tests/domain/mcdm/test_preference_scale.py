from __future__ import annotations

import pytest

from poli_insight.domain.enums import (
    PreferenceElicitationMethod,
    PreferenceScale,
)
from poli_insight.domain.mcdm.preference_scale import (
    PAIRWISE_FIVE_POINT,
    SCALE_CATALOG,
    InvalidPreferenceScaleError,
    PreferenceScaleDefinition,
    ScaleOption,
    TriangularFuzzyNumber,
    UnknownPreferenceScaleError,
    get_option,
    get_scale,
    validate_scale,
)


def test_built_in_scales_are_valid() -> None:
    for scale in SCALE_CATALOG.values():
        validate_scale(scale)


def test_get_scale_uses_elicitation_method_and_size() -> None:
    scale = get_scale(
        SCALE_CATALOG,
        PreferenceElicitationMethod.PAIRWISE_COMPARISON,
        PreferenceScale.FIVE_POINT,
    )

    assert scale is PAIRWISE_FIVE_POINT


def test_get_option_rejects_unknown_id() -> None:
    with pytest.raises(UnknownPreferenceScaleError, match="Unknown option"):
        get_option(PAIRWISE_FIVE_POINT, "missing")


def test_validate_scale_rejects_non_reciprocal_fuzzy_option() -> None:
    invalid_values = list(PAIRWISE_FIVE_POINT.values)
    invalid_values[-1] = ScaleOption(
        option_id="pairwise_5",
        label="Right criterion is more important",
        numeric_value=1 / 5,
        fuzzy_value=TriangularFuzzyNumber(1 / 5, 1 / 5, 1 / 5),
    )
    invalid_scale = PreferenceScaleDefinition(
        elicitation_method=PAIRWISE_FIVE_POINT.elicitation_method,
        preference_scale=PAIRWISE_FIVE_POINT.preference_scale,
        version=PAIRWISE_FIVE_POINT.version,
        ordered=PAIRWISE_FIVE_POINT.ordered,
        values=tuple(invalid_values),
    )

    with pytest.raises(
        InvalidPreferenceScaleError,
        match="Fuzzy reciprocal pair mismatch",
    ):
        validate_scale(invalid_scale)
