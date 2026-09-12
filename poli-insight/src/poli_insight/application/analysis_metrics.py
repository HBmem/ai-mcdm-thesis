"""Tie-aware comparisons between immutable ranking results."""

from __future__ import annotations

from decimal import Decimal
from math import sqrt

from poli_insight.domain.ranking import RankedAlternative


def ranking_manifest(values: tuple[RankedAlternative, ...]) -> list[dict[str, object]]:
    return [value.to_manifest() for value in values]


def comparison_metrics(
    baseline: tuple[RankedAlternative, ...],
    candidate: tuple[RankedAlternative, ...],
) -> dict[str, object]:
    baseline_by_id = {item.alternative_id: item for item in baseline}
    candidate_by_id = {item.alternative_id: item for item in candidate}
    common = tuple(sorted(set(baseline_by_id) & set(candidate_by_id)))
    baseline_best = max(
        (baseline_by_id[item].preference_value for item in common), default=None
    )
    candidate_best = max(
        (candidate_by_id[item].preference_value for item in common), default=None
    )
    baseline_top = sorted(
        item
        for item in common
        if baseline_by_id[item].preference_value == baseline_best
    )
    candidate_top = sorted(
        item
        for item in common
        if candidate_by_id[item].preference_value == candidate_best
    )
    top_k = min(3, len(common))
    baseline_top_k = {
        item.alternative_id
        for item in sorted(
            (baseline_by_id[value] for value in common),
            key=lambda item: (item.rank, item.alternative_id),
        )[:top_k]
    }
    candidate_top_k = {
        item.alternative_id
        for item in sorted(
            (candidate_by_id[value] for value in common),
            key=lambda item: (item.rank, item.alternative_id),
        )[:top_k]
    }
    strict_reversals = 0
    tie_transitions = 0
    affected_pairs: list[dict[str, str]] = []
    for index, left in enumerate(common):
        for right in common[index + 1 :]:
            before = _sign(
                baseline_by_id[left].preference_value
                - baseline_by_id[right].preference_value
            )
            after = _sign(
                candidate_by_id[left].preference_value
                - candidate_by_id[right].preference_value
            )
            if before and after and before != after:
                strict_reversals += 1
                affected_pairs.append(
                    {"left": left, "right": right, "change": "reversal"}
                )
            elif before != after and (before == 0 or after == 0):
                tie_transitions += 1
                affected_pairs.append(
                    {"left": left, "right": right, "change": "tie_transition"}
                )
    return {
        "baseline_top_set": baseline_top,
        "candidate_top_set": candidate_top,
        "top_set_changed": baseline_top != candidate_top,
        "top_choice_retained": bool(set(baseline_top) & set(candidate_top)),
        "top_k": top_k,
        "top_k_retention": (
            Decimal(len(baseline_top_k & candidate_top_k)) / Decimal(top_k)
            if top_k
            else None
        ),
        "kendall_tau_b": _kendall_tau_b(baseline_by_id, candidate_by_id, common),
        "spearman": _spearman(baseline_by_id, candidate_by_id, common),
        "maximum_rank_displacement": max(
            (
                abs(baseline_by_id[item].rank - candidate_by_id[item].rank)
                for item in common
            ),
            default=0,
        ),
        "baseline_score_margin": _score_margin(
            tuple(baseline_by_id[item] for item in common)
        ),
        "candidate_score_margin": _score_margin(
            tuple(candidate_by_id[item] for item in common)
        ),
        "strict_reversals": strict_reversals,
        "tie_transitions": tie_transitions,
        "affected_pairs": affected_pairs,
    }


def _score_margin(values: tuple[RankedAlternative, ...]) -> Decimal | None:
    scores = sorted({item.preference_value for item in values}, reverse=True)
    return None if len(scores) < 2 else scores[0] - scores[1]


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else -1 if value < 0 else 0


def _kendall_tau_b(baseline, candidate, common: tuple[str, ...]) -> Decimal | None:
    if len(common) < 2:
        return None
    concordant = discordant = ties_before = ties_after = 0
    for index, left in enumerate(common):
        for right in common[index + 1 :]:
            before = _sign(
                baseline[left].preference_value - baseline[right].preference_value
            )
            after = _sign(
                candidate[left].preference_value - candidate[right].preference_value
            )
            if before == 0 and after != 0:
                ties_before += 1
            if after == 0 and before != 0:
                ties_after += 1
            if before and after:
                if before == after:
                    concordant += 1
                else:
                    discordant += 1
    denominator = sqrt(
        (concordant + discordant + ties_before) * (concordant + discordant + ties_after)
    )
    if denominator == 0:
        return None
    return Decimal(str((concordant - discordant) / denominator))


def _average_positions(values, common: tuple[str, ...]) -> dict[str, Decimal]:
    ordered = sorted(common, key=lambda item: (-values[item].preference_value, item))
    result: dict[str, Decimal] = {}
    position = 1
    while position <= len(ordered):
        end = position
        score = values[ordered[position - 1]].preference_value
        while end < len(ordered) and values[ordered[end]].preference_value == score:
            end += 1
        average = (Decimal(position) + Decimal(end)) / Decimal(2)
        for item in ordered[position - 1 : end]:
            result[item] = average
        position = end + 1
    return result


def _spearman(baseline, candidate, common: tuple[str, ...]) -> Decimal | None:
    if len(common) < 2:
        return None
    left = _average_positions(baseline, common)
    right = _average_positions(candidate, common)
    left_mean = sum(left.values(), Decimal(0)) / Decimal(len(common))
    right_mean = sum(right.values(), Decimal(0)) / Decimal(len(common))
    numerator = sum(
        ((left[item] - left_mean) * (right[item] - right_mean) for item in common),
        Decimal(0),
    )
    left_square = sum(((left[item] - left_mean) ** 2 for item in common), Decimal(0))
    right_square = sum(((right[item] - right_mean) ** 2 for item in common), Decimal(0))
    denominator = (left_square * right_square).sqrt()
    return None if denominator == 0 else numerator / denominator
