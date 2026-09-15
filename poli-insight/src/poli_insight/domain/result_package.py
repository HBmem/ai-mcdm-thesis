"""Immutable final-result packages and participant-facing releases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Self

from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    BundleVariant,
    PackageArtifactType,
    ParticipantReleaseStatus,
    RunInclusionStatus,
    RunStatus,
)

JsonObject = Mapping[str, Any]


class ResultPackageRuleViolation(ValueError):
    pass


def _text(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ResultPackageRuleViolation(f"{label} must be nonempty and trimmed.")


def _aware(value: datetime | None, label: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ResultPackageRuleViolation(f"{label} must include timezone information.")


@dataclass(frozen=True, slots=True)
class ResultPackageArtifact:
    package_artifact_id: str
    package_run_id: str
    artifact_type: PackageArtifactType
    name: str
    sequence: int
    schema_version: int
    content_json: JsonObject
    content_hash: str
    variant: BundleVariant | None = None

    def __post_init__(self) -> None:
        _text(self.package_artifact_id, "Package artifact ID")
        _text(self.package_run_id, "Package artifact run ID")
        _text(self.name, "Package artifact name")
        if self.sequence < 1 or self.schema_version < 1:
            raise ResultPackageRuleViolation(
                "Package artifact sequence and schema version must be positive."
            )
        if (self.artifact_type == PackageArtifactType.VARIANT_MANIFEST) != (
            self.variant is not None
        ):
            raise ResultPackageRuleViolation(
                "Only variant manifests may carry a bundle variant."
            )
        if self.content_hash != hash_json(self.content_json):
            raise ResultPackageRuleViolation("Package artifact hash is inconsistent.")

    @classmethod
    def create(cls, **values: Any) -> Self:
        return cls(**values, content_hash=hash_json(values["content_json"]))

    def to_manifest(self) -> dict[str, object]:
        return {
            "artifact_type": self.artifact_type.value,
            "name": self.name,
            "sequence": self.sequence,
            "schema_version": self.schema_version,
            "variant": None if self.variant is None else self.variant.value,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ResultPackageSubject:
    package_subject_id: str
    package_run_id: str
    sequence: int
    subject_key: str
    participant_id: str
    alias_snapshot: str
    stakeholder_group_id: str
    stakeholder_group_label: str
    inclusion_status: RunInclusionStatus
    result_json: JsonObject
    content_hash: str
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.package_subject_id, "Package subject ID"),
            (self.package_run_id, "Package subject run ID"),
            (self.subject_key, "Package subject key"),
            (self.participant_id, "Package participant ID"),
            (self.alias_snapshot, "Package participant alias"),
            (self.stakeholder_group_id, "Package stakeholder group ID"),
            (self.stakeholder_group_label, "Package stakeholder group label"),
        ):
            _text(value, label)
        if self.sequence < 1:
            raise ResultPackageRuleViolation(
                "Package subject sequence must be positive."
            )
        if self.inclusion_status == RunInclusionStatus.INCLUDED:
            if self.exclusion_reason is not None:
                raise ResultPackageRuleViolation(
                    "Included package subjects cannot have an exclusion reason."
                )
        elif not self.exclusion_reason:
            raise ResultPackageRuleViolation(
                "Excluded package subjects require an exclusion reason."
            )
        if self.content_hash != hash_json(self._manifest()):
            raise ResultPackageRuleViolation("Package subject hash is inconsistent.")

    @classmethod
    def create(cls, **values: Any) -> Self:
        manifest = {
            "sequence": values["sequence"],
            "subject_key": values["subject_key"],
            "participant_id": values["participant_id"],
            "alias_snapshot": values["alias_snapshot"],
            "stakeholder_group_id": values["stakeholder_group_id"],
            "stakeholder_group_label": values["stakeholder_group_label"],
            "inclusion_status": values["inclusion_status"].value,
            "exclusion_reason": values.get("exclusion_reason"),
            "result": dict(values["result_json"]),
        }
        return cls(**values, content_hash=hash_json(manifest))

    def _manifest(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "subject_key": self.subject_key,
            "participant_id": self.participant_id,
            "alias_snapshot": self.alias_snapshot,
            "stakeholder_group_id": self.stakeholder_group_id,
            "stakeholder_group_label": self.stakeholder_group_label,
            "inclusion_status": self.inclusion_status.value,
            "exclusion_reason": self.exclusion_reason,
            "result": dict(self.result_json),
        }

    def to_public_manifest(self) -> dict[str, object]:
        """Return the identity-bearing mapping used only by public exports."""

        return {**self._manifest(), "content_hash": self.content_hash}


@dataclass(frozen=True, slots=True)
class ResultPackageRun:
    package_run_id: str
    session_id: str
    source_processing_run_id: str
    source_ranking_run_id: str
    source_analysis_run_ids: tuple[str, ...]
    variants: tuple[BundleVariant, ...]
    run_number: int
    status: RunStatus
    source_roster_hash: str
    source_processing_output_hash: str
    source_ranking_output_hash: str
    input_hash: str
    environment_json: JsonObject
    created_at: datetime
    created_by: str
    completed_at: datetime
    correlation_id: str
    artifacts: tuple[ResultPackageArtifact, ...] = field(default_factory=tuple)
    subjects: tuple[ResultPackageSubject, ...] = field(default_factory=tuple)
    output_hash: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.package_run_id, "Package run ID"),
            (self.session_id, "Package session ID"),
            (self.source_processing_run_id, "Package processing run ID"),
            (self.source_ranking_run_id, "Package ranking run ID"),
            (self.source_roster_hash, "Package roster hash"),
            (self.source_processing_output_hash, "Package processing output hash"),
            (self.source_ranking_output_hash, "Package ranking output hash"),
            (self.input_hash, "Package input hash"),
            (self.created_by, "Package creator"),
            (self.correlation_id, "Package correlation ID"),
        ):
            _text(value, label)
        if self.run_number < 1:
            raise ResultPackageRuleViolation("Package run number must be positive.")
        _aware(self.created_at, "Package creation time")
        _aware(self.completed_at, "Package completion time")
        if self.status not in {RunStatus.SUCCEEDED, RunStatus.FAILED}:
            raise ResultPackageRuleViolation("Package runs must be terminal.")
        if not self.source_analysis_run_ids or len(
            set(self.source_analysis_run_ids)
        ) != len(self.source_analysis_run_ids):
            raise ResultPackageRuleViolation(
                "Package runs require unique analysis source runs."
            )
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ResultPackageRuleViolation(
                "Package variants must be nonempty and unique."
            )
        if any(item.package_run_id != self.package_run_id for item in self.artifacts):
            raise ResultPackageRuleViolation("Package artifacts belong to another run.")
        if any(item.package_run_id != self.package_run_id for item in self.subjects):
            raise ResultPackageRuleViolation("Package subjects belong to another run.")
        if len({item.package_artifact_id for item in self.artifacts}) != len(
            self.artifacts
        ) or len({item.sequence for item in self.artifacts}) != len(self.artifacts):
            raise ResultPackageRuleViolation(
                "Package artifacts require unique identities and sequence numbers."
            )
        if (
            len({item.package_subject_id for item in self.subjects})
            != len(self.subjects)
            or len({item.sequence for item in self.subjects}) != len(self.subjects)
            or len({item.subject_key for item in self.subjects}) != len(self.subjects)
            or len({item.participant_id for item in self.subjects})
            != len(self.subjects)
        ):
            raise ResultPackageRuleViolation(
                "Package subjects require unique identities, keys, participants, and sequence numbers."
            )
        if BundleVariant.PUBLIC not in self.variants and self.subjects:
            raise ResultPackageRuleViolation(
                "Anonymous-only packages cannot retain participant subjects."
            )
        if self.status == RunStatus.SUCCEEDED:
            input_manifests = [
                item
                for item in self.artifacts
                if item.artifact_type == PackageArtifactType.INPUT_MANIFEST
            ]
            if len(input_manifests) != 1:
                raise ResultPackageRuleViolation(
                    "Successful packages require one input manifest."
                )
            manifests = {
                item.variant
                for item in self.artifacts
                if item.artifact_type == PackageArtifactType.VARIANT_MANIFEST
            }
            if manifests != set(self.variants):
                raise ResultPackageRuleViolation(
                    "Successful packages require one manifest per selected variant."
                )
            if BundleVariant.PUBLIC in self.variants and not self.subjects:
                raise ResultPackageRuleViolation(
                    "Public packages require participant subject mappings."
                )
            expected = hash_json(
                {
                    "schema_version": 1,
                    "input_hash": self.input_hash,
                    "artifacts": [item.content_hash for item in self.artifacts],
                    "subjects": [item.content_hash for item in self.subjects],
                }
            )
            if self.output_hash != expected:
                raise ResultPackageRuleViolation("Package output hash is inconsistent.")
            if self.failure_code is not None or self.failure_detail is not None:
                raise ResultPackageRuleViolation(
                    "Successful packages cannot contain failure evidence."
                )
        else:
            if (
                self.output_hash is not None
                or not self.failure_code
                or not self.failure_detail
            ):
                raise ResultPackageRuleViolation(
                    "Failed packages require safe failure evidence and no output hash."
                )
            if self.artifacts or self.subjects:
                raise ResultPackageRuleViolation(
                    "Failed packages cannot retain partial output evidence."
                )

    @classmethod
    def succeeded(
        cls,
        *,
        artifacts: tuple[ResultPackageArtifact, ...],
        subjects: tuple[ResultPackageSubject, ...],
        **values: Any,
    ) -> Self:
        output_hash = hash_json(
            {
                "schema_version": 1,
                "input_hash": values["input_hash"],
                "artifacts": [item.content_hash for item in artifacts],
                "subjects": [item.content_hash for item in subjects],
            }
        )
        return cls(
            **values,
            status=RunStatus.SUCCEEDED,
            artifacts=artifacts,
            subjects=subjects,
            output_hash=output_hash,
        )

    @classmethod
    def failed(cls, *, failure_code: str, failure_detail: str, **values: Any) -> Self:
        return cls(
            **values,
            status=RunStatus.FAILED,
            failure_code=failure_code,
            failure_detail=failure_detail,
        )


@dataclass(frozen=True, slots=True)
class ParticipantResultRelease:
    release_id: str
    session_id: str
    package_run_id: str
    package_artifact_id: str
    version_number: int
    status: ParticipantReleaseStatus
    released_at: datetime
    released_by: str
    withdrawn_at: datetime | None = None
    withdrawn_by: str | None = None
    withdrawal_reason: str | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.release_id, "Participant release ID"),
            (self.session_id, "Participant release session ID"),
            (self.package_run_id, "Participant release package ID"),
            (self.package_artifact_id, "Participant release artifact ID"),
            (self.released_by, "Participant release actor"),
        ):
            _text(value, label)
        if self.version_number < 1:
            raise ResultPackageRuleViolation("Release version must be positive.")
        _aware(self.released_at, "Participant release time")
        _aware(self.withdrawn_at, "Participant withdrawal time")
        if self.status == ParticipantReleaseStatus.ACTIVE:
            if any(
                value is not None
                for value in (
                    self.withdrawn_at,
                    self.withdrawn_by,
                    self.withdrawal_reason,
                )
            ):
                raise ResultPackageRuleViolation(
                    "Active releases cannot contain withdrawal evidence."
                )
        else:
            if (
                self.withdrawn_at is None
                or not self.withdrawn_by
                or not self.withdrawal_reason
            ):
                raise ResultPackageRuleViolation(
                    "Withdrawn releases require complete withdrawal evidence."
                )

    def withdraw(self, *, at: datetime, actor_id: str, reason: str) -> Self:
        if self.status != ParticipantReleaseStatus.ACTIVE:
            raise ResultPackageRuleViolation("Only an active release can be withdrawn.")
        _aware(at, "Participant withdrawal time")
        _text(actor_id, "Participant withdrawal actor")
        _text(reason, "Participant withdrawal reason")
        return replace(
            self,
            status=ParticipantReleaseStatus.WITHDRAWN,
            withdrawn_at=at,
            withdrawn_by=actor_id,
            withdrawal_reason=reason,
        )
