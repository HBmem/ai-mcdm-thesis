from __future__ import annotations

import json

import numpy as np

from typing import Any
from pyDecision.algorithm import ahp_method, fuzzy_ahp_method

class WeightingError(RuntimeError):
    pass

def _json_loads(value: str | dict | None) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)

def get_pairwise_matrix_from_submission(
    submission: dict[str, Any],
) -> tuple[list[str], np.ndarray]:
    """
    Extract the generated AHP pairwise matrix from a stored stakeholder submission.

    The matrix is currently generated in preferences.transform_linguistic_preferences()
    from one linguistic rating per criterion.
    """
    transformed = _json_loads(submission.get("transformed_preferences_json"))

    # Check for both possible key names for robustness
    matrix_payload = (
        transformed.get("rating_derived_pairwise_matrix")
        or transformed.get("ahp_pairwise_matrix")
    )
    if not matrix_payload:
        raise WeightingError(
            f"Submission {submission.get('submission_id')} does not contain a pairwise matrix."
        )

    criteria_order = matrix_payload.get("criteria_order", [])
    matrix = matrix_payload.get("matrix", [])

    if not criteria_order or not matrix:
        raise WeightingError(
            f"Submission {submission.get('submission_id')} has an incomplete pairwise matrix."
        )

    np_matrix = np.array(matrix, dtype=float)

    if np_matrix.shape[0] != np_matrix.shape[1]:
        raise WeightingError("AHP pairwise matrix must be square.")

    if np_matrix.shape[0] != len(criteria_order):
        raise WeightingError("Matrix size does not match criteria order length.")

    return criteria_order, np_matrix

def compute_ahp_weights_from_matrix(
    criteria_order: list[str],
    pairwise_matrix: np.ndarray,
    weight_derivation: str = "geometric",
) -> dict[str, Any]:
    """
    Run pyDecision AHP on a pairwise comparison matrix.

    pyDecision returns:
    - weights: criteria weight vector
    - rc: consistency ratio
    """
    weights, rc = ahp_method(pairwise_matrix, wd=weight_derivation)

    weights_by_criterion = {
        criterion_id: float(weights[idx])
        for idx, criterion_id in enumerate(criteria_order)
    }

    return {
        "method": "AHP",
        "weight_derivation": weight_derivation,
        "criteria_order": criteria_order,
        "pairwise_matrix": pairwise_matrix.round(6).tolist(),
        "weights": weights_by_criterion,
        "weights_vector": [float(w) for w in weights],
        "consistency_ratio": float(rc),
        "is_consistent": bool(rc <= 0.10),
    }

def compute_submission_ahp_result(
    submission: dict[str, Any],
    weight_derivation: str = "geometric",
) -> dict[str, Any]:
    """
    Compute AHP weights for one stakeholder submission.
    """
    criteria_order, matrix = get_pairwise_matrix_from_submission(submission)

    result = compute_ahp_weights_from_matrix(
        criteria_order=criteria_order,
        pairwise_matrix=matrix,
        weight_derivation=weight_derivation,
    )

    result["submission_id"] = submission.get("submission_id")
    result["participant_id"] = submission.get("participant_id")
    result["stakeholder_type_id"] = submission.get("stakeholder_type_id")
    result["normalized_voting_power"] = float(submission.get("normalized_voting_power") or 0.0)

    return result

def compute_group_ahp_result(submissions: list[dict[str, Any]], weight_derivation: str = "geometric") -> dict[str, Any]:
    """
    Aggregate multiple stakeholder pairwise matrices using weighted geometric mean,
    then run AHP once on the aggregate group matrix.
    """
    if not submissions:
        raise WeightingError("Cannot compute group AHP result without submissions.")

    individual_results = []
    matrices = []
    powers = []
    criteria_order: list[str] | None = None

    for submission in submissions:
        result = compute_submission_ahp_result(
            submission=submission,
            weight_derivation=weight_derivation,
        )
        individual_results.append(result)

        current_order = result["criteria_order"]
        current_matrix = np.array(result["pairwise_matrix"], dtype=float)

        if criteria_order is None:
            criteria_order = current_order
        elif criteria_order != current_order:
            raise WeightingError("All submissions must use the same criteria order.")

        matrices.append(current_matrix)
        powers.append(float(submission.get("normalized_voting_power") or 0.0))

    power_sum = sum(powers)

    if power_sum <= 0:
        powers = [1.0 / len(matrices)] * len(matrices)
    else:
        powers = [p / power_sum for p in powers]

    stacked = np.stack(matrices, axis=0)
    power_array = np.array(powers).reshape((-1, 1, 1))

    # Weighted geometric mean:
    # group_a_ij = product(a_ij_k ^ stakeholder_power_k)
    aggregate_matrix = np.prod(np.power(stacked, power_array), axis=0)

    group_result = compute_ahp_weights_from_matrix(
        criteria_order=criteria_order or [],
        pairwise_matrix=aggregate_matrix,
        weight_derivation=weight_derivation,
    )

    return {
        "method": "GROUP_AHP",
        "aggregation_method": "weighted_geometric_mean_pairwise_matrix",
        "weight_derivation": weight_derivation,
        "criteria_order": criteria_order,
        "stakeholder_powers": powers,
        "individual_results": individual_results,
        "aggregate_pairwise_matrix": aggregate_matrix.round(6).tolist(),
        "group_weights": group_result["weights"],
        "group_weights_vector": group_result["weights_vector"],
        "consistency_ratio": group_result["consistency_ratio"],
        "is_consistent": group_result["is_consistent"],
    }