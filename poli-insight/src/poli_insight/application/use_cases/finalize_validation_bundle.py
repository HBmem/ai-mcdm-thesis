"""Finalize a reviewed validation run into an immutable weighting bundle."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.ports.validator import (
    PreparedComparisonMatrix,
    WeightingAlgorithmRunner,
)
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    ArtifactType,
    AuditAction,
    MissingGroupPolicy,
    RunInclusionStatus,
    SessionStatus,
    SubmissionReviewStatus,
)
from poli_insight.domain.processing import (
    ProcessingMatrix,
    ProcessingRunSubmission,
    RunArtifact,
)
from poli_insight.domain.validation import ValidationPreparedMatrix


class FinalizeValidationBundleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FinalizeValidationBundleCommand:
    processing_run_id: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True)
class FinalizeValidationBundleResult:
    processing_run_id: str
    run_number: int
    output_hash: str
    included_submissions: int
    excluded_submissions: int
    group_count: int
    warning_count: int
    artifact_id: str


class FinalizeValidationBundle:
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

    def execute(
        self, command: FinalizeValidationBundleCommand
    ) -> FinalizeValidationBundleResult:
        with self._unit_of_work_factory() as unit_of_work:
            run = unit_of_work.processing_runs.get_for_update(
                command.processing_run_id
            )
            if run is None:
                raise FinalizeValidationBundleError("Validation bundle was not found.")
            session = unit_of_work.session.get(run.session_id)
            if session is None or session.status != SessionStatus.CLOSED:
                raise FinalizeValidationBundleError(
                    "A validation bundle can be finalized only after the session closes."
                )
            configuration = next(
                (
                    item
                    for item in session.configurations
                    if item.configuration_version_id
                    == run.configuration_version_id
                ),
                None,
            )
            if configuration is None:
                raise FinalizeValidationBundleError(
                    "The run's frozen configuration is unavailable."
                )
            runner = self._runner_registry.get(run.algorithm_implementation_id)
            current_submissions = unit_of_work.submissions.list_effective_for_configuration(
                configuration.configuration_version_id
            )
            participants = {
                item.participant_id: item
                for item in unit_of_work.participants.get_many(
                    tuple(item.participant_id for item in current_submissions)
                )
            }
            current_roster_hash = hash_json(
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
                    for item in current_submissions
                ]
            )
            if current_roster_hash != run.roster_hash:
                raise FinalizeValidationBundleError(
                    "The current submission roster differs from this validation run. "
                    "Run validation again explicitly."
                )

            resolved_items: list[ProcessingRunSubmission] = []
            validations = {}
            for item in run.submissions:
                validation = (
                    unit_of_work.validations.get(item.validation_id)
                    if item.validation_id is not None
                    else None
                )
                if validation is not None:
                    validations[validation.validation_id] = validation
                review = unit_of_work.submission_reviews.get_latest(
                    item.submission_id
                )
                inclusion = item.inclusion_status
                reason = item.exclusion_reason
                if inclusion == RunInclusionStatus.PENDING_REVIEW:
                    if (
                        review is None
                        or review.validation_id != item.validation_id
                        or review.status
                        not in {
                            SubmissionReviewStatus.ACCEPTED,
                            SubmissionReviewStatus.REJECTED,
                        }
                    ):
                        raise FinalizeValidationBundleError(
                            "Every warned validation requires an explicit include or "
                            "exclude decision tied to that validation."
                        )
                    if review.status == SubmissionReviewStatus.ACCEPTED:
                        inclusion = RunInclusionStatus.INCLUDED
                        reason = None
                    else:
                        inclusion = RunInclusionStatus.EXCLUDED_MODERATOR
                        reason = "moderator.rejected"
                elif (
                    inclusion == RunInclusionStatus.INCLUDED
                    and review is not None
                    and review.validation_id == item.validation_id
                    and review.status == SubmissionReviewStatus.REJECTED
                ):
                    inclusion = RunInclusionStatus.EXCLUDED_MODERATOR
                    reason = "moderator.rejected"
                if inclusion == RunInclusionStatus.INCLUDED and (
                    validation is None or not validation.is_usable_for_processing
                ):
                    raise FinalizeValidationBundleError(
                        "An included submission lacks usable validation evidence."
                    )
                resolved_items.append(
                    ProcessingRunSubmission(
                        processing_run_id=run.processing_run_id,
                        submission_id=item.submission_id,
                        participant_id=item.participant_id,
                        stakeholder_group_id=item.stakeholder_group_id,
                        validation_id=item.validation_id,
                        inclusion_status=inclusion,
                        exclusion_reason=reason,
                    )
                )

            included = tuple(
                item
                for item in resolved_items
                if item.inclusion_status == RunInclusionStatus.INCLUDED
            )
            if len(included) < configuration.minimum_valid_submissions:
                raise FinalizeValidationBundleError(
                    "The run does not meet the minimum valid submission requirement."
                )

            matrices, warnings = self._aggregate(
                run.processing_run_id,
                configuration,
                included,
                validations,
                run.parameter_json,
                runner,
            )
            bundle = self._bundle_manifest(
                run,
                configuration,
                resolved_items,
                matrices,
                warnings,
            )
            input_artifact = RunArtifact.create(
                run_artifact_id=self._id_factory(),
                processing_run_id=run.processing_run_id,
                artifact_type=ArtifactType.INPUT_MANIFEST,
                schema_version=1,
                content_json={
                    "schema_version": 1,
                    "input_hash": run.input_hash,
                    "roster_hash": run.roster_hash,
                    "algorithm_implementation_id": (
                        run.algorithm_implementation_id
                    ),
                    "parameters": dict(run.parameter_json),
                    "weight_derivation": "geometric",
                    "submissions": [
                        item.to_manifest() for item in resolved_items
                    ],
                },
            )
            artifact = RunArtifact.create(
                run_artifact_id=self._id_factory(),
                processing_run_id=run.processing_run_id,
                artifact_type=ArtifactType.ANALYSIS_BUNDLE,
                schema_version=1,
                content_json=bundle,
            )
            completed_at = self._clock()
            completed = run.complete(
                at=completed_at,
                submissions=tuple(resolved_items),
                matrices=matrices,
                artifacts=(input_artifact, artifact),
            )
            unit_of_work.processing_runs.save(completed)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=completed_at,
                    session_id=run.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.PROCESSED,
                    entity_type="processing_run",
                    entity_id=run.processing_run_id,
                    correlation_id=command.correlation_id,
                    use_case="finalize_validation_bundle",
                    before_json={"status": run.status.value},
                    after_json={
                        "status": completed.status.value,
                        "output_hash": completed.output_hash,
                        "included": len(included),
                        "excluded": len(resolved_items) - len(included),
                        "warning_count": len(warnings),
                    },
                )
            )
            unit_of_work.commit()

        assert completed.output_hash is not None
        return FinalizeValidationBundleResult(
            processing_run_id=completed.processing_run_id,
            run_number=completed.run_number,
            output_hash=completed.output_hash,
            included_submissions=len(included),
            excluded_submissions=len(resolved_items) - len(included),
            group_count=sum(item.level == "stakeholder_group" for item in matrices),
            warning_count=len(warnings),
            artifact_id=artifact.run_artifact_id,
        )

    def _aggregate(
        self,
        run_id,
        configuration,
        included,
        validations,
        parameters,
        runner: WeightingAlgorithmRunner,
    ) -> tuple[tuple[ProcessingMatrix, ...], tuple[dict[str, object], ...]]:
        participant_matrices: list[ProcessingMatrix] = []
        grouped_values: dict[str, list[tuple[tuple[Decimal, ...], ...]]] = defaultdict(list)
        criterion_ids: tuple[str, ...] | None = None
        warnings: list[dict[str, object]] = []
        for item in included:
            validation = validations[item.validation_id]
            prepared = validation.prepared_matrix
            if prepared is None:
                raise FinalizeValidationBundleError(
                    "A selected validation has no prepared comparison matrix."
                )
            values = _decimal_matrix(prepared.matrix_json)
            if criterion_ids is None:
                criterion_ids = prepared.criterion_ids
            elif criterion_ids != prepared.criterion_ids:
                raise FinalizeValidationBundleError(
                    "Selected validations use incompatible criterion ordering."
                )
            grouped_values[item.stakeholder_group_id].append(values)
            participant_matrices.append(
                ProcessingMatrix.create(
                    processing_matrix_id=self._id_factory(),
                    processing_run_id=run_id,
                    level="participant",
                    criterion_ids=prepared.criterion_ids,
                    matrix_json=prepared.matrix_json,
                    weights_json={
                        "values": [
                            {
                                "criterion_id": weight.criterion_id,
                                "weight": weight.crisp_weight,
                            }
                            for weight in validation.criterion_weights
                        ]
                    },
                    diagnostics_json={
                        "consistency_ratio": validation.consistency_ratio,
                        "messages": [
                            {"code": message.code, "severity": message.severity.value}
                            for message in validation.messages
                        ],
                    },
                    validation_id=validation.validation_id,
                )
            )
        if criterion_ids is None:
            raise FinalizeValidationBundleError("No included matrices are available.")

        required_keys = set(
            configuration.required_group_policy_json.get(
                "required_group_keys", []
            )
        )
        groups_by_id = {
            group.session_stakeholder_group_id: group
            for group in configuration.stakeholder_groups
            if group.is_active
        }
        missing_required = {
            group.group_key
            for group in groups_by_id.values()
            if group.group_key in required_keys
            and not grouped_values.get(group.session_stakeholder_group_id)
        }
        if (
            missing_required
            and configuration.missing_group_policy == MissingGroupPolicy.FAIL
        ):
            raise FinalizeValidationBundleError(
                "Required stakeholder groups have no included submissions: "
                + ", ".join(sorted(missing_required))
            )

        group_matrices: dict[str, tuple[tuple[Decimal, ...], ...]] = {}
        output_matrices = list(participant_matrices)
        for group_id, participant_values in grouped_values.items():
            values = _geometric_mean_matrices(participant_values)
            group_matrices[group_id] = values
            result = runner.execute(
                _prepared_for_aggregate(run_id, criterion_ids, values), parameters
            )
            diagnostics = _diagnostics(result, configuration.consistency_threshold)
            if diagnostics.get("threshold_exceeded"):
                warnings.append(
                    {"level": "stakeholder_group", "stakeholder_group_id": group_id, "code": "consistency.threshold_exceeded"}
                )
            output_matrices.append(
                ProcessingMatrix.create(
                    processing_matrix_id=self._id_factory(),
                    processing_run_id=run_id,
                    level="stakeholder_group",
                    stakeholder_group_id=group_id,
                    criterion_ids=criterion_ids,
                    matrix_json=_matrix_json(values),
                    weights_json=_weights_json(result),
                    diagnostics_json=diagnostics,
                )
            )

        allocations = {
            group_id: Decimal(group.allocation_units)
            / Decimal(configuration.allocation_total_units)
            for group_id, group in groups_by_id.items()
            if group_id in group_matrices
        }
        if configuration.missing_group_policy == MissingGroupPolicy.EXCLUDED_RENORMALIZED:
            total = sum(allocations.values(), Decimal(0))
            allocations = {key: value / total for key, value in allocations.items()}
        session_values = _weighted_geometric_matrices(group_matrices, allocations)
        session_result = runner.execute(
            _prepared_for_aggregate(run_id, criterion_ids, session_values), parameters
        )
        session_diagnostics = _diagnostics(
            session_result, configuration.consistency_threshold
        )
        if session_diagnostics.get("threshold_exceeded"):
            warnings.append(
                {"level": "session", "code": "consistency.threshold_exceeded"}
            )
        output_matrices.append(
            ProcessingMatrix.create(
                processing_matrix_id=self._id_factory(),
                processing_run_id=run_id,
                level="session",
                criterion_ids=criterion_ids,
                matrix_json=_matrix_json(session_values),
                weights_json=_weights_json(session_result),
                diagnostics_json=session_diagnostics,
            )
        )
        return tuple(output_matrices), tuple(warnings)

    @staticmethod
    def _bundle_manifest(
        run,
        configuration,
        submissions,
        matrices,
        warnings,
    ):
        session_matrix = next(
            matrix for matrix in matrices if matrix.level == "session"
        )
        group_matrices = {
            matrix.stakeholder_group_id: matrix
            for matrix in matrices
            if matrix.level == "stakeholder_group"
        }
        configured_powers = {
            group.session_stakeholder_group_id: (
                Decimal(group.allocation_units)
                / Decimal(configuration.allocation_total_units)
            )
            for group in configuration.stakeholder_groups
            if group.is_active
        }
        if configuration.missing_group_policy == MissingGroupPolicy.ZERO_CONTRIBUTION:
            effective_powers = dict(configured_powers)
        else:
            effective_powers = {
                group_id: power
                for group_id, power in configured_powers.items()
                if group_id in group_matrices
            }
        if (
            configuration.missing_group_policy
            == MissingGroupPolicy.EXCLUDED_RENORMALIZED
        ):
            effective_total = sum(effective_powers.values(), Decimal(0))
            effective_powers = {
                group_id: power / effective_total
                for group_id, power in effective_powers.items()
            }
        return {
            "schema_version": 1,
            "run": {
                "processing_run_id": run.processing_run_id,
                "run_number": run.run_number,
                "session_id": run.session_id,
                "configuration_version_id": run.configuration_version_id,
                "scenario_snapshot_id": run.scenario_snapshot_id,
                "input_hash": run.input_hash,
                "roster_hash": run.roster_hash,
                "environment": dict(run.environment_json),
            },
            "algorithm": {
                "implementation_id": run.algorithm_implementation_id,
                "parameters": dict(run.parameter_json),
                "weight_derivation": "geometric",
            },
            "ordered_criteria": list(session_matrix.criterion_ids),
            "submissions": [item.to_manifest() for item in submissions],
            "stakeholder_groups": [
                {
                    "stakeholder_group_id": group.session_stakeholder_group_id,
                    "group_key": group.group_key,
                    "configured_voting_power": configured_powers[
                        group.session_stakeholder_group_id
                    ],
                    "effective_voting_power": effective_powers.get(
                        group.session_stakeholder_group_id,
                        Decimal(0),
                    ),
                    "included_participant_count": sum(
                        item.inclusion_status
                        == RunInclusionStatus.INCLUDED
                        and item.stakeholder_group_id
                        == group.session_stakeholder_group_id
                        for item in submissions
                    ),
                    "matrix_hash": (
                        group_matrices[group.session_stakeholder_group_id].matrix_hash
                        if group.session_stakeholder_group_id in group_matrices
                        else None
                    ),
                }
                for group in configuration.stakeholder_groups
                if group.is_active
            ],
            "matrices": [item.to_manifest() for item in matrices],
            "warnings": list(warnings),
        }


def _decimal_matrix(matrix_json) -> tuple[tuple[Decimal, ...], ...]:
    return tuple(
        tuple(value if isinstance(value, Decimal) else Decimal(str(value)) for value in row)
        for row in matrix_json["values"]
    )


def _geometric_mean_matrices(matrices):
    size = len(matrices[0])
    result = [[Decimal(1) for _ in range(size)] for _ in range(size)]
    for left in range(size):
        for right in range(left + 1, size):
            logarithmic_mean = sum(
                (matrix[left][right].ln() for matrix in matrices),
                Decimal(0),
            ) / Decimal(len(matrices))
            value = logarithmic_mean.exp()
            result[left][right] = value
            result[right][left] = Decimal(1) / value
    return tuple(tuple(row) for row in result)


def _weighted_geometric_matrices(matrices, allocations):
    first = next(iter(matrices.values()))
    size = len(first)
    result = [[Decimal(1) for _ in range(size)] for _ in range(size)]
    for left in range(size):
        for right in range(left + 1, size):
            exponent = sum(
                (
                    matrices[group_id][left][right].ln() * weight
                    for group_id, weight in allocations.items()
                ),
                start=Decimal(0),
            )
            value = exponent.exp()
            result[left][right] = value
            result[right][left] = Decimal(1) / value
    return tuple(tuple(row) for row in result)


def _prepared_for_aggregate(run_id, criterion_ids, values):
    matrix = ValidationPreparedMatrix.create(
        validation_id=run_id,
        response_format="pairwise",
        value_shape="crisp",
        criterion_ids=criterion_ids,
        matrix_json=_matrix_json(values),
        preparer_version="stakeholder-geometric-aggregation-v1",
    )
    return PreparedComparisonMatrix(matrix=matrix, normalized_answers=())


def _matrix_json(values):
    return {
        "values": [
            [format(value.normalize(), "f") for value in row]
            for row in values
        ]
    }


def _weights_json(result):
    if result.fuzzy_weights:
        return {
            "shape": "triangular_fuzzy",
            "values": [
                {
                    "criterion_id": criterion_id,
                    "lower": weight[0],
                    "middle": weight[1],
                    "upper": weight[2],
                }
                for criterion_id, weight in zip(
                    result.criterion_ids,
                    result.fuzzy_weights,
                    strict=True,
                )
            ],
        }
    return {
        "shape": "crisp",
        "values": [
            {"criterion_id": criterion_id, "weight": weight}
            for criterion_id, weight in zip(
                result.criterion_ids, result.crisp_weights, strict=True
            )
        ]
    }


def _diagnostics(result, threshold):
    return {
        **dict(result.diagnostics_json),
        "consistency_ratio": result.consistency_ratio,
        "consistency_threshold": threshold,
        "threshold_exceeded": (
            threshold is not None
            and result.consistency_ratio is not None
            and result.consistency_ratio > threshold
        ),
    }
