"""Application-owned response scales available to every session.

Scenario packages may recommend one of these stable scale keys, but they do
not define the application's supported calculation contract.  Importing a
scenario materializes this versioned catalog into the immutable scenario
snapshot so a session configuration can continue to reference the existing
``scenario_scales`` persistence boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


APPLICATION_SCALE_CATALOG_VERSION = 1


@dataclass(frozen=True, slots=True)
class ApplicationScaleValue:
    stable_value_key: str
    label: str
    numeric_value: Decimal
    fuzzy_value: tuple[Decimal, Decimal, Decimal]


@dataclass(frozen=True, slots=True)
class ApplicationResponseScale:
    scale_key: str
    name: str
    response_format: str
    definition_version: int
    values: tuple[ApplicationScaleValue, ...]


def _decimal(value: str) -> Decimal:
    return Decimal(value)


def _value(
    key: str,
    label: str,
    numeric_value: str,
    fuzzy_lower: str,
    fuzzy_middle: str,
    fuzzy_upper: str,
) -> ApplicationScaleValue:
    return ApplicationScaleValue(
        stable_value_key=key,
        label=label,
        numeric_value=_decimal(numeric_value),
        fuzzy_value=(
            _decimal(fuzzy_lower),
            _decimal(fuzzy_middle),
            _decimal(fuzzy_upper),
        ),
    )


APPLICATION_RESPONSE_SCALES = (
    ApplicationResponseScale(
        scale_key="direct_five_point_v1",
        name="Direct Rating Five Point V1",
        response_format="direct_rating",
        definition_version=1,
        values=(
            _value("direct_1", "Very Low", "1", "0", "0.1", "0.25"),
            _value("direct_2", "Low", "2", "0.15", "0.3", "0.45"),
            _value("direct_3", "Medium", "3", "0.35", "0.5", "0.65"),
            _value("direct_4", "High", "4", "0.55", "0.7", "0.85"),
            _value("direct_5", "Very High", "5", "0.75", "0.9", "1"),
        ),
    ),
    ApplicationResponseScale(
        scale_key="direct_seven_point_v1",
        name="Direct Rating Seven Point V1",
        response_format="direct_rating",
        definition_version=1,
        values=(
            _value("direct_1", "Very Low", "1", "0", "0.1", "0.2"),
            _value("direct_2", "Low", "2", "0.1333", "0.2333", "0.3333"),
            _value(
                "direct_3",
                "Moderately Low",
                "3",
                "0.2667",
                "0.3667",
                "0.4667",
            ),
            _value("direct_4", "Medium", "4", "0.4", "0.5", "0.6"),
            _value(
                "direct_5",
                "Moderately High",
                "5",
                "0.5333",
                "0.6333",
                "0.7333",
            ),
            _value("direct_6", "High", "6", "0.6667", "0.7667", "0.8667"),
            _value("direct_7", "Very High", "7", "0.8", "0.9", "1"),
        ),
    ),
    ApplicationResponseScale(
        scale_key="pairwise_five_point_v1",
        name="Pairwise Five Point V1",
        response_format="pairwise",
        definition_version=1,
        values=(
            _value(
                "pairwise_1",
                "Left criterion is more important",
                "5",
                "4",
                "5",
                "6",
            ),
            _value(
                "pairwise_2",
                "Left criterion is slightly more important",
                "3",
                "2",
                "3",
                "4",
            ),
            _value(
                "pairwise_3",
                "Both criteria are equally important",
                "1",
                "1",
                "1",
                "1",
            ),
            _value(
                "pairwise_4",
                "Right criterion is slightly more important",
                "0.333333333333333333",
                "0.25",
                "0.333333333333333333",
                "0.5",
            ),
            _value(
                "pairwise_5",
                "Right criterion is more important",
                "0.2",
                "0.166666666666666667",
                "0.2",
                "0.25",
            ),
        ),
    ),
    ApplicationResponseScale(
        scale_key="pairwise_seven_point_v1",
        name="Pairwise Seven Point V1",
        response_format="pairwise",
        definition_version=1,
        values=(
            _value(
                "pairwise_1",
                "Left criterion is much more important",
                "7",
                "6",
                "7",
                "8",
            ),
            _value(
                "pairwise_2",
                "Left criterion is more important",
                "5",
                "4",
                "5",
                "6",
            ),
            _value(
                "pairwise_3",
                "Left criterion is slightly more important",
                "3",
                "2",
                "3",
                "4",
            ),
            _value(
                "pairwise_4",
                "Both criteria are equally important",
                "1",
                "1",
                "1",
                "1",
            ),
            _value(
                "pairwise_5",
                "Right criterion is slightly more important",
                "0.333333333333333333",
                "0.25",
                "0.333333333333333333",
                "0.5",
            ),
            _value(
                "pairwise_6",
                "Right criterion is more important",
                "0.2",
                "0.166666666666666667",
                "0.2",
                "0.25",
            ),
            _value(
                "pairwise_7",
                "Right criterion is much more important",
                "0.142857142857142857",
                "0.125",
                "0.142857142857142857",
                "0.166666666666666667",
            ),
        ),
    ),
)


def response_scale_catalog_document() -> dict[str, object]:
    """Return a detached canonical document for hashing and materialization."""

    return {
        "catalog_version": APPLICATION_SCALE_CATALOG_VERSION,
        "scales": [
            {
                "scale_key": scale.scale_key,
                "name": scale.name,
                "response_format": scale.response_format,
                "definition_version": scale.definition_version,
                "values": [
                    {
                        "id": value.stable_value_key,
                        "label": value.label,
                        "ordinal": ordinal,
                        "numeric_value": value.numeric_value,
                        "fuzzy_value": list(value.fuzzy_value),
                    }
                    for ordinal, value in enumerate(scale.values)
                ],
            }
            for scale in APPLICATION_RESPONSE_SCALES
        ],
    }


def response_scale_import_documents() -> dict[str, dict[str, object]]:
    """Return scale documents understood by the scenario import materializer."""

    return {
        scale.scale_key: {
            "name": scale.name,
            "version": scale.definition_version,
            "type": scale.response_format,
            "ordered": True,
            "source": "application",
            "catalog_version": APPLICATION_SCALE_CATALOG_VERSION,
            "values": [
                {
                    "id": value.stable_value_key,
                    "label": value.label,
                    "ordinal": ordinal,
                    "numeric_value": value.numeric_value,
                    "fuzzy_value": list(value.fuzzy_value),
                }
                for ordinal, value in enumerate(scale.values)
            ],
        }
        for scale in APPLICATION_RESPONSE_SCALES
    }
