"""Explicit administrator-triggered validation of a session roster."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version
from platform import python_version

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.application.use_cases.validate_submission import (
    ValidateSubmission,
    ValidateSubmissionCommand,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AlgorithmRole,
    AuditAction,
    ParticipantAccessStatus,
    RunInclusionStatus,
    ValidationStatus,
)
from poli_insight.domain.processing import ProcessingRun, ProcessingRunSubmission


class ValidateCurrentSubmissionsError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ValidateCurrentSubmissionsCommand:
    session_id: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True)
class ValidateCurrentSubmissionsResult:
    processing_run_id: str
    run_number: int
    roster_hash: str
    total: int
    valid: int
    warned: int
    invalid: int
    error: int
    excluded_disabled: int
    reused: int
    executed: int


class ValidateCurrentSubmissions:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        validate_submission: ValidateSubmission,
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._validate_submission = validate_submission
        self._clock = clock
        self._id_factory = id_factory

    def execute(
        self, command: ValidateCurrentSubmissionsCommand
    ) -> ValidateCurrentSubmissionsResult:
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get(command.session_id)
            if session is None or session.active_configuration is None:
                raise ValidateCurrentSubmissionsError(
                    "The session or its active configuration was not found."
                )
            configuration = session.active_configuration
            weighting = next(
                (
                    item
                    for item in configuration.algorithm_configs
                    if item.role == AlgorithmRole.WEIGHTING
                ),
                None,
            )
            if weighting is None:
                raise ValidateCurrentSubmissionsError(
                    "The active configuration has no weighting algorithm."
                )
            submissions = unit_of_work.submissions.list_effective_for_configuration(
                configuration.configuration_version_id
            )
            participants = {
                item.participant_id: item
                for item in unit_of_work.participants.get_many(
                    tuple(item.participant_id for item in submissions)
                )
            }

        validation_results = {}
        reused = 0
        executed = 0
        for submission in submissions:
            participant = participants.get(submission.participant_id)
            if (
                participant is None
                or participant.access_status != ParticipantAccessStatus.ACTIVE
            ):
                continue
            result = self._validate_submission.execute(
                ValidateSubmissionCommand(
                    submission_id=submission.submission_id,
                    session_algorithm_config_id=(
                        weighting.session_algorithm_config_id
                    ),
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    correlation_id=command.correlation_id,
                )
            )
            validation_results[submission.submission_id] = result
            reused += int(result.reused)
            executed += int(not result.reused)

        run_id = self._id_factory()
        roster_manifest = [
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
        roster_hash = hash_json(roster_manifest)
        selections: list[ProcessingRunSubmission] = []
        counts: Counter[str] = Counter()
        for submission in submissions:
            participant = participants.get(submission.participant_id)
            selected_result = validation_results.get(submission.submission_id)
            if (
                participant is None
                or participant.access_status != ParticipantAccessStatus.ACTIVE
            ):
                inclusion = RunInclusionStatus.EXCLUDED_DISABLED
                reason = "participant.disabled"
                validation_id = None
                counts["excluded_disabled"] += 1
            elif selected_result is None:
                raise AssertionError("Active submission validation is missing.")
            elif selected_result.status == ValidationStatus.VALID:
                inclusion = RunInclusionStatus.INCLUDED
                reason = None
                validation_id = selected_result.validation_id
                counts["valid"] += 1
            elif selected_result.status == ValidationStatus.VALID_WITH_WARNING:
                inclusion = RunInclusionStatus.PENDING_REVIEW
                reason = None
                validation_id = selected_result.validation_id
                counts["warned"] += 1
            elif selected_result.status == ValidationStatus.INVALID:
                inclusion = RunInclusionStatus.EXCLUDED_INVALID
                reason = "validation.invalid"
                validation_id = selected_result.validation_id
                counts["invalid"] += 1
            else:
                inclusion = RunInclusionStatus.EXCLUDED_ERROR
                reason = "validation.error"
                validation_id = selected_result.validation_id
                counts["error"] += 1
            selections.append(
                ProcessingRunSubmission(
                    processing_run_id=run_id,
                    submission_id=submission.submission_id,
                    participant_id=submission.participant_id,
                    stakeholder_group_id=submission.session_stakeholder_group_id,
                    validation_id=validation_id,
                    inclusion_status=inclusion,
                    exclusion_reason=reason,
                )
            )

        with self._unit_of_work_factory() as unit_of_work:
            run_number = unit_of_work.processing_runs.next_run_number(
                command.session_id
            )
            validation_evidence = tuple(
                validation
                for result in validation_results.values()
                if (
                    validation := unit_of_work.validations.get(
                        result.validation_id
                    )
                )
                is not None
            )
            created_at = self._clock()
            run = ProcessingRun.awaiting_review(
                processing_run_id=run_id,
                session_id=command.session_id,
                configuration_version_id=configuration.configuration_version_id,
                scenario_snapshot_id=configuration.scenario_snapshot_id,
                run_number=run_number,
                roster_hash=roster_hash,
                algorithm_implementation_id=weighting.algorithm_implementation_id,
                parameter_json=weighting.parameter_json,
                environment_json={
                    "bundle_schema_version": 1,
                    "matrix_schema_version": 1,
                    "validation_mode": "explicit_admin",
                    "application_version": _package_version("poli-insight"),
                    "provider_version": _package_version("pydecision"),
                    "python_version": python_version(),
                    "validator_versions": sorted(
                        {
                            item.validator_version
                            for item in validation_evidence
                        }
                    ),
                    "algorithm_versions": sorted(
                        {
                            str(item.quality_metrics_json["algorithm_version"])
                            for item in validation_evidence
                            if "algorithm_version"
                            in item.quality_metrics_json
                        }
                    ),
                    "adapter_versions": sorted(
                        {
                            str(item.quality_metrics_json["adapter_version"])
                            for item in validation_evidence
                            if "adapter_version" in item.quality_metrics_json
                        }
                    ),
                    "preparer_versions": sorted(
                        {
                            item.prepared_matrix.preparer_version
                            for item in validation_evidence
                            if item.prepared_matrix is not None
                        }
                    ),
                },
                created_at=created_at,
                created_by=command.actor_id,
                submissions=tuple(selections),
            )
            unit_of_work.processing_runs.add(run)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=created_at,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.VALIDATED,
                    entity_type="processing_run",
                    entity_id=run_id,
                    correlation_id=command.correlation_id,
                    use_case="validate_current_submissions",
                    after_json={
                        "run_number": run_number,
                        "status": run.status.value,
                        "roster_hash": roster_hash,
                        "total": len(submissions),
                        "valid": counts["valid"],
                        "warned": counts["warned"],
                        "invalid": counts["invalid"],
                        "error": counts["error"],
                    },
                )
            )
            unit_of_work.commit()

        return ValidateCurrentSubmissionsResult(
            processing_run_id=run_id,
            run_number=run_number,
            roster_hash=roster_hash,
            total=len(submissions),
            valid=counts["valid"],
            warned=counts["warned"],
            invalid=counts["invalid"],
            error=counts["error"],
            excluded_disabled=counts["excluded_disabled"],
            reused=reused,
            executed=executed,
        )


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"
