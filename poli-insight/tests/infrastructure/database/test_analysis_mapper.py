from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from poli_insight.domain.analysis import AnalysisArtifact, AnalysisCase, AnalysisRun
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    AnalysisType,
    ArtifactType,
)
from poli_insight.infrastructure.database.mappers.analysis import (
    analysis_run_summary_to_domain,
    analysis_run_to_domain,
    analysis_run_to_row,
)


def test_analysis_mapper_round_trips_decimal_cases_and_artifacts() -> None:
    run_id = str(uuid4())
    case = AnalysisCase.create(
        analysis_case_id=str(uuid4()),
        analysis_run_id=run_id,
        sequence=1,
        status=AnalysisCaseStatus.EVALUATED,
        scope_type="session",
        scope_id=None,
        subject_type="criterion",
        subject_id=str(uuid4()),
        input_json={"candidate_weight": Decimal("0.45")},
        result_json={"metrics": {"kendall_tau_b": Decimal("0.8")}},
        warnings=(),
    )
    artifacts = tuple(
        AnalysisArtifact.create(
            analysis_artifact_id=str(uuid4()),
            analysis_run_id=run_id,
            artifact_type=artifact_type,
            schema_version=1,
            content_json=content,
        )
        for artifact_type, content in (
            (ArtifactType.INPUT_MANIFEST, {"input_hash": "c" * 64}),
            (
                ArtifactType.STRUCTURED_RESULT,
                {"summary": {"case_count": 1}},
            ),
            (
                ArtifactType.ANALYSIS_BUNDLE,
                {"participant_identifiers_included": False},
            ),
        )
    )
    now = datetime(2026, 9, 8, tzinfo=UTC)
    run = AnalysisRun.succeeded(
        analysis_run_id=run_id,
        session_id=str(uuid4()),
        source_processing_run_id=str(uuid4()),
        source_ranking_run_id=str(uuid4()),
        run_number=2,
        analysis_type=AnalysisType.SENSITIVITY,
        method=AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION,
        source_processing_output_hash="a" * 64,
        source_ranking_output_hash="b" * 64,
        input_hash="c" * 64,
        parameter_json={"step": Decimal("0.01")},
        environment_json={"adapter_version": "1.0.0"},
        created_at=now,
        created_by="admin-1",
        completed_at=now,
        correlation_id="correlation-1",
        cases=(case,),
        artifacts=artifacts,
    )

    row = analysis_run_to_row(run)
    restored = analysis_run_to_domain(row)
    summary = analysis_run_summary_to_domain(row)

    assert restored == run
    assert summary.analysis_run_id == run.analysis_run_id
    assert summary.artifacts == run.artifacts
    assert not hasattr(summary, "cases")
