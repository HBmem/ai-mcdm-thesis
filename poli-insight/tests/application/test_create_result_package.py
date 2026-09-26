from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from poli_insight.application.use_cases.create_result_package import (
    CreateResultPackageCommand,
    _aggregate_matrix_manifest,
    _aggregate_ranking_manifest,
    _participant_influence_case_manifest,
)
from poli_insight.domain.analysis import AnalysisCase
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import AnalysisCaseStatus, BundleVariant


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


@pytest.mark.parametrize("status", list(AnalysisCaseStatus))
def test_participant_influence_projection_preserves_cases_without_identity(status):
    case = AnalysisCase.create(
        analysis_case_id="case-1",
        analysis_run_id="analysis-1",
        sequence=1,
        status=status,
        scope_type="participant",
        scope_id="group-1",
        subject_type="participant",
        subject_id="participant-secret",
        input_json={
            "omitted_participant_id": "participant-secret",
            "stakeholder_group_id": "group-1",
            "group_key": "residents",
        },
        result_json=(
            {
                "session_metrics": {"maximum_rank_displacement": 1},
                "session_ranking": [{"alternative_id": "a", "rank": 1}],
                "group_metrics": {"maximum_rank_displacement": 2},
                "group_ranking": [{"alternative_id": "b", "rank": 1}],
            }
            if status == AnalysisCaseStatus.EVALUATED else {}
        ),
        warnings=("analysis.required_group_would_be_empty",)
        if status != AnalysisCaseStatus.EVALUATED else (),
    )
    original = deepcopy(case.to_manifest())

    manifest = _participant_influence_case_manifest(case)

    assert "participant-secret" not in str(manifest)
    assert manifest["subject_id"] is None
    assert manifest["sequence"] == 1
    assert manifest["scope_id"] == "group-1"
    assert manifest["status"] == status.value
    assert manifest["result"] == case.result_json
    assert manifest["warnings"] == list(case.warnings)
    assert manifest["source_content_hash"] == case.content_hash
    assert manifest["content_hash"] == hash_json({
        key: value for key, value in manifest.items()
        if key not in {"content_hash", "source_content_hash"}
    })
    assert case.to_manifest() == original
