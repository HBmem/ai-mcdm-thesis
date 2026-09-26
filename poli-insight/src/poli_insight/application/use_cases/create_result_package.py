"""Build immutable anonymous and identity-linked result packages."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from importlib.metadata import PackageNotFoundError, version
from platform import python_version
from typing import Any

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.analysis import AnalysisCase, AnalysisRun
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AnalysisMethod,
    ArtifactType,
    AuditAction,
    BundleVariant,
    MissingGroupPolicy,
    PackageArtifactType,
    RunInclusionStatus,
    RunStatus,
    SessionStatus,
)
from poli_insight.domain.result_package import (
    ResultPackageArtifact,
    ResultPackageRun,
    ResultPackageSubject,
)

_PACKAGE_SCHEMA_VERSION = 1
_AGGREGATE_PROJECTION_VERSION = 4
_COMMON_SECTION_SCHEMA_VERSIONS = {"06_analyses": 2}
_SMALL_GROUP_THRESHOLD = 3


class CreateResultPackageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CreateResultPackageCommand:
    session_id: str
    source_ranking_run_id: str
    source_analysis_run_ids: tuple[str, ...]
    variants: tuple[BundleVariant, ...]
    actor_id: str
    small_group_acknowledged: bool = False
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))

    def __post_init__(self) -> None:
        for value, label in (
            (self.session_id, "Session ID"),
            (self.source_ranking_run_id, "Ranking run ID"),
            (self.actor_id, "Actor ID"),
            (self.correlation_id, "Correlation ID"),
        ):
            if not value.strip():
                raise CreateResultPackageError(f"{label} cannot be empty.")
        if not self.source_analysis_run_ids:
            raise CreateResultPackageError(
                "Select at least one successful analysis run."
            )
        if len(set(self.source_analysis_run_ids)) != len(self.source_analysis_run_ids):
            raise CreateResultPackageError("Analysis run selections must be unique.")
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise CreateResultPackageError(
                "Select one or more unique package versions."
            )
        variant_order = {
            BundleVariant.ANONYMOUS: 0,
            BundleVariant.PUBLIC: 1,
        }
        object.__setattr__(
            self,
            "variants",
            tuple(sorted(self.variants, key=variant_order.__getitem__)),
        )


@dataclass(frozen=True, slots=True)
class PackageProgress:
    phase: str
    completed_steps: int
    total_steps: int
    message: str


@dataclass(frozen=True, slots=True)
class CreateResultPackageResult:
    package_run_id: str
    run_number: int
    variants: tuple[BundleVariant, ...]
    output_hash: str
    reused: bool
    warning_count: int


class CreateResultPackage:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = lambda: str(new_id()),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock
        self._id_factory = id_factory

    def execute(
        self,
        command: CreateResultPackageCommand,
        *,
        on_progress: Callable[[PackageProgress], None] | None = None,
    ) -> CreateResultPackageResult:
        self._progress(on_progress, "validating", 0, "Validating frozen lineage")
        with self._unit_of_work_factory() as unit_of_work:
            context = self._load_context(unit_of_work, command)
            input_manifest = self._input_manifest(command, context)
            input_hash = hash_json(input_manifest)
            reused = unit_of_work.result_packages.find_success_by_input_hash(input_hash)
            if reused is not None:
                self._progress(on_progress, "persisting", 7, "Reused existing package")
                return _result(reused, reused=True)

            package_run_id = self._id_factory()
            run_number = unit_of_work.result_packages.next_run_number(
                command.session_id
            )
            now = self._clock()
            base: dict[str, Any] = {
                "package_run_id": package_run_id,
                "session_id": command.session_id,
                "source_processing_run_id": context["processing"].processing_run_id,
                "source_ranking_run_id": context["ranking"].ranking_run_id,
                "source_analysis_run_ids": tuple(
                    item.analysis_run_id for item in context["analyses"]
                ),
                "variants": command.variants,
                "run_number": run_number,
                "source_roster_hash": context["processing"].roster_hash,
                "source_processing_output_hash": context["processing"].output_hash,
                "source_ranking_output_hash": context["ranking"].output_hash,
                "input_hash": input_hash,
                "environment_json": {
                    "package_schema_version": _PACKAGE_SCHEMA_VERSION,
                    "application_version": _package_version("poli-insight"),
                    "python_version": python_version(),
                    "renderer_version": "deterministic-report-v1",
                    "aggregate_projection_version": _AGGREGATE_PROJECTION_VERSION,
                },
                "created_at": now,
                "created_by": command.actor_id,
                "completed_at": now,
                "correlation_id": command.correlation_id,
            }
            try:
                self._progress(
                    on_progress, "loading_lineage", 1, "Loading source evidence"
                )
                common_sections, warnings = self._common_sections(context)
                self._progress(
                    on_progress,
                    "assembling_common_sections",
                    2,
                    "Assembling aggregate sections",
                )
                artifacts = [
                    ResultPackageArtifact.create(
                        package_artifact_id=self._id_factory(),
                        package_run_id=package_run_id,
                        artifact_type=PackageArtifactType.INPUT_MANIFEST,
                        name="input_manifest",
                        sequence=1,
                        schema_version=1,
                        content_json=input_manifest,
                    )
                ]
                for sequence, (name, content) in enumerate(
                    common_sections.items(), start=2
                ):
                    artifacts.append(
                        ResultPackageArtifact.create(
                            package_artifact_id=self._id_factory(),
                            package_run_id=package_run_id,
                            artifact_type=PackageArtifactType.COMMON_SECTION,
                            name=name,
                            sequence=sequence,
                            schema_version=_COMMON_SECTION_SCHEMA_VERSIONS.get(name, 1),
                            content_json=content,
                        )
                    )
                self._progress(
                    on_progress, "applying_privacy_rules", 3, "Applying privacy rules"
                )
                subjects = (
                    self._subjects(package_run_id, context)
                    if BundleVariant.PUBLIC in command.variants
                    else ()
                )
                shared = [
                    {
                        "name": item.name,
                        "content_hash": item.content_hash,
                        "sequence": item.sequence,
                        "schema_version": item.schema_version,
                    }
                    for item in artifacts
                    if item.artifact_type == PackageArtifactType.COMMON_SECTION
                ]
                self._progress(
                    on_progress, "building_variants", 4, "Building bundle versions"
                )
                for variant in command.variants:
                    manifest: dict[str, object] = {
                        "schema_version": 1,
                        "aggregate_projection_version": _AGGREGATE_PROJECTION_VERSION,
                        "variant": variant.value,
                        "privacy_label": (
                            "anonymous with de-identified influence cases"
                            if variant == BundleVariant.ANONYMOUS
                            else "identity-linked controlled access"
                        ),
                        "package_run_id": package_run_id,
                        "sections": shared,
                        "completeness": common_sections["06_analyses"]["completeness"],
                        "warnings": list(warnings),
                        "small_group_warning_acknowledged": input_manifest[
                            "small_group_warning_acknowledged"
                        ],
                        "warning_codes": list(warnings),
                        "participant_identity_mapping_included": (
                            variant == BundleVariant.PUBLIC
                        ),
                        "participant_subject_count": (
                            len(subjects) if variant == BundleVariant.PUBLIC else 0
                        ),
                        "redactions": (
                            [
                                "participant identifiers and aliases",
                                "submission and validation identifiers",
                                "participant matrices and rankings",
                                "participant identifiers in individual influence cases",
                                "stored identity and access credentials",
                            ]
                            if variant == BundleVariant.ANONYMOUS
                            else [
                                "stored names, email addresses, and additional identity",
                                "invitation and access credentials",
                                "source submission and validation identifiers",
                            ]
                        ),
                    }
                    if variant == BundleVariant.PUBLIC:
                        manifest["subject_hashes"] = [
                            item.content_hash for item in subjects
                        ]
                    artifacts.append(
                        ResultPackageArtifact.create(
                            package_artifact_id=self._id_factory(),
                            package_run_id=package_run_id,
                            artifact_type=PackageArtifactType.VARIANT_MANIFEST,
                            name=f"{variant.value}_manifest",
                            sequence=len(artifacts) + 1,
                            schema_version=1,
                            variant=variant,
                            content_json=manifest,
                        )
                    )
                self._progress(on_progress, "verifying", 5, "Verifying package hashes")
                run = ResultPackageRun.succeeded(
                    **base,
                    artifacts=tuple(artifacts),
                    subjects=tuple(subjects),
                )
            except Exception as error:  # noqa: BLE001 - retain safe terminal evidence
                run = ResultPackageRun.failed(
                    **base,
                    failure_code="result_package.build_failed",
                    failure_detail=_safe_error(error),
                )
            self._progress(on_progress, "persisting", 6, "Persisting immutable package")
            unit_of_work.result_packages.add(run)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=run.completed_at,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.PACKAGED,
                    entity_type="result_package_run",
                    entity_id=package_run_id,
                    correlation_id=command.correlation_id,
                    use_case="create_result_package",
                    after_json={
                        "status": run.status.value,
                        "variants": [item.value for item in command.variants],
                        "input_hash": input_hash,
                        "output_hash": run.output_hash,
                        "analysis_count": len(command.source_analysis_run_ids),
                    },
                )
            )
            unit_of_work.commit()
        self._progress(on_progress, "persisting", 7, "Package complete")
        if run.status == RunStatus.FAILED:
            raise CreateResultPackageError(
                run.failure_detail or "Package creation failed."
            )
        return _result(run, reused=False)

    def _load_context(self, unit_of_work: UnitOfWork, command):
        session = unit_of_work.session.get(command.session_id)
        if session is None:
            raise CreateResultPackageError("The selected session was not found.")
        if session.status == SessionStatus.ARCHIVED:
            raise CreateResultPackageError("Archived sessions are inspection-only.")
        if session.status != SessionStatus.CLOSED:
            raise CreateResultPackageError(
                "Results can be packaged only after closing the session."
            )
        if (
            session.identity_policy.casefold() == "anonymous"
            and BundleVariant.PUBLIC in command.variants
        ):
            raise CreateResultPackageError(
                "Anonymous sessions cannot create identity-linked public bundles."
            )
        ranking = unit_of_work.ranking_runs.get(command.source_ranking_run_id)
        if ranking is None or ranking.status != RunStatus.SUCCEEDED:
            raise CreateResultPackageError("Select a successful ranking run.")
        if ranking.session_id != command.session_id:
            raise CreateResultPackageError(
                "The ranking run belongs to another session."
            )
        processing = unit_of_work.processing_runs.get(ranking.source_processing_run_id)
        if processing is None or processing.status != RunStatus.SUCCEEDED:
            raise CreateResultPackageError(
                "The ranking source processing run is unavailable."
            )
        if (
            ranking.configuration_version_id != processing.configuration_version_id
            or ranking.scenario_snapshot_id != processing.scenario_snapshot_id
            or ranking.roster_hash != processing.roster_hash
        ):
            raise CreateResultPackageError(
                "The ranking and processing lineage evidence is inconsistent."
            )
        analyses = tuple(
            unit_of_work.analysis_runs.get(run_id)
            for run_id in command.source_analysis_run_ids
        )
        if any(item is None for item in analyses):
            raise CreateResultPackageError("A selected analysis run was not found.")
        typed_analyses = tuple(
            sorted(
                (item for item in analyses if item is not None),
                key=lambda item: item.method.value,
            )
        )
        if any(
            item.status != RunStatus.SUCCEEDED
            or item.session_id != command.session_id
            or item.source_ranking_run_id != ranking.ranking_run_id
            or item.source_processing_run_id != processing.processing_run_id
            or item.source_processing_output_hash != processing.output_hash
            or item.source_ranking_output_hash != ranking.output_hash
            for item in typed_analyses
        ):
            raise CreateResultPackageError(
                "Every analysis must be successful and share the selected ranking lineage."
            )
        methods = [item.method for item in typed_analyses]
        if len(set(methods)) != len(methods):
            raise CreateResultPackageError(
                "Select at most one run for each analysis method."
            )
        configuration = next(
            (
                item
                for item in session.configurations
                if item.configuration_version_id == processing.configuration_version_id
            ),
            None,
        )
        scenario = unit_of_work.scenarios.get_by_id(processing.scenario_snapshot_id)
        if configuration is None or scenario is None:
            raise CreateResultPackageError(
                "Frozen scenario or configuration is unavailable."
            )
        group_counts = Counter(
            item.stakeholder_group_id
            for item in processing.submissions
            if item.inclusion_status == RunInclusionStatus.INCLUDED
        )
        small_groups = tuple(
            group.session_stakeholder_group_id
            for group in configuration.stakeholder_groups
            if group.is_active
            and 0
            < group_counts[group.session_stakeholder_group_id]
            < _SMALL_GROUP_THRESHOLD
        )
        if (
            BundleVariant.ANONYMOUS in command.variants
            and small_groups
            and not command.small_group_acknowledged
        ):
            raise CreateResultPackageError(
                "Acknowledge the re-identification warning for small stakeholder groups."
            )
        current_submissions = unit_of_work.submissions.list_effective_for_configuration(
            configuration.configuration_version_id
        )
        current_participants = {
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
                        current_participants[item.participant_id].access_status.value
                        if item.participant_id in current_participants
                        else "missing"
                    ),
                }
                for item in current_submissions
            ]
        )
        return {
            "session": session,
            "configuration": configuration,
            "scenario": scenario,
            "processing": processing,
            "ranking": ranking,
            "analyses": typed_analyses,
            "all_analyses": unit_of_work.analysis_runs.list_for_ranking(
                ranking.ranking_run_id
            ),
            "participants": {
                item.participant_id: item
                for item in unit_of_work.participants.get_many(
                    tuple(item.participant_id for item in processing.submissions)
                )
            },
            "small_groups": small_groups,
            "current_roster_hash": current_roster_hash,
            "stale_at_creation": (
                session.active_configuration_version_id
                != processing.configuration_version_id
                or current_roster_hash != processing.roster_hash
            ),
        }

    @staticmethod
    def _input_manifest(command, context) -> dict[str, object]:
        return {
            "schema_version": 1,
            "aggregate_projection_version": _AGGREGATE_PROJECTION_VERSION,
            "session_id": command.session_id,
            "processing": {
                "id": context["processing"].processing_run_id,
                "output_hash": context["processing"].output_hash,
            },
            "ranking": {
                "id": context["ranking"].ranking_run_id,
                "output_hash": context["ranking"].output_hash,
            },
            "analyses": [
                {
                    "id": item.analysis_run_id,
                    "method": item.method.value,
                    "output_hash": item.output_hash,
                }
                for item in sorted(
                    context["analyses"], key=lambda value: value.method.value
                )
            ],
            "variants": sorted(item.value for item in command.variants),
            "small_group_warning_acknowledged": bool(
                BundleVariant.ANONYMOUS in command.variants
                and context["small_groups"]
                and command.small_group_acknowledged
            ),
        }

    def _common_sections(self, context):
        session = context["session"]
        configuration = context["configuration"]
        scenario = context["scenario"]
        processing = context["processing"]
        ranking = context["ranking"]
        analyses = context["analyses"]
        group_names = {
            item.session_stakeholder_group_id: item.name
            for item in configuration.stakeholder_groups
        }
        inclusion_counts = Counter(
            item.inclusion_status.value for item in processing.submissions
        )
        exclusion_counts = Counter(
            item.exclusion_reason
            for item in processing.submissions
            if item.exclusion_reason
        )
        group_counts = Counter(
            item.stakeholder_group_id
            for item in processing.submissions
            if item.inclusion_status == RunInclusionStatus.INCLUDED
        )
        warnings = (
            ["privacy.small_stakeholder_group"] if context["small_groups"] else []
        )
        effective_group_powers = _effective_group_powers(
            configuration,
            {
                matrix.stakeholder_group_id: matrix
                for matrix in processing.matrices
                if matrix.level == "stakeholder_group"
            },
        )
        all_by_method: dict[AnalysisMethod, list[AnalysisRun]] = {}
        for item in context["all_analyses"]:
            all_by_method.setdefault(item.method, []).append(item)
        selected_by_method = {item.method: item for item in analyses}
        analysis_completeness = []
        analysis_results = []
        for method in AnalysisMethod:
            selected = selected_by_method.get(method)
            history = all_by_method.get(method, [])
            if selected is not None:
                state = "selected"
                safe_artifact = next(
                    (
                        artifact
                        for artifact in selected.artifacts
                        if artifact.artifact_type == ArtifactType.ANALYSIS_BUNDLE
                    ),
                    None,
                )
                structured = next(
                    (
                        artifact
                        for artifact in selected.artifacts
                        if artifact.artifact_type == ArtifactType.STRUCTURED_RESULT
                    ),
                    None,
                )
                case_status_counts = Counter(
                    item.status.value for item in selected.cases
                )
                case_warning_counts = Counter(
                    warning
                    for item in selected.cases
                    for warning in item.warnings
                )
                ordered_cases = tuple(
                    sorted(selected.cases, key=lambda item: item.sequence)
                )

                result: dict[str, object] = {
                    "method": method.value,
                    "analysis_type": selected.analysis_type.value,
                    "analysis_run_id": selected.analysis_run_id,
                    "input_hash": selected.input_hash,
                    "output_hash": selected.output_hash,
                    "parameters": dict(selected.parameter_json),
                    "case_count": len(selected.cases),
                    "case_status_counts": dict(sorted(case_status_counts.items())),
                    "warning_counts": dict(sorted(case_warning_counts.items())),
                    "summary": (
                        dict(safe_artifact.content_json)
                        if safe_artifact is not None
                        else {}
                    ),
                    "summary_artifact_hash": (
                        None if safe_artifact is None else safe_artifact.content_hash
                    ),
                    "structured_result_hash": (
                        None if structured is None else structured.content_hash
                    ),
                }
                if method == AnalysisMethod.PARTICIPANT_INFLUENCE:
                    result["cases"] = [
                        _participant_influence_case_manifest(item)
                        for item in ordered_cases
                    ]
                else:
                    result["cases"] = [
                        item.to_manifest()
                        for item in ordered_cases
                        if item.scope_type != "participant"
                    ]
                analysis_results.append(result)
            elif any(item.status == RunStatus.SUCCEEDED for item in history):
                state = "not_selected"
            elif history:
                state = "failed"
            else:
                state = "not_run"
            analysis_completeness.append({"method": method.value, "state": state})
        sections = {
            "01_context": {
                "schema_version": 1,
                "session": {
                    "session_id": session.session_id,
                    "title": session.title,
                    "description": session.description,
                    "identity_policy": session.identity_policy,
                    "status": session.status.value,
                    "lineage_state_at_packaging": (
                        "stale" if context["stale_at_creation"] else "current"
                    ),
                },
                "scenario": {
                    "scenario_snapshot_id": scenario.scenario_snapshot_id,
                    "title": scenario.title,
                    "domain": scenario.domain,
                    "summary": scenario.summary,
                    "policy_question": scenario.policy_question,
                    "root_hash": scenario.root_hash,
                    "criteria": [
                        {
                            "criterion_id": item.criterion_id,
                            "key": item.criterion_key,
                            "name": item.name,
                            "description": item.description,
                            "direction": item.direction.value,
                            "unit": item.unit,
                            "display_order": item.display_order,
                        }
                        for item in sorted(
                            scenario.criteria, key=lambda value: value.display_order
                        )
                    ],
                    "alternatives": [
                        {
                            "alternative_id": item.alternative_id,
                            "key": item.alternative_key,
                            "name": item.name,
                            "description": item.description,
                            "display_order": item.display_order,
                        }
                        for item in sorted(
                            scenario.alternatives, key=lambda value: value.display_order
                        )
                    ],
                    "decision_matrix": [
                        {
                            "alternative_id": item.alternative_id,
                            "criterion_id": item.criterion_id,
                            "value": item.value_numeric,
                            "value_json": item.value_json,
                        }
                        for item in scenario.matrix_values
                    ],
                },
            },
            "02_configuration": {
                "schema_version": 1,
                "configuration_version_id": configuration.configuration_version_id,
                "configuration_hash": configuration.config_hash,
                "response_format": configuration.response_format.value,
                "missing_group_policy": configuration.missing_group_policy.value,
                "required_group_policy": dict(configuration.required_group_policy_json),
                "consistency_threshold": configuration.consistency_threshold,
                "stakeholder_groups": [
                    {
                        "stakeholder_group_id": item.session_stakeholder_group_id,
                        "key": item.group_key,
                        "name": item.name,
                        "configured_allocation_units": item.allocation_units,
                        "configured_voting_power": (
                            str(
                                Decimal(item.allocation_units)
                                / Decimal(configuration.allocation_total_units)
                            )
                        ),
                        "effective_voting_power": str(
                            effective_group_powers.get(
                                item.session_stakeholder_group_id, Decimal(0)
                            )
                        ),
                        "included_participant_count": group_counts[
                            item.session_stakeholder_group_id
                        ],
                        "small_group_warning": (
                            item.session_stakeholder_group_id in context["small_groups"]
                        ),
                    }
                    for item in sorted(
                        configuration.stakeholder_groups,
                        key=lambda value: value.display_order,
                    )
                    if item.is_active
                ],
                "algorithms": [
                    {
                        "role": item.role.value,
                        "implementation_id": item.algorithm_implementation_id,
                        "parameters": dict(item.parameter_json),
                        "parameter_hash": item.parameter_hash,
                    }
                    for item in sorted(
                        configuration.algorithm_configs,
                        key=lambda value: value.execution_order,
                    )
                ],
            },
            "03_validation": {
                "schema_version": 1,
                "roster_hash": processing.roster_hash,
                "total_submission_count": len(processing.submissions),
                "inclusion_counts": dict(sorted(inclusion_counts.items())),
                "exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
                "group_included_counts": [
                    {
                        "stakeholder_group": group_names.get(group_id, group_id),
                        "count": count,
                    }
                    for group_id, count in sorted(group_counts.items())
                ],
            },
            "04_weighting": {
                "schema_version": 1,
                "processing_run_id": processing.processing_run_id,
                "input_hash": processing.input_hash,
                "output_hash": processing.output_hash,
                "aggregate_matrices": [
                    _aggregate_matrix_manifest(item)
                    for item in processing.matrices
                    if item.level in {"stakeholder_group", "session"}
                ],
            },
            "05_ranking": {
                "schema_version": 1,
                "ranking_run_id": ranking.ranking_run_id,
                "input_hash": ranking.input_hash,
                "output_hash": ranking.output_hash,
                "implementation_id": ranking.algorithm_implementation_id,
                "implementation_version": ranking.implementation_version,
                "adapter_version": ranking.adapter_version,
                "aggregate_results": [
                    _aggregate_ranking_manifest(item)
                    for item in ranking.results
                    if item.level in {"stakeholder_group", "session"}
                ],
            },
            "06_analyses": {
                "schema_version": _COMMON_SECTION_SCHEMA_VERSIONS["06_analyses"],
                "completeness": analysis_completeness,
                "selected_results": analysis_results,
            },
            "07_provenance": {
                "schema_version": 1,
                "source_processing_run_id": processing.processing_run_id,
                "source_ranking_run_id": ranking.ranking_run_id,
                "source_analysis_run_ids": [item.analysis_run_id for item in analyses],
                "source_roster_hash": processing.roster_hash,
                "current_roster_hash_at_packaging": context["current_roster_hash"],
                "lineage_state_at_packaging": (
                    "stale" if context["stale_at_creation"] else "current"
                ),
                "source_artifacts": {
                    "processing": [
                        {
                            "artifact_id": item.run_artifact_id,
                            "artifact_type": item.artifact_type.value,
                            "content_hash": item.content_hash,
                        }
                        for item in sorted(
                            processing.artifacts,
                            key=lambda value: (
                                value.artifact_type.value, value.run_artifact_id
                            ),
                        )
                    ],
                    "ranking": [
                        {
                            "artifact_id": item.ranking_artifact_id,
                            "artifact_type": item.artifact_type.value,
                            "content_hash": item.content_hash,
                        }
                        for item in sorted(
                            ranking.artifacts,
                            key=lambda value: (
                                value.artifact_type.value, value.ranking_artifact_id
                            ),
                        )
                    ],
                    "analyses": [
                        {
                            "analysis_run_id": analysis.analysis_run_id,
                            "artifacts": [
                                {
                                    "artifact_id": item.analysis_artifact_id,
                                    "artifact_type": item.artifact_type.value,
                                    "content_hash": item.content_hash,
                                }
                                for item in sorted(
                                    analysis.artifacts,
                                    key=lambda value: (
                                        value.artifact_type.value,
                                        value.analysis_artifact_id,
                                    ),
                                )
                            ],
                        }
                        for analysis in analyses
                    ],
                },
                "processing_environment": dict(processing.environment_json),
                "ranking_environment": dict(ranking.environment_json),
                "analysis_environments": [
                    {
                        "method": item.method.value,
                        "environment": dict(item.environment_json),
                    }
                    for item in analyses
                ],
                "warnings": warnings,
            },
        }
        return sections, tuple(warnings)

    def _subjects(self, package_run_id: str, context):
        processing = context["processing"]
        ranking = context["ranking"]
        configuration = context["configuration"]
        participants = context["participants"]
        groups = {
            item.session_stakeholder_group_id: item
            for item in configuration.stakeholder_groups
        }
        participant_matrices = {
            item.validation_id: item
            for item in processing.matrices
            if item.level == "participant" and item.validation_id is not None
        }
        group_matrices = {
            item.stakeholder_group_id: item
            for item in processing.matrices
            if item.level == "stakeholder_group"
        }
        session_matrix = next(
            (item for item in processing.matrices if item.level == "session"), None
        )
        participant_rankings = {
            item.validation_id: item
            for item in ranking.results
            if item.level == "participant" and item.validation_id is not None
        }
        group_rankings = {
            item.stakeholder_group_id: item
            for item in ranking.results
            if item.level == "stakeholder_group"
        }
        session_ranking = next(
            (item for item in ranking.results if item.level == "session"), None
        )
        participant_analysis = next(
            (
                item
                for item in context["analyses"]
                if item.method == AnalysisMethod.PARTICIPANT_INFLUENCE
            ),
            None,
        )
        influence = (
            {}
            if participant_analysis is None
            else {
                item.subject_id: item
                for item in participant_analysis.cases
                if item.subject_type == "participant" and item.subject_id is not None
            }
        )
        effective_powers = _effective_group_powers(configuration, group_matrices)
        subjects = []
        for sequence, submission in enumerate(processing.submissions, start=1):
            participant = participants.get(submission.participant_id)
            if participant is None:
                raise CreateResultPackageError(
                    "A participant referenced by the source run is unavailable."
                )
            group = groups.get(submission.stakeholder_group_id)
            if group is None:
                raise CreateResultPackageError(
                    "A stakeholder group referenced by the source run is unavailable."
                )
            matrix = participant_matrices.get(submission.validation_id)
            personal_ranking = participant_rankings.get(submission.validation_id)
            influence_case = influence.get(submission.participant_id)
            included = submission.inclusion_status == RunInclusionStatus.INCLUDED
            result = {
                "schema_version": 1,
                "inclusion": {
                    "status": submission.inclusion_status.value,
                    "exclusion_reason": submission.exclusion_reason,
                },
                "preferences": (
                    None
                    if not included or matrix is None
                    else {
                        "criterion_ids": list(matrix.criterion_ids),
                        "matrix": dict(matrix.matrix_json),
                        "matrix_hash": matrix.matrix_hash,
                    }
                ),
                "weights": {
                    "participant": (
                        None
                        if not included or matrix is None
                        else dict(matrix.weights_json)
                    ),
                    "stakeholder_group": (
                        None
                        if group_matrices.get(submission.stakeholder_group_id) is None
                        else dict(
                            group_matrices[submission.stakeholder_group_id].weights_json
                        )
                    ),
                    "session": (
                        None
                        if session_matrix is None
                        else dict(session_matrix.weights_json)
                    ),
                },
                "rankings": {
                    "participant": (
                        None
                        if not included or personal_ranking is None
                        else _aggregate_ranking_manifest(personal_ranking)
                    ),
                    "stakeholder_group": (
                        None
                        if group_rankings.get(submission.stakeholder_group_id) is None
                        else _aggregate_ranking_manifest(
                            group_rankings[submission.stakeholder_group_id]
                        )
                    ),
                    "session": (
                        None
                        if session_ranking is None
                        else _aggregate_ranking_manifest(session_ranking)
                    ),
                },
                "stakeholder_representation": {
                    "group_name": group.name,
                    "configured_allocation_units": group.allocation_units,
                    "allocation_total_units": configuration.allocation_total_units,
                    "configured_voting_power": str(
                        Decimal(group.allocation_units)
                        / Decimal(configuration.allocation_total_units)
                    ),
                    "effective_voting_power": str(
                        effective_powers.get(
                            group.session_stakeholder_group_id, Decimal(0)
                        )
                    ),
                },
                "participant_influence": (
                    {
                        "status": "not_measured",
                        "explanation": (
                            "Participant influence was not selected for this package; "
                            "no individual causal effect is inferred."
                        ),
                    }
                    if participant_analysis is None
                    else {
                        "status": (
                            "not_evaluable"
                            if influence_case is None
                            else influence_case.status.value
                        ),
                        "results": (
                            None
                            if influence_case is None
                            else dict(influence_case.result_json)
                        ),
                        "warnings": (
                            []
                            if influence_case is None
                            else list(influence_case.warnings)
                        ),
                        "explanation": (
                            "This is a leave-one-participant-out counterfactual, not proof "
                            "that the participant caused the collective outcome."
                        ),
                    }
                ),
            }
            subjects.append(
                ResultPackageSubject.create(
                    package_subject_id=self._id_factory(),
                    package_run_id=package_run_id,
                    sequence=sequence,
                    subject_key=f"subject-{self._id_factory()}",
                    participant_id=submission.participant_id,
                    alias_snapshot=participant.alias or f"Participant {sequence:03d}",
                    stakeholder_group_id=submission.stakeholder_group_id,
                    stakeholder_group_label=group.name,
                    inclusion_status=submission.inclusion_status,
                    exclusion_reason=submission.exclusion_reason,
                    result_json=result,
                )
            )
        return tuple(subjects)

    @staticmethod
    def _progress(callback, phase: str, completed: int, message: str) -> None:
        if callback is not None:
            callback(PackageProgress(phase, completed, 7, message))


def _result(run: ResultPackageRun, *, reused: bool) -> CreateResultPackageResult:
    assert run.output_hash is not None
    provenance = next(
        (item for item in run.artifacts if item.name == "07_provenance"), None
    )
    warnings = [] if provenance is None else provenance.content_json.get("warnings", [])
    return CreateResultPackageResult(
        package_run_id=run.package_run_id,
        run_number=run.run_number,
        variants=run.variants,
        output_hash=run.output_hash,
        reused=reused,
        warning_count=len(warnings) if isinstance(warnings, list) else 0,
    )


def _package_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unavailable"


def _safe_error(error: Exception) -> str:
    if isinstance(error, CreateResultPackageError):
        return str(error)
    return "The result package could not be assembled from the frozen evidence."


def _aggregate_matrix_manifest(matrix: Any) -> dict[str, object]:
    """Project aggregate evidence without participant-validation identity fields."""

    return {
        "level": matrix.level,
        "stakeholder_group_id": matrix.stakeholder_group_id,
        "criterion_ids": list(matrix.criterion_ids),
        "matrix": dict(matrix.matrix_json),
        "weights": dict(matrix.weights_json),
        "diagnostics": dict(matrix.diagnostics_json),
        "matrix_hash": matrix.matrix_hash,
    }


def _aggregate_ranking_manifest(result: Any) -> dict[str, object]:
    """Project aggregate ranking evidence without participant-validation identity."""

    return {
        "source_processing_matrix_id": result.source_processing_matrix_id,
        "level": result.level,
        "stakeholder_group_id": result.stakeholder_group_id,
        "metric_label": result.metric_label,
        "alternatives": [item.to_manifest() for item in result.alternatives],
        "diagnostics": dict(result.diagnostics_json),
        "result_hash": result.result_hash,
    }


def _effective_group_powers(
    configuration: Any, group_matrices: Mapping[str, Any]
) -> dict[str, Decimal]:
    configured = {
        group.session_stakeholder_group_id: (
            Decimal(group.allocation_units)
            / Decimal(configuration.allocation_total_units)
        )
        for group in configuration.stakeholder_groups
        if group.is_active
    }
    if configuration.missing_group_policy == MissingGroupPolicy.ZERO_CONTRIBUTION:
        return configured
    effective = {
        group_id: power
        for group_id, power in configured.items()
        if group_id in group_matrices
    }
    if configuration.missing_group_policy == MissingGroupPolicy.EXCLUDED_RENORMALIZED:
        total = sum(effective.values(), Decimal(0))
        if total:
            effective = {
                group_id: power / total for group_id, power in effective.items()
            }
    return effective


def _participant_influence_case_manifest(case: AnalysisCase) -> dict[str, object]:
    """Project participant influence into the shared analysis-case contract.

    Participant influence produces two deterministic effect scopes: the
    participant's stakeholder-group reranking and the final session reranking.
    The shared package uses the session effect as the primary ``metrics`` /
    ``ranking`` pair so generic analysis consumers can render it consistently,
    while retaining the stakeholder-group effect as an explicit secondary block.

    Participant identity fields are removed from the shared projection. The
    original source case hash is retained so the de-identified projection can
    still be traced back to immutable source evidence.
    """
    manifest = case.to_manifest()
    source_content_hash = manifest.pop("content_hash")

    # The participant is the subject of the counterfactual. Do not expose either
    # subject_id or participant-scoped scope_id in a shared package.
    manifest["subject_id"] = None
    if str(manifest.get("scope_type", "")).casefold() == "participant":
        manifest["scope_id"] = None

    inputs = _strip_participant_identity_fields(dict(case.input_json))
    source_result = _strip_participant_identity_fields(dict(case.result_json))

    session_metrics = _json_mapping(source_result.get("session_metrics"))
    session_ranking = _json_sequence(source_result.get("session_ranking"))
    session_diagnostics = _json_mapping(
        source_result.get("session_weighting_diagnostics")
    )

    group_metrics = _json_mapping(source_result.get("group_metrics"))
    group_ranking = _json_sequence(source_result.get("group_ranking"))
    group_diagnostics = _json_mapping(
        source_result.get("group_weighting_diagnostics")
    )

    if case.status.value == "evaluated" and (not session_metrics or not session_ranking):
        raise CreateResultPackageError(
            "An evaluated participant-influence case is missing session metrics or ranking evidence."
        )

    # Normalize the primary session effect to the same result contract used by
    # the other analysis methods.
    projected_result: dict[str, object] = {
        "primary_effect_scope": "session",
        "metrics": session_metrics,
        "ranking": session_ranking,
        "weighting_diagnostics": session_diagnostics,
        "stakeholder_group_effect": {
            "metrics": group_metrics,
            "ranking": group_ranking,
            "weighting_diagnostics": group_diagnostics,
        },
    }

    # Preserve future deterministic fields without flattening them into the
    # primary contract. This prevents accidental evidence loss when the analysis
    # implementation grows new fields.
    known_result_keys = {
        "session_metrics",
        "session_ranking",
        "session_weighting_diagnostics",
        "group_metrics",
        "group_ranking",
        "group_weighting_diagnostics",
    }
    additional = {
        key: value
        for key, value in source_result.items()
        if key not in known_result_keys
    }
    if additional:
        projected_result["additional"] = additional

    manifest["input"] = inputs
    manifest["result"] = projected_result
    manifest["projection_schema_version"] = 2

    # Include the immutable source linkage in the projected case hash. As with
    # AnalysisCase.content_hash, the hash is calculated before adding the
    # content_hash field itself.
    manifest["source_content_hash"] = source_content_hash
    manifest["content_hash"] = hash_json(manifest)
    return manifest


_PARTICIPANT_IDENTITY_FIELDS = frozenset(
    {
        "participant_id",
        "omitted_participant_id",
        "subject_participant_id",
        "participant_alias",
        "alias_snapshot",
        "submission_id",
        "validation_id",
    }
)


def _strip_participant_identity_fields(value: Any) -> Any:
    """Recursively remove identity-bearing fields from shared participant evidence."""
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().casefold().replace(" ", "_")
            if normalized in _PARTICIPANT_IDENTITY_FIELDS:
                continue
            cleaned[key] = _strip_participant_identity_fields(item)
        return cleaned
    if isinstance(value, tuple):
        return [_strip_participant_identity_fields(item) for item in value]
    if isinstance(value, list):
        return [_strip_participant_identity_fields(item) for item in value]
    return value


def _json_mapping(value: Any) -> dict[str, Any]:
    """Return a mutable JSON-object projection without accepting arbitrary objects."""
    return dict(value) if isinstance(value, Mapping) else {}


def _json_sequence(value: Any) -> list[Any]:
    """Return a JSON-array projection for list/tuple analysis evidence."""
    if isinstance(value, (list, tuple)):
        return [_strip_participant_identity_fields(item) for item in value]
    return []
