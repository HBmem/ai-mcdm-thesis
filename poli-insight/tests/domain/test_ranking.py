from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from poli_insight.domain.enum import ArtifactType, RunStatus
from poli_insight.domain.ranking import (
    RankedAlternative,
    RankingArtifact,
    RankingResult,
    RankingRuleViolation,
    RankingRun,
)


def _result() -> RankingResult:
    return RankingResult.create(
        ranking_result_id="result-1",
        ranking_run_id="ranking-1",
        source_processing_matrix_id="matrix-1",
        level="session",
        metric_label="Preference",
        alternatives=(
            RankedAlternative("a", 1, Decimal("0.8")),
            RankedAlternative("b", 2, Decimal("0.2")),
        ),
        diagnostics_json={"provider": "test"},
    )


def test_ranking_result_hash_covers_generic_metrics_and_dense_ranks():
    result = _result()

    assert len(result.result_hash) == 64
    assert [item.rank for item in result.alternatives] == [1, 2]

    with pytest.raises(RankingRuleViolation, match="dense"):
        RankingResult.create(
            ranking_result_id="result-2",
            ranking_run_id="ranking-1",
            source_processing_matrix_id="matrix-2",
            level="session",
            metric_label="Preference",
            alternatives=(
                RankedAlternative("a", 1, Decimal("0.8")),
                RankedAlternative("b", 3, Decimal("0.2")),
            ),
            diagnostics_json={},
        )


def test_aggregate_results_reject_individual_validation_identity():
    with pytest.raises(RankingRuleViolation, match="cannot contain validation"):
        RankingResult.create(
            ranking_result_id="result-2",
            ranking_run_id="ranking-1",
            source_processing_matrix_id="matrix-2",
            level="session",
            validation_id="validation-secret",
            metric_label="Preference",
            alternatives=(RankedAlternative("a", 1, Decimal("0.8")),),
            diagnostics_json={},
        )


def test_successful_run_has_immutable_output_evidence():
    result = _result()
    artifact = RankingArtifact.create(
        ranking_artifact_id="artifact-1",
        ranking_run_id="ranking-1",
        artifact_type=ArtifactType.STRUCTURED_RESULT,
        schema_version=1,
        content_json={"results": [result.to_manifest()]},
    )
    now = datetime(2026, 8, 25, tzinfo=UTC)
    run = RankingRun.succeeded(
        ranking_run_id="ranking-1",
        session_id="session-1",
        source_processing_run_id="processing-1",
        configuration_version_id="configuration-1",
        scenario_snapshot_id="scenario-1",
        run_number=1,
        roster_hash="a" * 64,
        input_hash="b" * 64,
        algorithm_implementation_id="algorithm-1",
        implementation_version="1.0.0",
        adapter_version="1.0.0",
        parameter_json={},
        environment_json={},
        created_at=now,
        created_by="admin-1",
        completed_at=now,
        results=(result,),
        artifacts=(artifact,),
    )

    assert run.status == RunStatus.SUCCEEDED
    assert run.output_hash is not None
