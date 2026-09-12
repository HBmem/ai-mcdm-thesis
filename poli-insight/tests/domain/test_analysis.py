from __future__ import annotations

from datetime import UTC, datetime

import pytest

from poli_insight.domain.analysis import (
    AnalysisArtifact,
    AnalysisCase,
    AnalysisRuleViolation,
    AnalysisRun,
    analysis_type_for,
)
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    AnalysisType,
    ArtifactType,
    RunStatus,
)


def _case(run_id: str = "analysis-1") -> AnalysisCase:
    return AnalysisCase.create(
        analysis_case_id="case-1",
        analysis_run_id=run_id,
        sequence=1,
        status=AnalysisCaseStatus.EVALUATED,
        scope_type="session",
        subject_type="criterion",
        subject_id="criterion-1",
        input_json={"weight": "0.5"},
        result_json={"changed": False},
        warnings=(),
    )


def test_analysis_method_maps_to_expected_category() -> None:
    assert (
        analysis_type_for(AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION)
        == AnalysisType.SENSITIVITY
    )
    assert (
        analysis_type_for(AnalysisMethod.PARTICIPANT_INFLUENCE)
        == AnalysisType.PARTICIPANT_IMPACT
    )


def test_successful_analysis_hashes_cases_and_ai_safe_artifact() -> None:
    case = _case()
    artifact = AnalysisArtifact.create(
        analysis_artifact_id="artifact-1",
        analysis_run_id="analysis-1",
        artifact_type=ArtifactType.ANALYSIS_BUNDLE,
        schema_version=1,
        content_json={"participant_identifiers_included": False},
    )
    run = AnalysisRun.succeeded(
        analysis_run_id="analysis-1",
        session_id="session-1",
        source_processing_run_id="processing-1",
        source_ranking_run_id="ranking-1",
        run_number=1,
        analysis_type=AnalysisType.SENSITIVITY,
        method=AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION,
        source_processing_output_hash="a" * 64,
        source_ranking_output_hash="b" * 64,
        input_hash="c" * 64,
        parameter_json={},
        environment_json={},
        created_at=datetime(2026, 9, 8, tzinfo=UTC),
        created_by="admin-1",
        completed_at=datetime(2026, 9, 8, tzinfo=UTC),
        correlation_id="correlation-1",
        cases=(case,),
        artifacts=(artifact,),
    )

    assert run.status == RunStatus.SUCCEEDED
    assert run.output_hash is not None


def test_analysis_rejects_method_category_mismatch() -> None:
    with pytest.raises(AnalysisRuleViolation, match="method"):
        AnalysisRun.failed(
            analysis_run_id="analysis-1",
            session_id="session-1",
            source_processing_run_id="processing-1",
            source_ranking_run_id="ranking-1",
            run_number=1,
            analysis_type=AnalysisType.ROBUSTNESS,
            method=AnalysisMethod.PARTICIPANT_INFLUENCE,
            source_processing_output_hash="a" * 64,
            source_ranking_output_hash="b" * 64,
            input_hash="c" * 64,
            parameter_json={},
            environment_json={},
            created_at=datetime(2026, 9, 8, tzinfo=UTC),
            created_by="admin-1",
            completed_at=datetime(2026, 9, 8, tzinfo=UTC),
            correlation_id="correlation-1",
            failure_code="analysis.failed",
            failure_detail="Safe failure.",
        )
