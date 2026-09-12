from __future__ import annotations

from decimal import Decimal

from poli_insight.application.analysis_metrics import comparison_metrics
from poli_insight.application.ports.ranking import RankingWeightInput
from poli_insight.application.use_cases.run_selected_analyses import (
    _perturbed_weights,
    _weight_grid,
)
from poli_insight.domain.ranking import RankedAlternative


def test_rank_metrics_distinguish_reversal_from_tie_transition() -> None:
    baseline = (
        RankedAlternative("a", 1, Decimal("0.9")),
        RankedAlternative("b", 2, Decimal("0.6")),
        RankedAlternative("c", 3, Decimal("0.3")),
    )
    candidate = (
        RankedAlternative("b", 1, Decimal("0.8")),
        RankedAlternative("a", 2, Decimal("0.7")),
        RankedAlternative("c", 2, Decimal("0.7")),
    )

    metrics = comparison_metrics(baseline, candidate)

    assert metrics["strict_reversals"] == 1
    assert metrics["tie_transitions"] == 1
    assert metrics["top_set_changed"] is True
    assert metrics["maximum_rank_displacement"] == 1
    assert metrics["top_k_retention"] == Decimal(1)


def test_removing_the_original_winner_uses_the_best_survivor_as_baseline() -> None:
    baseline = (
        RankedAlternative("a", 1, Decimal("0.9")),
        RankedAlternative("b", 2, Decimal("0.6")),
        RankedAlternative("c", 3, Decimal("0.3")),
    )
    candidate = (
        RankedAlternative("b", 1, Decimal("0.8")),
        RankedAlternative("c", 2, Decimal("0.2")),
    )

    metrics = comparison_metrics(baseline, candidate)

    assert metrics["baseline_top_set"] == ["b"]
    assert metrics["candidate_top_set"] == ["b"]
    assert metrics["top_set_changed"] is False


def test_identical_rankings_have_perfect_tie_aware_correlations() -> None:
    ranking = (
        RankedAlternative("a", 1, Decimal("0.8")),
        RankedAlternative("b", 2, Decimal("0.5")),
        RankedAlternative("c", 2, Decimal("0.5")),
    )

    metrics = comparison_metrics(ranking, ranking)

    assert metrics["kendall_tau_b"] == Decimal(1)
    assert metrics["spearman"] == Decimal(1)


def test_weight_grid_is_deterministic_and_includes_exact_baseline() -> None:
    values = _weight_grid(
        Decimal("0.03"),
        {
            "lower_delta": Decimal("0.05"),
            "upper_delta": Decimal("0.05"),
            "step": Decimal("0.02"),
        },
    )

    assert values == (
        Decimal(0),
        Decimal("0.02"),
        Decimal("0.03"),
        Decimal("0.04"),
        Decimal("0.06"),
        Decimal("0.08"),
    )


def test_weight_one_fallback_distributes_residual_equally() -> None:
    values, fallback = _perturbed_weights(
        (
            RankingWeightInput("a", Decimal(1)),
            RankingWeightInput("b", Decimal(0)),
            RankingWeightInput("c", Decimal(0)),
        ),
        "a",
        Decimal("0.4"),
    )

    assert fallback is True
    assert tuple(item.value for item in values) == (
        Decimal("0.4"),
        Decimal("0.3"),
        Decimal("0.3"),
    )
