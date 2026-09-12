"""Create immutable rankings from one successful deterministic weighting run."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from platform import python_version
from typing import Any

from poli_insight.application.ports.ranking import (
    RankingAlternativeInput,
    RankingAlternativeResult,
    RankingContractViolation,
    RankingExecutionError,
    RankingRequest,
    RankingWeightInput,
)
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.ranking_support import (
    ranked_alternatives,
    ranking_request_for_matrix,
    stored_decimal,
    weight_inputs,
)
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AlgorithmRole,
    ArtifactType,
    AuditAction,
    RunStatus,
    ScenarioSnapshotStatus,
    SessionStatus,
)
from poli_insight.domain.processing import ProcessingMatrix
from poli_insight.domain.ranking import (
    RankedAlternative,
    RankingArtifact,
    RankingResult,
    RankingRun,
)


class CreateRankingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CreateRankingCommand:
    session_id: str
    source_processing_run_id: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True)
class CreateRankingResult:
    ranking_run_id: str
    run_number: int
    status: RunStatus
    reused: bool
    result_count: int
    output_hash: str | None
    failure_code: str | None = None
    failure_detail: str | None = None


class CreateRanking:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        runner_registry,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._runner_registry = runner_registry
        self._clock = clock
        self._id_factory = id_factory

    def execute(self, command: CreateRankingCommand) -> CreateRankingResult:
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get(command.session_id)
            if session is None:
                raise CreateRankingError("The selected session was not found.")
            if session.status != SessionStatus.CLOSED:
                raise CreateRankingError(
                    "Rankings can be generated only for a closed session."
                )
            source = unit_of_work.processing_runs.get(command.source_processing_run_id)
            if (
                source is None
                or source.session_id != command.session_id
                or source.status != RunStatus.SUCCEEDED
            ):
                raise CreateRankingError(
                    "A successful weighting run from this session is required."
                )
            configuration = next(
                (
                    item
                    for item in session.configurations
                    if item.configuration_version_id == source.configuration_version_id
                ),
                None,
            )
            if configuration is None or (
                session.active_configuration_version_id
                != configuration.configuration_version_id
            ):
                raise CreateRankingError(
                    "The weighting run does not use the active frozen configuration."
                )
            if configuration.scenario_snapshot_id != source.scenario_snapshot_id:
                raise CreateRankingError(
                    "The weighting run and configuration use different scenarios."
                )
            scenario = unit_of_work.scenarios.get_by_id(source.scenario_snapshot_id)
            if scenario is None or scenario.status != ScenarioSnapshotStatus.READY:
                raise CreateRankingError("A ready scenario snapshot is required.")
            ranking_configs = tuple(
                item
                for item in configuration.algorithm_configs
                if item.role == AlgorithmRole.RANKING
            )
            ranking_config = (
                min(ranking_configs, key=lambda item: item.execution_order)
                if ranking_configs
                else None
            )
            if ranking_config is None:
                raise CreateRankingError(
                    "No ranking implementation is configured for this session."
                )
            implementations = unit_of_work.algorithms.get_many(
                (ranking_config.algorithm_implementation_id,)
            )
            if not implementations or not implementations[0].active:
                raise CreateRankingError(
                    "The configured ranking implementation is unavailable."
                )
            implementation = implementations[0]
            if implementation.role != AlgorithmRole.RANKING:
                raise CreateRankingError(
                    "The configured implementation is not registered for ranking."
                )
            try:
                runner = self._runner_registry.get(
                    ranking_config.algorithm_implementation_id
                )
            except RankingContractViolation as error:
                raise CreateRankingError(str(error)) from error
            if (
                runner.metadata.implementation_version
                != implementation.implementation_version
                or runner.metadata.adapter_version != implementation.adapter_version
                or runner.metadata.parameter_schema_version
                != ranking_config.parameter_schema_version
            ):
                raise CreateRankingError(
                    "The registered ranking adapter does not match the frozen implementation."
                )
            self._ensure_current_roster(unit_of_work, source, configuration)
            if not source.matrices:
                raise CreateRankingError(
                    "The weighting run contains no persisted matrices."
                )
            source_matrices = tuple(
                sorted(
                    source.matrices,
                    key=lambda item: item.processing_matrix_id,
                )
            )

            try:
                requests = tuple(
                    self._request_for_matrix(
                        matrix,
                        scenario,
                        ranking_config.parameter_json,
                    )
                    for matrix in source_matrices
                )
            except RankingContractViolation as error:
                raise CreateRankingError(str(error)) from error
            input_manifest = {
                "schema_version": 1,
                "session_id": command.session_id,
                "source_processing_run_id": source.processing_run_id,
                "source_output_hash": source.output_hash,
                "configuration_version_id": configuration.configuration_version_id,
                "configuration_hash": configuration.config_hash,
                "scenario_snapshot_id": scenario.scenario_snapshot_id,
                "scenario_input_hash": scenario.materialized_input_hash,
                "roster_hash": source.roster_hash,
                "algorithm": {
                    "implementation_id": implementation.algorithm_implementation_id,
                    "implementation_version": implementation.implementation_version,
                    "adapter_version": implementation.adapter_version,
                    "parameter_schema_version": ranking_config.parameter_schema_version,
                    "parameters": dict(ranking_config.parameter_json),
                },
                "requests": [self._request_manifest(item) for item in requests],
            }
            input_hash = hash_json(input_manifest)
            reused = unit_of_work.ranking_runs.find_success_by_input_hash(input_hash)
            if reused is not None:
                return self._result(reused, reused=True)

            ranking_run_id = self._id_factory()
            run_number = unit_of_work.ranking_runs.next_run_number(command.session_id)
            created_at = self._clock()
            environment = {
                "ranking_schema_version": 1,
                "application_version": _package_version("poli-insight"),
                "provider_version": _package_version(implementation.library_name),
                "python_version": python_version(),
            }
            input_artifact = RankingArtifact.create(
                ranking_artifact_id=self._id_factory(),
                ranking_run_id=ranking_run_id,
                artifact_type=ArtifactType.INPUT_MANIFEST,
                schema_version=1,
                content_json=input_manifest,
            )
            base: dict[str, Any] = {
                "ranking_run_id": ranking_run_id,
                "session_id": command.session_id,
                "source_processing_run_id": source.processing_run_id,
                "configuration_version_id": configuration.configuration_version_id,
                "scenario_snapshot_id": scenario.scenario_snapshot_id,
                "run_number": run_number,
                "roster_hash": source.roster_hash,
                "input_hash": input_hash,
                "algorithm_implementation_id": implementation.algorithm_implementation_id,
                "implementation_version": implementation.implementation_version,
                "adapter_version": implementation.adapter_version,
                "parameter_json": dict(ranking_config.parameter_json),
                "environment_json": environment,
                "created_at": created_at,
                "created_by": command.actor_id,
                "completed_at": created_at,
            }
            try:
                results: list[RankingResult] = []
                traces: list[dict[str, object]] = []
                for matrix, request in zip(source_matrices, requests, strict=True):
                    execution = runner.execute(request)
                    ranked = self._ranked_alternatives(
                        execution.alternatives,
                        request.alternatives,
                    )
                    results.append(
                        RankingResult.create(
                            ranking_result_id=self._id_factory(),
                            ranking_run_id=ranking_run_id,
                            source_processing_matrix_id=matrix.processing_matrix_id,
                            level=matrix.level,
                            stakeholder_group_id=matrix.stakeholder_group_id,
                            validation_id=(
                                matrix.validation_id
                                if matrix.level == "participant"
                                else None
                            ),
                            alternatives=ranked,
                            metric_label=execution.metric_label,
                            diagnostics_json={
                                **dict(execution.diagnostics_json),
                                "algorithm_metadata": dict(
                                    execution.algorithm_metadata_json
                                ),
                            },
                        )
                    )
                    traces.append(
                        {
                            "source_processing_matrix_id": matrix.processing_matrix_id,
                            "level": matrix.level,
                            "trace": dict(execution.trace_json),
                        }
                    )
                trace_artifact = RankingArtifact.create(
                    ranking_artifact_id=self._id_factory(),
                    ranking_run_id=ranking_run_id,
                    artifact_type=ArtifactType.RANKING_TRACE,
                    schema_version=1,
                    content_json={"schema_version": 1, "traces": traces},
                )
                structured_artifact = RankingArtifact.create(
                    ranking_artifact_id=self._id_factory(),
                    ranking_run_id=ranking_run_id,
                    artifact_type=ArtifactType.STRUCTURED_RESULT,
                    schema_version=1,
                    content_json={
                        "schema_version": 1,
                        "algorithm_implementation_id": implementation.algorithm_implementation_id,
                        "results": [item.to_manifest() for item in results],
                    },
                )
                run = RankingRun.succeeded(
                    **base,
                    results=tuple(results),
                    artifacts=(input_artifact, trace_artifact, structured_artifact),
                )
            except (RankingContractViolation, RankingExecutionError) as error:
                code = (
                    error.code
                    if isinstance(error, RankingExecutionError)
                    else "ranking.input_or_result_invalid"
                )
                detail = (
                    error.safe_detail
                    if isinstance(error, RankingExecutionError)
                    else str(error)
                )
                run = RankingRun.failed(
                    **base,
                    results=(),
                    artifacts=(input_artifact,),
                    failure_code=code,
                    failure_detail=detail,
                )
            unit_of_work.ranking_runs.add(run)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=created_at,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.PROCESSED,
                    entity_type="ranking_run",
                    entity_id=ranking_run_id,
                    correlation_id=command.correlation_id,
                    use_case="create_ranking",
                    before_json=None,
                    after_json={
                        "status": run.status.value,
                        "source_processing_run_id": source.processing_run_id,
                        "input_hash": input_hash,
                        "output_hash": run.output_hash,
                        "result_count": len(run.results),
                        "failure_code": run.failure_code,
                    },
                )
            )
            unit_of_work.commit()
            return self._result(run, reused=False)

    @staticmethod
    def _ensure_current_roster(unit_of_work, source, configuration) -> None:
        submissions = unit_of_work.submissions.list_effective_for_configuration(
            configuration.configuration_version_id
        )
        participants = {
            item.participant_id: item
            for item in unit_of_work.participants.get_many(
                tuple(item.participant_id for item in submissions)
            )
        }
        current_hash = hash_json(
            [
                {
                    "submission_id": item.submission_id,
                    "participant_id": item.participant_id,
                    "stakeholder_group_id": item.session_stakeholder_group_id,
                    "answers_hash": item.answers_hash,
                    "participant_access_status": (
                        participants[item.participant_id].access_status.value
                        if item.participant_id in participants
                        else "missing"
                    ),
                }
                for item in submissions
            ]
        )
        if current_hash != source.roster_hash:
            raise CreateRankingError(
                "The current frozen roster differs from the selected weighting run."
            )

    @staticmethod
    def _request_for_matrix(
        matrix: ProcessingMatrix, scenario, parameters
    ) -> RankingRequest:
        return ranking_request_for_matrix(matrix, scenario, parameters)

    @staticmethod
    def _request_manifest(request: RankingRequest) -> dict[str, object]:
        return {
            "source_processing_matrix_id": request.source_processing_matrix_id,
            "alternatives": [
                {
                    "alternative_id": item.alternative_id,
                    "alternative_key": item.alternative_key,
                    "display_order": item.display_order,
                }
                for item in request.alternatives
            ],
            "criteria": [
                {
                    "criterion_id": item.criterion_id,
                    "criterion_key": item.criterion_key,
                    "direction": item.direction.value,
                    "data_type": item.data_type.value,
                    "display_order": item.display_order,
                }
                for item in request.criteria
            ],
            "cells": [
                {
                    "alternative_id": item.alternative_id,
                    "criterion_id": item.criterion_id,
                    "numeric_value": item.numeric_value,
                    "structured_value": (
                        None
                        if item.structured_value is None
                        else dict(item.structured_value)
                    ),
                }
                for item in request.cells
            ],
            "weights": [
                {
                    "criterion_id": item.criterion_id,
                    "value": (
                        dict(item.value)
                        if isinstance(item.value, Mapping)
                        else item.value
                    ),
                }
                for item in request.weights
            ],
            "parameters": dict(request.parameters),
        }

    @staticmethod
    def _ranked_alternatives(
        values: tuple[RankingAlternativeResult, ...],
        alternatives: tuple[RankingAlternativeInput, ...],
    ) -> tuple[RankedAlternative, ...]:
        return ranked_alternatives(values, alternatives)

    @staticmethod
    def _result(run: RankingRun, *, reused: bool) -> CreateRankingResult:
        return CreateRankingResult(
            ranking_run_id=run.ranking_run_id,
            run_number=run.run_number,
            status=run.status,
            reused=reused,
            result_count=len(run.results),
            output_hash=run.output_hash,
            failure_code=run.failure_code,
            failure_detail=run.failure_detail,
        )


def _weight_inputs(matrix: ProcessingMatrix) -> tuple[RankingWeightInput, ...]:
    return weight_inputs(matrix)


def _stored_decimal(value: Decimal) -> Decimal:
    return stored_decimal(value)


def _package_version(name: str) -> str:
    normalized = name.casefold().replace(" ", "")
    try:
        return version(normalized)
    except PackageNotFoundError:
        return "unavailable"
