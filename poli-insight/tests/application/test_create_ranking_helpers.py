from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from poli_insight.application.ports.ranking import (
    RankingAlternativeInput,
    RankingAlternativeResult,
    RankingExecutionResult,
    RankingRunnerMetadata,
)
from poli_insight.application.use_cases.create_ranking import (
    CreateRanking,
    CreateRankingCommand,
)
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    AlgorithmRole,
    CriterionDataType,
    CriterionDirection,
    RunStatus,
    ScenarioSnapshotStatus,
    SessionStatus,
)
from poli_insight.domain.processing import ProcessingMatrix
from poli_insight.domain.scenario import (
    ScenarioAlternative,
    ScenarioCriterion,
    ScenarioMatrixValue,
)
from poli_insight.infrastructure.ranking.pydecision_topsis import (
    StaticRankingRunnerRegistry,
)


def test_shared_scores_receive_dense_rank_with_stable_display_order():
    alternatives = (
        RankingAlternativeInput("a", "a", "A", 2),
        RankingAlternativeInput("b", "b", "B", 0),
        RankingAlternativeInput("c", "c", "C", 1),
    )
    provider_values = (
        RankingAlternativeResult("a", Decimal("0.5000000000000000004")),
        RankingAlternativeResult("b", Decimal("0.9")),
        RankingAlternativeResult("c", Decimal("0.5000000000000000003")),
    )

    ranked = CreateRanking._ranked_alternatives(provider_values, alternatives)

    assert [(item.alternative_id, item.rank) for item in ranked] == [
        ("b", 1),
        ("c", 2),
        ("a", 2),
    ]
    assert ranked[1].preference_value == Decimal("0.5")


def test_create_ranking_generates_all_levels_and_reuses_exact_success():
    criterion_ids = ("criterion-cost", "criterion-benefit")
    matrices = (
        ProcessingMatrix.create(
            processing_matrix_id="matrix-participant",
            processing_run_id="weighting-1",
            level="participant",
            validation_id="validation-1",
            criterion_ids=criterion_ids,
            matrix_json={"values": [["1", "2"], ["0.5", "1"]]},
            weights_json={
                "shape": "crisp",
                "values": [
                    {"criterion_id": criterion_ids[0], "weight": Decimal("0.4")},
                    {"criterion_id": criterion_ids[1], "weight": Decimal("0.6")},
                ],
            },
            diagnostics_json={},
        ),
        ProcessingMatrix.create(
            processing_matrix_id="matrix-group",
            processing_run_id="weighting-1",
            level="stakeholder_group",
            stakeholder_group_id="group-1",
            criterion_ids=criterion_ids,
            matrix_json={"values": [["1", "2"], ["0.5", "1"]]},
            weights_json={
                "shape": "crisp",
                "values": [
                    {"criterion_id": criterion_ids[0], "weight": Decimal("0.5")},
                    {"criterion_id": criterion_ids[1], "weight": Decimal("0.5")},
                ],
            },
            diagnostics_json={},
        ),
        ProcessingMatrix.create(
            processing_matrix_id="matrix-session",
            processing_run_id="weighting-1",
            level="session",
            criterion_ids=criterion_ids,
            matrix_json={"values": [["1", "2"], ["0.5", "1"]]},
            weights_json={
                "shape": "crisp",
                "values": [
                    {"criterion_id": criterion_ids[0], "weight": Decimal("0.3")},
                    {"criterion_id": criterion_ids[1], "weight": Decimal("0.7")},
                ],
            },
            diagnostics_json={},
        ),
    )
    ranking_config = SimpleNamespace(
        role=AlgorithmRole.RANKING,
        execution_order=0,
        algorithm_implementation_id="ranking-method-1",
        parameter_json={},
        parameter_schema_version=1,
    )
    configuration = SimpleNamespace(
        configuration_version_id="configuration-1",
        scenario_snapshot_id="scenario-1",
        config_hash="c" * 64,
        algorithm_configs=(ranking_config,),
    )
    session = SimpleNamespace(
        status=SessionStatus.CLOSED,
        active_configuration_version_id="configuration-1",
        configurations=(configuration,),
    )
    source = SimpleNamespace(
        processing_run_id="weighting-1",
        session_id="session-1",
        configuration_version_id="configuration-1",
        scenario_snapshot_id="scenario-1",
        status=RunStatus.SUCCEEDED,
        roster_hash=hash_json([]),
        output_hash="d" * 64,
        matrices=matrices,
    )
    alternatives = (
        ScenarioAlternative("alternative-a", "a", "Option A", 0),
        ScenarioAlternative("alternative-b", "b", "Option B", 1),
    )
    criteria = (
        ScenarioCriterion(
            criterion_ids[0],
            "cost",
            "Cost",
            CriterionDirection.COST,
            CriterionDataType.NUMERIC,
            0,
        ),
        ScenarioCriterion(
            criterion_ids[1],
            "benefit",
            "Benefit",
            CriterionDirection.BENEFIT,
            CriterionDataType.NUMERIC,
            1,
        ),
    )
    scenario = SimpleNamespace(
        scenario_snapshot_id="scenario-1",
        status=ScenarioSnapshotStatus.READY,
        materialized_input_hash="e" * 64,
        alternatives=alternatives,
        criteria=criteria,
        matrix_values=tuple(
            ScenarioMatrixValue(
                alternative.alternative_id,
                criterion.criterion_id,
                {},
                value_numeric=Decimal(value),
            )
            for alternative, row in zip(
                alternatives,
                (("2", "8"), ("5", "3")),
                strict=True,
            )
            for criterion, value in zip(criteria, row, strict=True)
        ),
    )
    implementation = SimpleNamespace(
        algorithm_implementation_id="ranking-method-1",
        role=AlgorithmRole.RANKING,
        active=True,
        implementation_version="1.0.0",
        adapter_version="1.0.0",
        library_name="future-ranking-provider",
    )

    class Runner:
        metadata = RankingRunnerMetadata("ranking-method-1", "1.0.0", "1.0.0")

        def __init__(self):
            self.calls = 0

        def execute(self, request):
            self.calls += 1
            return RankingExecutionResult(
                alternatives=(
                    RankingAlternativeResult("alternative-a", Decimal("0.8")),
                    RankingAlternativeResult("alternative-b", Decimal("0.2")),
                ),
                metric_label="Preference",
                diagnostics_json={"method": "future"},
            )

    class RankingRepository:
        def __init__(self):
            self.runs = []

        def find_success_by_input_hash(self, input_hash):
            return next(
                (
                    item
                    for item in self.runs
                    if item.input_hash == input_hash
                    and item.status == RunStatus.SUCCEEDED
                ),
                None,
            )

        def next_run_number(self, session_id):
            return len(self.runs) + 1

        def add(self, run):
            self.runs.append(run)

    ranking_repository = RankingRepository()
    audit_events = SimpleNamespace(
        events=[], add=lambda item: audit_events.events.append(item)
    )

    class UnitOfWork:
        def __init__(self):
            self.session = SimpleNamespace(get=lambda session_id: session)
            self.processing_runs = SimpleNamespace(get=lambda run_id: source)
            self.scenarios = SimpleNamespace(get_by_id=lambda snapshot_id: scenario)
            self.algorithms = SimpleNamespace(get_many=lambda ids: (implementation,))
            self.submissions = SimpleNamespace(
                list_effective_for_configuration=lambda configuration_id: ()
            )
            self.participants = SimpleNamespace(get_many=lambda ids: ())
            self.ranking_runs = ranking_repository
            self.audit_events = audit_events
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def commit(self):
            self.committed = True

    runner = Runner()
    use_case = CreateRanking(
        UnitOfWork,
        StaticRankingRunnerRegistry(runner),
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
        id_factory=lambda: str(uuid4()),
    )
    command = CreateRankingCommand(
        session_id="session-1",
        source_processing_run_id="weighting-1",
        actor_id="admin-1",
    )

    first = use_case.execute(command)
    second = use_case.execute(command)

    assert first.status == RunStatus.SUCCEEDED
    assert first.result_count == 3
    assert second.reused
    assert second.ranking_run_id == first.ranking_run_id
    assert runner.calls == 3
    assert len(ranking_repository.runs) == 1
    assert {item.level for item in ranking_repository.runs[0].results} == {
        "participant",
        "stakeholder_group",
        "session",
    }
    assert (
        next(
            item
            for item in ranking_repository.runs[0].results
            if item.level == "stakeholder_group"
        ).validation_id
        is None
    )
