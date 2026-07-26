from __future__ import annotations

from poli_insight.domain.enums import PreferenceElicitationMethod
###
FIVE_POINT_SCALE_ = {
    "type": PreferenceElicitationMethod.DIRECT_RATING,
    "ordered": True,
    "values": [
        {
            "linguistic": "Very Low",
            "numeric": 1,
            "fuzzy_value": [0.0, 0.1, 0.25]
        },
        {
            "linguistic": "Low",
            "numeric": 2,
            "fuzzy_value": [0.15, 0.3, 0.45]
        },
        {
            "linguistic": "Medium",
            "numeric": 3,
            "fuzzy_value": [0.35, 0.5, 0.65]
        },
        {
            "linguistic": "High",
            "numeric": 4,
            "fuzzy_value": [0.55, 0.7, 0.85]
        },
        {
            "linguistic": "Very High",
            "numeric": 5,
            "fuzzy_value": [0.75, 0.9, 1.0]
        },
    ]   
}

SEVEN_POINT_SCALE = {
    "type": PreferenceElicitationMethod.DIRECT_RATING,
    "ordered": True,
    "values": [
        {
            "linguistic": "Very Low",
            "numeric": 1,
            "fuzzy_value": [0.0000, 0.1000, 0.2000],
        },
        {
            "linguistic": "Low",
            "numeric": 2,
            "fuzzy_value": [0.1333, 0.2333, 0.3333],
        },
        {
            "linguistic": "Moderately Low",
            "numeric": 3,
            "fuzzy_value": [0.2667, 0.3667, 0.4667],
        },
        {
            "linguistic": "Medium",
            "numeric": 4,
            "fuzzy_value": [0.4000, 0.5000, 0.6000],
        },
        {
            "linguistic": "Moderately High",
            "numeric": 5,
            "fuzzy_value": [0.5333, 0.6333, 0.7333],
        },
        {
            "linguistic": "High",
            "numeric": 6,
            "fuzzy_value": [0.6667, 0.7667, 0.8667],
        },
        {
            "linguistic": "Very High",
            "numeric": 7,
            "fuzzy_value": [0.8000, 0.9000, 1.0000],
        },
    ],
}

PAIRWISE_FIVE_POINT_SCALE = {
    "type": PreferenceElicitationMethod.PAIRWISE_COMPARISON,
    "ordered": True,
    "values": [
        {
            "id": "left_more",
            "label": "Left criterion is more important",
            "numeric_value": 5,
            "fuzzy_value": [4, 5, 6],
        },
        {
            "id": "left_slightly_more",
            "label": "Left criterion is slightly more important",
            "numeric_value": 3,
            "fuzzy_value": [2, 3, 4],
        },
        {
            "id": "equal",
            "label": "Both criteria are equally important",
            "numeric_value": 1,
            "fuzzy_value": [1, 1, 1],
        },
        {
            "id": "right_slightly_more",
            "label": "Right criterion is slightly more important",
            "numeric_value": 1 / 3,
            "fuzzy_value": [1 / 4, 1 / 3, 1 / 2],
        },
        {
            "id": "right_more",
            "label": "Right criterion is more important",
            "numeric_value": 1 / 5,
            "fuzzy_value": [1 / 6, 1 / 5, 1 / 4],
        },
    ],
}

PAIRWISE_SEVEN_POINT_SCALE = {
    "type": PreferenceElicitationMethod.PAIRWISE_COMPARISON,
    "ordered": True,
    "values": [
        {
            "id": "left_much_more",
            "label": "Left criterion is much more important",
            "numeric_value": 7,
            "fuzzy_value": [6, 7, 8],
        },
        {
            "id": "left_more",
            "label": "Left criterion is more important",
            "numeric_value": 5,
            "fuzzy_value": [4, 5, 6],
        },
        {
            "id": "left_slightly_more",
            "label": "Left criterion is slightly more important",
            "numeric_value": 3,
            "fuzzy_value": [2, 3, 4],
        },
        {
            "id": "equal",
            "label": "Both criteria are equally important",
            "numeric_value": 1,
            "fuzzy_value": [1, 1, 1],
        },
        {
            "id": "right_slightly_more",
            "label": "Right criterion is slightly more important",
            "numeric_value": 1 / 3,
            "fuzzy_value": [1 / 4, 1 / 3, 1 / 2],
        },
        {
            "id": "right_more",
            "label": "Right criterion is more important",
            "numeric_value": 1 / 5,
            "fuzzy_value": [1 / 6, 1 / 5, 1 / 4],
        },
        {
            "id": "right_much_more",
            "label": "Right criterion is much more important",
            "numeric_value": 1 / 7,
            "fuzzy_value": [1 / 8, 1 / 7, 1 / 6],
        },
    ],
}