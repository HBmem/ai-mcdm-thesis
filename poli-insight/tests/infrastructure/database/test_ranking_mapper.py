from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from poli_insight.domain.enum import ArtifactType
from poli_insight.domain.ranking import (
    RankedAlternative,
    RankingArtifact,
    RankingResult,
    RankingRun,
)
from poli_insight.infrastructure.database.mappers.ranking import (
    ranking_run_to_domain,
    ranking_run_to_row,
)


def test_ranking_run_mapper_round_trips_generic_result_and_artifact():
    run_id = str(uuid4())
    result = RankingResult.create(
        ranking_result_id=str(uuid4()),
        ranking_run_id=run_id,
        source_processing_matrix_id=str(uuid4()),
        level="session",
        alternatives=(
            RankedAlternative(
                str(uuid4()),
                1,
                Decimal("0.75"),
                {"future_method_metric": Decimal("2.5")},
            ),
        ),
        metric_label="Preference",
        diagnostics_json={"method": "test"},
    )
    artifact = RankingArtifact.create(
        ranking_artifact_id=str(uuid4()),
        ranking_run_id=run_id,
        artifact_type=ArtifactType.RANKING_TRACE,
        schema_version=1,
        content_json={"trace": "deterministic"},
    )
    now = datetime(2026, 8, 25, tzinfo=UTC)
    run = RankingRun.succeeded(
        ranking_run_id=run_id,
        session_id=str(uuid4()),
        source_processing_run_id=str(uuid4()),
        configuration_version_id=str(uuid4()),
        scenario_snapshot_id=str(uuid4()),
        run_number=1,
        roster_hash="a" * 64,
        input_hash="b" * 64,
        algorithm_implementation_id=str(uuid4()),
        implementation_version="1.0.0",
        adapter_version="1.0.0",
        parameter_json={"future_parameter": True},
        environment_json={"provider": "test"},
        created_at=now,
        created_by="admin-1",
        completed_at=now,
        results=(result,),
        artifacts=(artifact,),
    )

    restored = ranking_run_to_domain(ranking_run_to_row(run))

    assert restored == run
