from __future__ import annotations

from decimal import Decimal
from itertools import count
from types import SimpleNamespace
from unittest.mock import patch

from poli_insight.application.ports.ranking import (
    RankingAlternativeInput,
    RankingAlternativeResult,
    RankingCriterionInput,
    RankingDecisionCell,
    RankingExecutionResult,
    RankingRequest,
    RankingWeightInput,
)
from poli_insight.application.ports.validator import WeightingExecutionResult
from poli_insight.application.ranking_support import ranked_alternatives
from poli_insight.application.use_cases.run_selected_analyses import (
    AnalysisTestSpec,
    RunSelectedAnalyses,
    RunSelectedAnalysesCommand,
    _Context,
)
from poli_insight.domain.enum import (
    AnalysisCaseStatus,
    AnalysisMethod,
    CriterionDataType,
    CriterionDirection,
    RunInclusionStatus,
    RunStatus,
)
from poli_insight.domain.processing import ProcessingMatrix, ProcessingRunSubmission


class _RankingRunner:
    metadata = SimpleNamespace(adapter_version="1.0.0")

    def execute(self, request):
        weights = {item.criterion_id: item.value for item in request.weights}
        cells = {
            (item.alternative_id, item.criterion_id): item.numeric_value
            for item in request.cells
        }
        scores = []
        for alternative in request.alternatives:
            score = sum(
                (
                    cells[(alternative.alternative_id, criterion.criterion_id)]
                    * weights[criterion.criterion_id]
                    for criterion in request.criteria
                ),
                Decimal(0),
            )
            scores.append(RankingAlternativeResult(alternative.alternative_id, score))
        return RankingExecutionResult(tuple(scores), "Score")


class _WeightingRunner:
    metadata = SimpleNamespace(adapter_version="1.0.0")

    def execute(self, prepared, parameters):
        size = len(prepared.criterion_ids)
        return WeightingExecutionResult(
            criterion_ids=prepared.criterion_ids,
            crisp_weights=tuple(Decimal(1) / Decimal(size) for _ in range(size)),
            consistency_ratio=Decimal(0),
        )


def _matrix(matrix_id, level, *, group_id=None, validation_id=None):
    return ProcessingMatrix.create(
        processing_matrix_id=matrix_id,
        processing_run_id="processing-1",
        level=level,
        stakeholder_group_id=group_id,
        validation_id=validation_id,
        criterion_ids=("cost", "benefit"),
        matrix_json={"values": [["1", "2"], ["0.5", "1"]]},
        weights_json={
            "shape": "crisp",
            "values": [
                {"criterion_id": "cost", "weight": Decimal("0.5")},
                {"criterion_id": "benefit", "weight": Decimal("0.5")},
            ],
        },
        diagnostics_json={},
    )


def _request(matrix_id):
    alternatives = tuple(
        RankingAlternativeInput(key, key, key.upper(), index)
        for index, key in enumerate(("a", "b", "c"))
    )
    criteria = (
        RankingCriterionInput(
            "cost",
            "cost",
            "Cost",
            CriterionDirection.COST,
            CriterionDataType.NUMERIC,
            0,
        ),
        RankingCriterionInput(
            "benefit",
            "benefit",
            "Benefit",
            CriterionDirection.BENEFIT,
            CriterionDataType.NUMERIC,
            1,
        ),
    )
    raw = {
        "a": (Decimal("0.9"), Decimal("0.2")),
        "b": (Decimal("0.5"), Decimal("0.7")),
        "c": (Decimal("0.2"), Decimal("0.9")),
    }
    return RankingRequest(
        source_processing_matrix_id=matrix_id,
        alternatives=alternatives,
        criteria=criteria,
        cells=tuple(
            RankingDecisionCell(
                alternative.alternative_id, criterion.criterion_id, numeric_value=value
            )
            for alternative in alternatives
            for criterion, value in zip(
                criteria, raw[alternative.alternative_id], strict=True
            )
        ),
        weights=(
            RankingWeightInput("cost", Decimal("0.5")),
            RankingWeightInput("benefit", Decimal("0.5")),
        ),
    )


def _context():
    matrices = (
        _matrix("participant-1", "participant", validation_id="validation-1"),
        _matrix("participant-2", "participant", validation_id="validation-2"),
        _matrix("participant-3", "participant", validation_id="validation-3"),
        _matrix("group-1", "stakeholder_group", group_id="g1"),
        _matrix("group-2", "stakeholder_group", group_id="g2"),
        _matrix("session", "session"),
    )
    requests = {
        item.processing_matrix_id: _request(item.processing_matrix_id)
        for item in matrices
        if item.level != "participant"
    }
    runner = _RankingRunner()
    scopes = tuple(
        (
            matrix,
            SimpleNamespace(
                alternatives=ranked_alternatives(
                    runner.execute(requests[matrix.processing_matrix_id]).alternatives,
                    requests[matrix.processing_matrix_id].alternatives,
                )
            ),
            requests[matrix.processing_matrix_id],
        )
        for matrix in matrices
        if matrix.level in {"stakeholder_group", "session"}
    )
    groups = (
        SimpleNamespace(
            session_stakeholder_group_id="g1",
            group_key="required",
            allocation_units=60,
            is_active=True,
        ),
        SimpleNamespace(
            session_stakeholder_group_id="g2",
            group_key="optional",
            allocation_units=40,
            is_active=True,
        ),
    )
    submissions = tuple(
        ProcessingRunSubmission(
            processing_run_id="processing-1",
            submission_id=f"submission-{index}",
            participant_id=f"participant-{index}",
            stakeholder_group_id=group_id,
            inclusion_status=RunInclusionStatus.INCLUDED,
            validation_id=f"validation-{index}",
        )
        for index, group_id in ((1, "g1"), (2, "g1"), (3, "g2"))
    )
    return _Context(
        session=SimpleNamespace(),
        configuration=SimpleNamespace(
            stakeholder_groups=groups,
            required_group_policy_json={"required_group_keys": ["required"]},
            allocation_total_units=100,
            consistency_threshold=Decimal("0.1"),
        ),
        source=SimpleNamespace(
            processing_run_id="processing-1",
            configuration_version_id="configuration-1",
            scenario_snapshot_id="scenario-1",
            algorithm_implementation_id="weighting-1",
            output_hash="a" * 64,
            matrices=matrices,
            submissions=submissions,
        ),
        ranking=SimpleNamespace(
            session_id="session-1",
            ranking_run_id="ranking-1",
            algorithm_implementation_id="ranking-1",
            adapter_version="1.0.0",
            output_hash="b" * 64,
        ),
        scenario=SimpleNamespace(),
        weighting_runner=_WeightingRunner(),
        ranking_runner=runner,
        weighting_parameters={},
        ranking_parameters={},
        scopes=scopes,
    )


def _service():
    values = count(1)
    return RunSelectedAnalyses(
        lambda: None,
        None,
        None,
        id_factory=lambda: f"id-{next(values)}",
    )


def test_all_five_analysis_methods_produce_expected_cases() -> None:
    service = _service()
    context = _context()

    perturbation = service._weight_perturbation(
        context,
        {
            "lower_delta": Decimal("0.01"),
            "upper_delta": Decimal("0.01"),
            "step": Decimal("0.01"),
        },
        "run-1",
        1,
        1,
        None,
    )
    criterion = service._criterion_removal(context, {}, "run-2", 1, 1, None)
    reversal = service._rank_reversal(context, {}, "run-3", 1, 1, None)
    group = service._group_influence(context, {}, "run-4", 1, 1, None)
    participant = service._participant_influence(context, {}, "run-5", 1, 1, None)

    assert len(perturbation) == 18
    assert len(criterion) == 6
    assert len(reversal) == 9
    assert len(group) == 2
    assert group[0].status == AnalysisCaseStatus.NOT_EVALUABLE
    assert group[1].status == AnalysisCaseStatus.EVALUATED
    assert len(participant) == 3
    assert all(item.status == AnalysisCaseStatus.EVALUATED for item in participant)


class _AnalysisRepository:
    def __init__(self) -> None:
        self.runs = []

    def find_success_by_input_hash(self, input_hash):
        return next(
            (
                run
                for run in self.runs
                if run.input_hash == input_hash and run.status == RunStatus.SUCCEEDED
            ),
            None,
        )

    def next_run_number(self, processing_run_id):
        return len(self.runs) + 1

    def add(self, run):
        self.runs.append(run)


class _UnitOfWork:
    def __init__(self) -> None:
        self.analysis_runs = _AnalysisRepository()
        self.audit_events = SimpleNamespace(events=[])
        self.audit_events.add = self.audit_events.events.append
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_arguments):
        return None

    def commit(self):
        self.commits += 1


def test_batch_isolates_failures_and_reuses_successful_inputs() -> None:
    context = _context()
    unit_of_work = _UnitOfWork()
    identifiers = count(1)
    service = RunSelectedAnalyses(
        lambda: unit_of_work,
        None,
        None,
        id_factory=lambda: f"batch-{next(identifiers)}",
    )
    command = RunSelectedAnalysesCommand(
        session_id="session-1",
        source_ranking_run_id="ranking-1",
        tests=(
            AnalysisTestSpec(AnalysisMethod.CRITERION_REMOVAL),
            AnalysisTestSpec(AnalysisMethod.RANK_REVERSAL),
        ),
        actor_id="admin-1",
        correlation_id="correlation-1",
    )
    original = service._execute_method

    def fail_first(context, method, *arguments):
        if method == AnalysisMethod.CRITERION_REMOVAL:
            raise RuntimeError("provider internals")
        return original(context, method, *arguments)

    progress = []
    with (
        patch.object(service, "_context", return_value=context),
        patch.object(service, "_execute_method", side_effect=fail_first),
    ):
        first = service.execute(command, on_progress=progress.append)

    assert tuple(item.status for item in first.outcomes) == (
        RunStatus.FAILED,
        RunStatus.SUCCEEDED,
    )
    assert first.outcomes[0].failure_detail == (
        "The selected analysis could not be completed."
    )
    assert len(unit_of_work.analysis_runs.runs) == 2
    assert len(unit_of_work.audit_events.events) == 2
    assert [item.phase for item in progress if item.test_index == 2] == [
        "validating",
        "preparing_baseline",
        *("evaluating_cases" for _ in range(9)),
        "summarizing",
        "persisting",
        "persisting",
    ]

    cached_command = RunSelectedAnalysesCommand(
        session_id="session-1",
        source_ranking_run_id="ranking-1",
        tests=(AnalysisTestSpec(AnalysisMethod.RANK_REVERSAL),),
        actor_id="admin-1",
    )
    with patch.object(service, "_context", return_value=context):
        cached = service.execute(cached_command)

    assert cached.outcomes[0].reused is True
    assert len(unit_of_work.analysis_runs.runs) == 2
