from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from poli_insight.application.use_cases.create_result_package import (
    CreateResultPackageCommand,
    _aggregate_matrix_manifest,
    _aggregate_ranking_manifest,
)
from poli_insight.domain.enum import BundleVariant


def test_package_command_normalizes_variant_order() -> None:
    command = CreateResultPackageCommand(
        session_id="session-1",
        source_ranking_run_id="ranking-1",
        source_analysis_run_ids=("analysis-1",),
        variants=(BundleVariant.PUBLIC, BundleVariant.ANONYMOUS),
        actor_id="admin-1",
    )

    assert command.variants == (BundleVariant.ANONYMOUS, BundleVariant.PUBLIC)


def test_aggregate_package_projections_remove_validation_identity() -> None:
    matrix = SimpleNamespace(
        level="stakeholder_group",
        stakeholder_group_id="group-1",
        validation_id="validation-secret",
        criterion_ids=("cost",),
        matrix_json={"values": [[Decimal(1)]]},
        weights_json={"cost": Decimal(1)},
        diagnostics_json={},
        matrix_hash="a" * 64,
    )
    alternative = SimpleNamespace(
        to_manifest=lambda: {
            "alternative_id": "alternative-1",
            "rank": 1,
            "preference_value": Decimal(1),
        }
    )
    ranking = SimpleNamespace(
        source_processing_matrix_id="matrix-1",
        level="stakeholder_group",
        stakeholder_group_id="group-1",
        validation_id="validation-secret",
        metric_label="Preference",
        alternatives=(alternative,),
        diagnostics_json={},
        result_hash="b" * 64,
    )

    matrix_manifest = _aggregate_matrix_manifest(matrix)
    ranking_manifest = _aggregate_ranking_manifest(ranking)

    assert "validation_id" not in matrix_manifest
    assert "validation_id" not in ranking_manifest
    assert "validation-secret" not in str(matrix_manifest)
    assert "validation-secret" not in str(ranking_manifest)
