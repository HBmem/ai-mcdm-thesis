"""Execute selected sensitivity and robustness tests as immutable child runs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from platform import python_version
from typing import Any

from poli_insight.application.analysis_metrics import (
    comparison_metrics,
    ranking_manifest,
)
from poli_insight.application.ports.ranking import (
    RankingContractViolation,
    RankingRequest,
    RankingWeightInput,
)
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.ranking_support import (
    ranked_alternatives,
    ranking_request_for_matrix,
)
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.application.use_cases.finalize_validation_bundle import (
    _decimal_matrix,
    _diagnostics,
    _geometric_mean_matrices,
    _prepared_for_aggregate,
    _weighted_geometric_matrices,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.analysis import (
    AnalysisArtifact,
    AnalysisCase,
    AnalysisRun,
    analysis_type_for,
)
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AnalysisCaseStatus,
    AnalysisMethod,
    ArtifactType,
    AuditAction,
    RunInclusionStatus,
    RunStatus,
    ScenarioSnapshotStatus,
)


class RunSelectedAnalysesError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class AnalysisTestSpec:
    method: AnalysisMethod
    parameters: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunSelectedAnalysesCommand:
    session_id: str
    source_ranking_run_id: str
    tests: tuple[AnalysisTestSpec, ...]
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True)
class AnalysisProgress:
    method: AnalysisMethod
    test_index: int
    total_tests: int
    phase: str
    completed_cases: int
    total_cases: int
    message: str


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    method: AnalysisMethod
    analysis_run_id: str
    run_number: int
    status: RunStatus
    reused: bool
    evaluated_cases: int
    not_evaluable_cases: int
    failure_detail: str | None = None


@dataclass(frozen=True, slots=True)
class RunSelectedAnalysesResult:
    outcomes: tuple[AnalysisOutcome, ...]


@dataclass(slots=True)
class _Context:
    session: Any
    configuration: Any
    source: Any
    ranking: Any
    scenario: Any
    weighting_runner: Any
    ranking_runner: Any
    weighting_parameters: Mapping[str, object]
    ranking_parameters: Mapping[str, object]
    scopes: tuple[tuple[Any, Any, RankingRequest], ...]


class RunSelectedAnalyses:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        weighting_registry,
        ranking_registry,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._weighting_registry = weighting_registry
        self._ranking_registry = ranking_registry
        self._clock = clock
        self._id_factory = id_factory

    def execute(
        self,
        command: RunSelectedAnalysesCommand,
        *,
        on_progress: Callable[[AnalysisProgress], None] | None = None,
    ) -> RunSelectedAnalysesResult:
        if not command.tests:
            raise RunSelectedAnalysesError("Select at least one analysis test.")
        methods = tuple(item.method for item in command.tests)
        if len(set(methods)) != len(methods):
            raise RunSelectedAnalysesError("Each analysis test may be selected once.")
        outcomes: list[AnalysisOutcome] = []
        for index, spec in enumerate(command.tests, start=1):
            outcomes.append(
                self._run_one(
                    command,
                    spec,
                    index=index,
                    total=len(command.tests),
                    on_progress=on_progress,
                )
            )
        return RunSelectedAnalysesResult(tuple(outcomes))

    def _run_one(self, command, spec, *, index, total, on_progress) -> AnalysisOutcome:
        self._progress(
            on_progress,
            spec.method,
            index,
            total,
            "validating",
            0,
            1,
            "Validating frozen analysis inputs",
        )
        with self._unit_of_work_factory() as unit_of_work:
            context = self._context(unit_of_work, command)
            parameters = self._parameters(spec)
            input_manifest = self._input_manifest(context, spec.method, parameters)
            input_hash = hash_json(input_manifest)
            reused = unit_of_work.analysis_runs.find_success_by_input_hash(input_hash)
            if reused is not None:
                self._progress(
                    on_progress,
                    spec.method,
                    index,
                    total,
                    "persisting",
                    1,
                    1,
                    "Reused matching immutable analysis",
                )
                return self._outcome(reused, reused=True)

            run_id = self._id_factory()
            run_number = unit_of_work.analysis_runs.next_run_number(
                context.source.processing_run_id
            )
            created_at = self._clock()
            input_artifact = AnalysisArtifact.create(
                analysis_artifact_id=self._id_factory(),
                analysis_run_id=run_id,
                artifact_type=ArtifactType.INPUT_MANIFEST,
                schema_version=1,
                content_json=input_manifest,
            )
            base = {
                "analysis_run_id": run_id,
                "session_id": command.session_id,
                "source_processing_run_id": context.source.processing_run_id,
                "source_ranking_run_id": context.ranking.ranking_run_id,
                "run_number": run_number,
                "analysis_type": analysis_type_for(spec.method),
                "method": spec.method,
                "source_processing_output_hash": context.source.output_hash,
                "source_ranking_output_hash": context.ranking.output_hash,
                "input_hash": input_hash,
                "parameter_json": parameters,
                "environment_json": {
                    "analysis_schema_version": 1,
                    "application_version": _package_version("poli-insight"),
                    "python_version": python_version(),
                    "weighting_adapter_version": context.weighting_runner.metadata.adapter_version,
                    "ranking_adapter_version": context.ranking_runner.metadata.adapter_version,
                },
                "created_at": created_at,
                "created_by": command.actor_id,
                "correlation_id": command.correlation_id,
            }
            try:
                self._progress(
                    on_progress,
                    spec.method,
                    index,
                    total,
                    "preparing_baseline",
                    0,
                    1,
                    "Preparing persisted baseline rankings",
                )
                cases = self._execute_method(
                    context, spec.method, parameters, run_id, index, total, on_progress
                )
                self._progress(
                    on_progress,
                    spec.method,
                    index,
                    total,
                    "summarizing",
                    len(cases),
                    len(cases),
                    "Summarizing analysis evidence",
                )
                summary = _summary(spec.method, cases)
                structured = AnalysisArtifact.create(
                    analysis_artifact_id=self._id_factory(),
                    analysis_run_id=run_id,
                    artifact_type=ArtifactType.STRUCTURED_RESULT,
                    schema_version=1,
                    content_json={
                        "schema_version": 1,
                        "method": spec.method.value,
                        "summary": summary,
                        "case_hashes": [item.content_hash for item in cases],
                    },
                )
                safe_bundle = AnalysisArtifact.create(
                    analysis_artifact_id=self._id_factory(),
                    analysis_run_id=run_id,
                    artifact_type=ArtifactType.ANALYSIS_BUNDLE,
                    schema_version=1,
                    content_json={
                        "schema_version": 1,
                        "method": spec.method.value,
                        "tested_assumptions": parameters,
                        "summary": summary,
                        "participant_identifiers_included": False,
                    },
                )
                run = AnalysisRun.succeeded(
                    **base,
                    completed_at=self._clock(),
                    cases=cases,
                    artifacts=(input_artifact, structured, safe_bundle),
                )
            except Exception as error:  # noqa: BLE001 - isolate each selected test
                run = AnalysisRun.failed(
                    **base,
                    completed_at=self._clock(),
                    failure_code="analysis.execution_failed",
                    failure_detail=_safe_error(error),
                    cases=(),
                    artifacts=(input_artifact,),
                )
            self._progress(
                on_progress,
                spec.method,
                index,
                total,
                "persisting",
                0,
                1,
                "Persisting immutable analysis evidence",
            )
            unit_of_work.analysis_runs.add(run)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=run.completed_at,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.ANALYZED,
                    entity_type="analysis_run",
                    entity_id=run_id,
                    correlation_id=command.correlation_id,
                    use_case="run_selected_analyses",
                    before_json=None,
                    after_json={
                        "method": spec.method.value,
                        "status": run.status.value,
                        "input_hash": input_hash,
                        "output_hash": run.output_hash,
                        "case_count": len(run.cases),
                    },
                )
            )
            unit_of_work.commit()
            self._progress(
                on_progress,
                spec.method,
                index,
                total,
                "persisting",
                1,
                1,
                "Analysis test complete",
            )
            return self._outcome(run, reused=False)

    def _context(self, unit_of_work, command) -> _Context:
        ranking = unit_of_work.ranking_runs.get(command.source_ranking_run_id)
        if (
            ranking is None
            or ranking.status != RunStatus.SUCCEEDED
            or ranking.session_id != command.session_id
        ):
            raise RunSelectedAnalysesError(
                "A successful ranking run from this session is required."
            )
        source = unit_of_work.processing_runs.get(ranking.source_processing_run_id)
        if (
            source is None
            or source.status != RunStatus.SUCCEEDED
            or source.output_hash is None
        ):
            raise RunSelectedAnalysesError(
                "The ranking source weighting run is unavailable."
            )
        session = unit_of_work.session.get(command.session_id)
        if session is None:
            raise RunSelectedAnalysesError("The selected session was not found.")
        configuration = next(
            (
                item
                for item in session.configurations
                if item.configuration_version_id == source.configuration_version_id
            ),
            None,
        )
        if configuration is None:
            raise RunSelectedAnalysesError(
                "The frozen session configuration is unavailable."
            )
        scenario = unit_of_work.scenarios.get_by_id(source.scenario_snapshot_id)
        if scenario is None or scenario.status != ScenarioSnapshotStatus.READY:
            raise RunSelectedAnalysesError("The frozen ready scenario is unavailable.")
        weighting_impl = unit_of_work.algorithms.get_many(
            (source.algorithm_implementation_id,)
        )
        ranking_impl = unit_of_work.algorithms.get_many(
            (ranking.algorithm_implementation_id,)
        )
        if not weighting_impl or not ranking_impl:
            raise RunSelectedAnalysesError(
                "A frozen algorithm implementation is unavailable."
            )
        weighting_runner = self._weighting_registry.get(
            source.algorithm_implementation_id
        )
        ranking_runner = self._ranking_registry.get(ranking.algorithm_implementation_id)
        if (
            weighting_runner.metadata.validator_version
            != weighting_impl[0].implementation_version
            or weighting_runner.metadata.adapter_version
            != weighting_impl[0].adapter_version
        ):
            raise RunSelectedAnalysesError(
                "The weighting adapter no longer matches the frozen implementation."
            )
        if (
            ranking_runner.metadata.implementation_version
            != ranking.implementation_version
            or ranking_runner.metadata.adapter_version != ranking.adapter_version
        ):
            raise RunSelectedAnalysesError(
                "The ranking adapter no longer matches the source ranking run."
            )
        results_by_matrix = {
            item.source_processing_matrix_id: item for item in ranking.results
        }
        scopes = []
        for matrix in source.matrices:
            if matrix.level not in {"stakeholder_group", "session"}:
                continue
            baseline = results_by_matrix.get(matrix.processing_matrix_id)
            if baseline is None:
                raise RunSelectedAnalysesError(
                    "The source ranking is missing an aggregate baseline."
                )
            scopes.append(
                (
                    matrix,
                    baseline,
                    ranking_request_for_matrix(
                        matrix, scenario, ranking.parameter_json
                    ),
                )
            )
        if not scopes:
            raise RunSelectedAnalysesError(
                "No aggregate ranking evidence is available."
            )
        return _Context(
            session=session,
            configuration=configuration,
            source=source,
            ranking=ranking,
            scenario=scenario,
            weighting_runner=weighting_runner,
            ranking_runner=ranking_runner,
            weighting_parameters=source.parameter_json,
            ranking_parameters=ranking.parameter_json,
            scopes=tuple(scopes),
        )

    @staticmethod
    def _parameters(spec: AnalysisTestSpec) -> dict[str, object]:
        if spec.method != AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION:
            return {}
        lower = Decimal(str(spec.parameters.get("lower_delta", "0.20")))
        upper = Decimal(str(spec.parameters.get("upper_delta", "0.20")))
        step = Decimal(str(spec.parameters.get("step", "0.01")))
        if (
            lower < 0
            or upper < 0
            or lower > 1
            or upper > 1
            or step < Decimal("0.001")
            or step > Decimal("0.10")
        ):
            raise RunSelectedAnalysesError(
                "Weight perturbation parameters are outside the supported range."
            )
        return {"lower_delta": lower, "upper_delta": upper, "step": step}

    @staticmethod
    def _input_manifest(context, method, parameters):
        return {
            "schema_version": 1,
            **(
                {
                    "method_revision": 2,
                    "required_group_handling": "counterfactual_omission_allowed",
                }
                if method == AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE
                else {}
            ),
            "method": method.value,
            "parameters": parameters,
            "session_id": context.ranking.session_id,
            "source_processing_run_id": context.source.processing_run_id,
            "source_processing_output_hash": context.source.output_hash,
            "source_ranking_run_id": context.ranking.ranking_run_id,
            "source_ranking_output_hash": context.ranking.output_hash,
            "scenario_snapshot_id": context.source.scenario_snapshot_id,
            "configuration_version_id": context.source.configuration_version_id,
            "weighting_algorithm_id": context.source.algorithm_implementation_id,
            "weighting_adapter_version": context.weighting_runner.metadata.adapter_version,
            "ranking_algorithm_id": context.ranking.algorithm_implementation_id,
            "ranking_adapter_version": context.ranking.adapter_version,
        }

    def _execute_method(
        self, context, method, parameters, run_id, index, total, callback
    ):
        handlers = {
            AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION: self._weight_perturbation,
            AnalysisMethod.CRITERION_REMOVAL: self._criterion_removal,
            AnalysisMethod.RANK_REVERSAL: self._rank_reversal,
            AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE: self._group_influence,
            AnalysisMethod.PARTICIPANT_INFLUENCE: self._participant_influence,
        }
        return handlers[method](context, parameters, run_id, index, total, callback)

    def _weight_perturbation(self, context, parameters, run_id, index, total, callback):
        planned = []
        for matrix, baseline, request in context.scopes:
            for weight in request.weights:
                if not isinstance(weight.value, Decimal):
                    raise RunSelectedAnalysesError(
                        "Weight perturbation requires crisp weights."
                    )
                for candidate in _weight_grid(weight.value, parameters):
                    planned.append(
                        (matrix, baseline, request, weight.criterion_id, candidate)
                    )
        cases = []
        for sequence, (matrix, baseline, request, criterion_id, candidate) in enumerate(
            planned, start=1
        ):
            weights, fallback = _perturbed_weights(
                request.weights, criterion_id, candidate
            )
            ranked = self._rank(
                context.ranking_runner, replace(request, weights=weights)
            )
            warnings = ("equal_residual_distribution",) if fallback else ()
            baseline_weight = next(
                item.value
                for item in request.weights
                if item.criterion_id == criterion_id
            )
            cases.append(
                self._case(
                    run_id,
                    sequence,
                    matrix.level,
                    matrix.stakeholder_group_id,
                    "criterion",
                    criterion_id,
                    {"baseline_weight": baseline_weight, "candidate_weight": candidate},
                    {
                        "ranking": ranking_manifest(ranked),
                        "metrics": comparison_metrics(baseline.alternatives, ranked),
                    },
                    warnings=warnings,
                )
            )
            self._progress(
                callback,
                AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION,
                index,
                total,
                "evaluating_cases",
                sequence,
                len(planned),
                f"Perturbed criterion {sequence} of {len(planned)}",
            )
        return tuple(cases)

    def _criterion_removal(self, context, parameters, run_id, index, total, callback):
        planned = [
            (matrix, baseline, request, position)
            for matrix, baseline, request in context.scopes
            for position in range(len(request.criteria))
        ]
        cases = []
        for sequence, (matrix, baseline, request, position) in enumerate(
            planned, start=1
        ):
            criterion = request.criteria[position]
            if len(request.criteria) == 1:
                cases.append(
                    self._not_evaluable(
                        run_id,
                        sequence,
                        matrix.level,
                        matrix.stakeholder_group_id,
                        "criterion",
                        criterion.criterion_id,
                        "analysis.single_criterion",
                        input_json={"removed_criterion_id": criterion.criterion_id},
                    )
                )
            else:
                values = _decimal_matrix(matrix.matrix_json)
                reduced_values = tuple(
                    tuple(
                        value for column, value in enumerate(row) if column != position
                    )
                    for row_index, row in enumerate(values)
                    if row_index != position
                )
                criterion_ids = tuple(
                    item.criterion_id
                    for offset, item in enumerate(request.criteria)
                    if offset != position
                )
                weighting = context.weighting_runner.execute(
                    _prepared_for_aggregate(run_id, criterion_ids, reduced_values),
                    context.weighting_parameters,
                )
                if not weighting.crisp_weights:
                    raise RunSelectedAnalysesError(
                        "Criterion removal currently requires crisp weights."
                    )
                weights = tuple(
                    RankingWeightInput(item, value)
                    for item, value in zip(
                        criterion_ids, weighting.crisp_weights, strict=True
                    )
                )
                reduced = replace(
                    request,
                    criteria=tuple(
                        item
                        for offset, item in enumerate(request.criteria)
                        if offset != position
                    ),
                    cells=tuple(
                        item
                        for item in request.cells
                        if item.criterion_id != criterion.criterion_id
                    ),
                    weights=weights,
                )
                ranked = self._rank(context.ranking_runner, reduced)
                diagnostics = _diagnostics(
                    weighting, context.configuration.consistency_threshold
                )
                warnings = (
                    ("consistency.threshold_exceeded",)
                    if diagnostics.get("threshold_exceeded")
                    else ()
                )
                cases.append(
                    self._case(
                        run_id,
                        sequence,
                        matrix.level,
                        matrix.stakeholder_group_id,
                        "criterion",
                        criterion.criterion_id,
                        {"removed_criterion_id": criterion.criterion_id},
                        {
                            "ranking": ranking_manifest(ranked),
                            "metrics": comparison_metrics(
                                baseline.alternatives, ranked
                            ),
                            "weighting_diagnostics": diagnostics,
                        },
                        warnings=warnings,
                    )
                )
            self._progress(
                callback,
                AnalysisMethod.CRITERION_REMOVAL,
                index,
                total,
                "evaluating_cases",
                sequence,
                len(planned),
                f"Removed criterion {sequence} of {len(planned)}",
            )
        return tuple(cases)

    def _rank_reversal(self, context, parameters, run_id, index, total, callback):
        planned = [
            (matrix, baseline, request, alternative)
            for matrix, baseline, request in context.scopes
            for alternative in request.alternatives
        ]
        cases = []
        for sequence, (matrix, baseline, request, alternative) in enumerate(
            planned, start=1
        ):
            if len(request.alternatives) < 3:
                cases.append(
                    self._not_evaluable(
                        run_id,
                        sequence,
                        matrix.level,
                        matrix.stakeholder_group_id,
                        "alternative",
                        alternative.alternative_id,
                        "analysis.too_few_alternatives",
                        input_json={
                            "removed_alternative_id": alternative.alternative_id
                        },
                    )
                )
            else:
                reduced = replace(
                    request,
                    alternatives=tuple(
                        item
                        for item in request.alternatives
                        if item.alternative_id != alternative.alternative_id
                    ),
                    cells=tuple(
                        item
                        for item in request.cells
                        if item.alternative_id != alternative.alternative_id
                    ),
                )
                ranked = self._rank(context.ranking_runner, reduced)
                cases.append(
                    self._case(
                        run_id,
                        sequence,
                        matrix.level,
                        matrix.stakeholder_group_id,
                        "alternative",
                        alternative.alternative_id,
                        {"removed_alternative_id": alternative.alternative_id},
                        {
                            "ranking": ranking_manifest(ranked),
                            "metrics": comparison_metrics(
                                baseline.alternatives, ranked
                            ),
                        },
                    )
                )
            self._progress(
                callback,
                AnalysisMethod.RANK_REVERSAL,
                index,
                total,
                "evaluating_cases",
                sequence,
                len(planned),
                f"Removed alternative {sequence} of {len(planned)}",
            )
        return tuple(cases)

    def _group_influence(self, context, parameters, run_id, index, total, callback):
        groups = {
            item.session_stakeholder_group_id: item
            for item in context.configuration.stakeholder_groups
            if item.is_active
        }
        group_matrices = {
            item.stakeholder_group_id: _decimal_matrix(item.matrix_json)
            for item in context.source.matrices
            if item.level == "stakeholder_group"
        }
        required = set(
            context.configuration.required_group_policy_json.get(
                "required_group_keys", []
            )
        )
        contributor_counts = defaultdict(int)
        for item in context.source.submissions:
            if item.inclusion_status == RunInclusionStatus.INCLUDED:
                contributor_counts[item.stakeholder_group_id] += 1
        baseline_by_group = {
            matrix.stakeholder_group_id: ranking_manifest(baseline.alternatives)
            for matrix, baseline, _request in context.scopes
            if matrix.level == "stakeholder_group"
        }
        session_matrix, baseline, request = next(
            item for item in context.scopes if item[0].level == "session"
        )
        planned = sorted(group_matrices)
        if not planned:
            case = self._not_evaluable(
                run_id,
                1,
                "session",
                None,
                "stakeholder_group",
                None,
                "analysis.no_included_groups",
            )
            self._progress(
                callback,
                AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE,
                index,
                total,
                "evaluating_cases",
                1,
                1,
                "No stakeholder groups were available to evaluate",
            )
            return (case,)
        cases = []
        for sequence, omitted in enumerate(planned, start=1):
            group = groups[omitted]
            case_input = {
                "omitted_group_id": omitted,
                "group_key": group.group_key,
                "allocation": Decimal(group.allocation_units)
                / Decimal(context.configuration.allocation_total_units),
                "contributor_count": contributor_counts[omitted],
                "required_group_keys": sorted(required),
            }
            remaining = {
                key: value for key, value in group_matrices.items() if key != omitted
            }
            if not remaining:
                case = self._not_evaluable(
                    run_id,
                    sequence,
                    "session",
                    None,
                    "stakeholder_group",
                    omitted,
                    "analysis.no_groups_remain",
                    input_json=case_input,
                )
            elif sum(groups[key].allocation_units for key in remaining) <= 0:
                case = self._not_evaluable(
                    run_id,
                    sequence,
                    "session",
                    None,
                    "stakeholder_group",
                    omitted,
                    "analysis.nonpositive_remaining_allocation",
                    input_json=case_input,
                )
            else:
                allocations = _normalized_allocations(groups, remaining)
                values = _weighted_geometric_matrices(remaining, allocations)
                weighting = context.weighting_runner.execute(
                    _prepared_for_aggregate(
                        run_id, session_matrix.criterion_ids, values
                    ),
                    context.weighting_parameters,
                )
                ranked = self._rank(
                    context.ranking_runner,
                    replace(request, weights=_result_weights(weighting)),
                )
                diagnostics = _diagnostics(
                    weighting, context.configuration.consistency_threshold
                )
                case = self._case(
                    run_id,
                    sequence,
                    "session",
                    None,
                    "stakeholder_group",
                    omitted,
                    case_input,
                    {
                        "ranking": ranking_manifest(ranked),
                        "metrics": comparison_metrics(baseline.alternatives, ranked),
                        "omitted_group_baseline_ranking": baseline_by_group.get(
                            omitted
                        ),
                        "weighting_diagnostics": diagnostics,
                    },
                    warnings=("consistency.threshold_exceeded",)
                    if diagnostics.get("threshold_exceeded")
                    else (),
                )
            cases.append(case)
            self._progress(
                callback,
                AnalysisMethod.STAKEHOLDER_GROUP_INFLUENCE,
                index,
                total,
                "evaluating_cases",
                sequence,
                len(planned),
                f"Evaluated stakeholder group {sequence} of {len(planned)}",
            )
        return tuple(cases)

    def _participant_influence(
        self, context, parameters, run_id, index, total, callback
    ):
        groups = {
            item.session_stakeholder_group_id: item
            for item in context.configuration.stakeholder_groups
            if item.is_active
        }
        required = set(
            context.configuration.required_group_policy_json.get(
                "required_group_keys", []
            )
        )
        participant_matrices = {
            item.validation_id: item
            for item in context.source.matrices
            if item.level == "participant"
        }
        included = [
            item
            for item in context.source.submissions
            if item.inclusion_status == RunInclusionStatus.INCLUDED
            and item.validation_id in participant_matrices
        ]
        if not included:
            case = self._not_evaluable(
                run_id,
                1,
                "session",
                None,
                "participant",
                None,
                "analysis.no_included_participants",
            )
            self._progress(
                callback,
                AnalysisMethod.PARTICIPANT_INFLUENCE,
                index,
                total,
                "evaluating_cases",
                1,
                1,
                "No included participants were available to evaluate",
            )
            return (case,)
        by_group = defaultdict(list)
        for item in included:
            by_group[item.stakeholder_group_id].append(
                participant_matrices[item.validation_id]
            )
        persisted_groups = {
            item.stakeholder_group_id: _decimal_matrix(item.matrix_json)
            for item in context.source.matrices
            if item.level == "stakeholder_group"
        }
        session_matrix, session_baseline, session_request = next(
            item for item in context.scopes if item[0].level == "session"
        )
        baseline_by_group = {
            matrix.stakeholder_group_id: (baseline, request)
            for matrix, baseline, request in context.scopes
            if matrix.level == "stakeholder_group"
        }
        cases = []
        for sequence, omitted in enumerate(included, start=1):
            group = groups[omitted.stakeholder_group_id]
            case_input = {
                "omitted_participant_id": omitted.participant_id,
                "stakeholder_group_id": omitted.stakeholder_group_id,
                "group_key": group.group_key,
                "required_group_keys": sorted(required),
            }
            remaining_members = [
                item
                for item in by_group[omitted.stakeholder_group_id]
                if item.validation_id != omitted.validation_id
            ]
            if not remaining_members and group.group_key in required:
                case = self._not_evaluable(
                    run_id,
                    sequence,
                    "participant",
                    omitted.stakeholder_group_id,
                    "participant",
                    omitted.participant_id,
                    "analysis.required_group_would_be_empty",
                    input_json=case_input,
                )
            else:
                group_values = dict(persisted_groups)
                group_metrics = None
                group_ranking = None
                group_diagnostics = None
                if remaining_members:
                    rebuilt = _geometric_mean_matrices(
                        [
                            _decimal_matrix(item.matrix_json)
                            for item in remaining_members
                        ]
                    )
                    group_values[omitted.stakeholder_group_id] = rebuilt
                    group_weighting = context.weighting_runner.execute(
                        _prepared_for_aggregate(
                            run_id, session_matrix.criterion_ids, rebuilt
                        ),
                        context.weighting_parameters,
                    )
                    group_baseline, group_request = baseline_by_group[
                        omitted.stakeholder_group_id
                    ]
                    group_ranked = self._rank(
                        context.ranking_runner,
                        replace(
                            group_request, weights=_result_weights(group_weighting)
                        ),
                    )
                    group_ranking = ranking_manifest(group_ranked)
                    group_metrics = comparison_metrics(
                        group_baseline.alternatives, group_ranked
                    )
                    group_diagnostics = _diagnostics(
                        group_weighting,
                        context.configuration.consistency_threshold,
                    )
                else:
                    group_values.pop(omitted.stakeholder_group_id, None)
                if not group_values:
                    case = self._not_evaluable(
                        run_id,
                        sequence,
                        "participant",
                        omitted.stakeholder_group_id,
                        "participant",
                        omitted.participant_id,
                        "analysis.no_groups_remain",
                        input_json=case_input,
                    )
                else:
                    allocations = _normalized_allocations(groups, group_values)
                    session_values = _weighted_geometric_matrices(
                        group_values, allocations
                    )
                    session_weighting = context.weighting_runner.execute(
                        _prepared_for_aggregate(
                            run_id, session_matrix.criterion_ids, session_values
                        ),
                        context.weighting_parameters,
                    )
                    session_ranked = self._rank(
                        context.ranking_runner,
                        replace(
                            session_request, weights=_result_weights(session_weighting)
                        ),
                    )
                    session_diagnostics = _diagnostics(
                        session_weighting,
                        context.configuration.consistency_threshold,
                    )
                    threshold_warning = any(
                        diagnostics and diagnostics.get("threshold_exceeded")
                        for diagnostics in (group_diagnostics, session_diagnostics)
                    )
                    case = self._case(
                        run_id,
                        sequence,
                        "participant",
                        omitted.stakeholder_group_id,
                        "participant",
                        omitted.participant_id,
                        case_input,
                        {
                            "session_ranking": ranking_manifest(session_ranked),
                            "session_metrics": comparison_metrics(
                                session_baseline.alternatives, session_ranked
                            ),
                            "group_ranking": group_ranking,
                            "group_metrics": group_metrics,
                            "group_weighting_diagnostics": group_diagnostics,
                            "session_weighting_diagnostics": session_diagnostics,
                        },
                        warnings=("consistency.threshold_exceeded",)
                        if threshold_warning
                        else (),
                    )
            cases.append(case)
            self._progress(
                callback,
                AnalysisMethod.PARTICIPANT_INFLUENCE,
                index,
                total,
                "evaluating_cases",
                sequence,
                len(included),
                f"Evaluated participant {sequence} of {len(included)}",
            )
        return tuple(cases)

    @staticmethod
    def _rank(runner, request):
        execution = runner.execute(request)
        return ranked_alternatives(execution.alternatives, request.alternatives)

    def _case(
        self,
        run_id,
        sequence,
        scope_type,
        scope_id,
        subject_type,
        subject_id,
        input_json,
        result_json,
        *,
        warnings=(),
    ):
        return AnalysisCase.create(
            analysis_case_id=self._id_factory(),
            analysis_run_id=run_id,
            sequence=sequence,
            status=AnalysisCaseStatus.EVALUATED,
            scope_type=scope_type,
            scope_id=scope_id,
            subject_type=subject_type,
            subject_id=subject_id,
            input_json=input_json,
            result_json=result_json,
            warnings=tuple(warnings),
        )

    def _not_evaluable(
        self,
        run_id,
        sequence,
        scope_type,
        scope_id,
        subject_type,
        subject_id,
        reason,
        *,
        input_json=None,
    ):
        return AnalysisCase.create(
            analysis_case_id=self._id_factory(),
            analysis_run_id=run_id,
            sequence=sequence,
            status=AnalysisCaseStatus.NOT_EVALUABLE,
            scope_type=scope_type,
            scope_id=scope_id,
            subject_type=subject_type,
            subject_id=subject_id,
            input_json=input_json or {},
            result_json={"reason": reason},
            warnings=(reason,),
        )

    @staticmethod
    def _progress(callback, method, index, total, phase, completed, cases, message):
        if callback is not None:
            callback(
                AnalysisProgress(method, index, total, phase, completed, cases, message)
            )

    @staticmethod
    def _outcome(run, *, reused):
        return AnalysisOutcome(
            method=run.method,
            analysis_run_id=run.analysis_run_id,
            run_number=run.run_number,
            status=run.status,
            reused=reused,
            evaluated_cases=sum(
                item.status == AnalysisCaseStatus.EVALUATED for item in run.cases
            ),
            not_evaluable_cases=sum(
                item.status == AnalysisCaseStatus.NOT_EVALUABLE for item in run.cases
            ),
            failure_detail=run.failure_detail,
        )


def _weight_grid(
    baseline: Decimal, parameters: Mapping[str, object]
) -> tuple[Decimal, ...]:
    lower = max(Decimal(0), baseline - Decimal(str(parameters["lower_delta"])))
    upper = min(Decimal(1), baseline + Decimal(str(parameters["upper_delta"])))
    step = Decimal(str(parameters["step"]))
    values = {baseline, lower, upper}
    current = lower
    while current <= upper:
        values.add(current)
        current += step
    return tuple(sorted(values))


def _perturbed_weights(weights, criterion_id, candidate):
    baseline = next(item.value for item in weights if item.criterion_id == criterion_id)
    if not isinstance(baseline, Decimal):
        raise RankingContractViolation("Weight perturbation requires crisp weights.")
    residual = Decimal(1) - baseline
    fallback = residual == 0 and len(weights) > 1 and candidate < 1
    result = []
    for item in weights:
        if not isinstance(item.value, Decimal):
            raise RankingContractViolation(
                "Weight perturbation requires crisp weights."
            )
        if item.criterion_id == criterion_id:
            value = candidate
        elif fallback:
            value = (Decimal(1) - candidate) / Decimal(len(weights) - 1)
        elif residual == 0:
            value = Decimal(0)
        else:
            value = item.value * (Decimal(1) - candidate) / residual
        result.append(RankingWeightInput(item.criterion_id, value))
    return tuple(result), fallback


def _result_weights(result):
    if not result.crisp_weights:
        raise RunSelectedAnalysesError(
            "This analysis iteration requires crisp weights."
        )
    return tuple(
        RankingWeightInput(item, value)
        for item, value in zip(result.criterion_ids, result.crisp_weights, strict=True)
    )


def _normalized_allocations(groups, matrices):
    raw = {key: Decimal(groups[key].allocation_units) for key in matrices}
    total = sum(raw.values(), Decimal(0))
    if total <= 0:
        raise RunSelectedAnalysesError(
            "Remaining stakeholder allocation is not positive."
        )
    return {key: value / total for key, value in raw.items()}


def _summary(method, cases):
    evaluated = [item for item in cases if item.status == AnalysisCaseStatus.EVALUATED]
    changed = 0
    max_displacement = 0
    reversals = 0
    for item in evaluated:
        metrics = (
            item.result_json.get("metrics")
            or item.result_json.get("session_metrics")
            or {}
        )
        if isinstance(metrics, Mapping):
            changed += bool(metrics.get("top_set_changed"))
            max_displacement = max(
                max_displacement, int(metrics.get("maximum_rank_displacement", 0))
            )
            reversals += int(metrics.get("strict_reversals", 0))
    summary = {
        "method": method.value,
        "case_count": len(cases),
        "evaluated_count": len(evaluated),
        "not_evaluable_count": len(cases) - len(evaluated),
        "top_set_change_count": changed,
        "maximum_rank_displacement": max_displacement,
        "strict_reversal_count": reversals,
        "instability_detected": changed > 0 or reversals > 0,
    }
    if method == AnalysisMethod.ONE_AT_A_TIME_WEIGHT_PERTURBATION:
        summary["sampled_stability"] = _sampled_stability(evaluated)
    if method == AnalysisMethod.PARTICIPANT_INFLUENCE:
        displacement_counts = defaultdict(int)
        for item in evaluated:
            metrics = item.result_json.get("session_metrics", {})
            displacement_counts[int(metrics.get("maximum_rank_displacement", 0))] += 1
        summary["effect_distribution"] = {
            "session_maximum_rank_displacement_counts": {
                str(key): value for key, value in sorted(displacement_counts.items())
            },
            "participant_identifiers_included": False,
        }
    return summary


def _sampled_stability(cases):
    grouped = defaultdict(list)
    for item in cases:
        grouped[(item.scope_type, item.scope_id, item.subject_id)].append(item)
    results = []
    for (scope_type, scope_id, criterion_id), values in sorted(
        grouped.items(), key=lambda entry: tuple(str(value or "") for value in entry[0])
    ):
        points = sorted(
            (
                Decimal(str(item.input_json["candidate_weight"])),
                bool(item.result_json["metrics"]["top_set_changed"]),
                item.result_json["metrics"].get("candidate_score_margin"),
            )
            for item in values
        )
        baseline = Decimal(str(values[0].input_json["baseline_weight"]))
        lower = [
            (weight, changed) for weight, changed, _ in points if weight <= baseline
        ]
        upper = [
            (weight, changed) for weight, changed, _ in points if weight >= baseline
        ]
        lower_change = next(
            (weight for weight, changed in reversed(lower) if changed), None
        )
        upper_change = next((weight for weight, changed in upper if changed), None)
        stable_lower = next(
            (
                weight
                for weight, changed in lower
                if not changed and (lower_change is None or weight > lower_change)
            ),
            baseline,
        )
        stable_upper = next(
            (
                weight
                for weight, changed in reversed(upper)
                if not changed and (upper_change is None or weight < upper_change)
            ),
            baseline,
        )
        margins = [margin for _, _, margin in points if margin is not None]
        results.append(
            {
                "scope_type": scope_type,
                "scope_id": scope_id,
                "criterion_id": criterion_id,
                "baseline_weight": baseline,
                "sampled_lower_stability_bound": stable_lower,
                "sampled_upper_stability_bound": stable_upper,
                "first_observed_lower_top_set_change": lower_change,
                "first_observed_upper_top_set_change": upper_change,
                "minimum_first_second_score_margin": min(margins) if margins else None,
            }
        )
    return results


def _safe_error(error: Exception) -> str:
    if isinstance(
        error,
        (
            RunSelectedAnalysesError,
            RankingContractViolation,
            ValueError,
            ArithmeticError,
        ),
    ):
        return str(error)
    return "The selected analysis could not be completed."


def _package_version(name: str) -> str:
    try:
        return version(name.casefold().replace(" ", ""))
    except PackageNotFoundError:
        return "unavailable"
