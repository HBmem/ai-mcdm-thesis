from decimal import Decimal

import pytest

from poli_insight.application.use_cases.finalize_validation_bundle import (
    _geometric_mean_matrices,
    _weighted_geometric_matrices,
)


def test_within_group_geometric_mean_preserves_reciprocity():
    first = ((Decimal(1), Decimal(2)), (Decimal("0.5"), Decimal(1)))
    second = ((Decimal(1), Decimal(8)), (Decimal("0.125"), Decimal(1)))

    result = _geometric_mean_matrices((first, second))

    assert float(result[0][1]) == pytest.approx(4)
    assert float(result[1][0]) == pytest.approx(0.25)


def test_across_group_weighted_geometric_product_uses_voting_power():
    matrices = {
        "group-a": ((Decimal(1), Decimal(4)), (Decimal("0.25"), Decimal(1))),
        "group-b": ((Decimal(1), Decimal(16)), (Decimal("0.0625"), Decimal(1))),
    }

    result = _weighted_geometric_matrices(
        matrices,
        {"group-a": Decimal("0.75"), "group-b": Decimal("0.25")},
    )

    assert float(result[0][1]) == pytest.approx(4 * (2**0.5))
    assert float(result[1][0]) == pytest.approx(1 / (4 * (2**0.5)))

