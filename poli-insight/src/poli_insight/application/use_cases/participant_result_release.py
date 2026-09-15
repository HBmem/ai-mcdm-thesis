"""Release and securely resolve participant-specific packaged results."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.application.use_cases._operational_audit import (
    operational_audit_event,
)
from poli_insight.application.use_cases.participant_access import (
    ParticipantAccessError,
    authorize_participant_access,
)
from poli_insight.core.ids import new_id
from poli_insight.core.time import utc_now
from poli_insight.domain.content_hash import hash_json
from poli_insight.domain.enum import (
    ActorType,
    AuditAction,
    BundleVariant,
    PackageArtifactType,
    ParticipantReleaseStatus,
    RunStatus,
    SessionStatus,
)
from poli_insight.domain.result_package import ParticipantResultRelease


class ParticipantResultReleaseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReleaseParticipantResultsCommand:
    session_id: str
    package_run_id: str
    actor_id: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True)
class WithdrawParticipantResultsCommand:
    session_id: str
    actor_id: str
    reason: str
    actor_type: ActorType = ActorType.USER
    correlation_id: str = field(default_factory=lambda: str(new_id()))


@dataclass(frozen=True, slots=True, repr=False)
class ReleasedParticipantResult:
    session_id: str
    session_title: str
    public_slug: str
    release_version: int
    package_run_id: str
    alias: str
    stakeholder_group: str
    result: Mapping[str, object]
    aggregate_sections: Mapping[str, Mapping[str, object]]

    def __post_init__(self) -> None:
        object.__setattr__(self, "result", MappingProxyType(dict(self.result)))
        object.__setattr__(
            self,
            "aggregate_sections",
            MappingProxyType(
                {
                    key: MappingProxyType(dict(value))
                    for key, value in self.aggregate_sections.items()
                }
            ),
        )


class ReleaseParticipantResults:
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
        self, command: ReleaseParticipantResultsCommand
    ) -> ParticipantResultRelease:
        now = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.session.get(command.session_id)
            package = unit_of_work.result_packages.get(command.package_run_id)
            if (
                session is None
                or package is None
                or package.session_id != command.session_id
            ):
                raise ParticipantResultReleaseError(
                    "The selected package is unavailable."
                )
            if session.identity_policy.casefold() == "anonymous":
                raise ParticipantResultReleaseError(
                    "Anonymous sessions cannot release identity-linked results."
                )
            if session.status != SessionStatus.CLOSED:
                raise ParticipantResultReleaseError(
                    "Participant results may be released only from a closed session."
                )
            if (
                package.status != RunStatus.SUCCEEDED
                or BundleVariant.PUBLIC not in package.variants
            ):
                raise ParticipantResultReleaseError(
                    "Select a successful identity-linked public package."
                )
            source = unit_of_work.processing_runs.get(package.source_processing_run_id)
            if (
                source is None
                or _current_roster_hash(unit_of_work, source)
                != package.source_roster_hash
            ):
                raise ParticipantResultReleaseError(
                    "This package is stale. Re-run processing and package current results."
                )
            public_artifact = next(
                (
                    item
                    for item in package.artifacts
                    if item.artifact_type == PackageArtifactType.VARIANT_MANIFEST
                    and item.variant == BundleVariant.PUBLIC
                ),
                None,
            )
            if public_artifact is None:
                raise ParticipantResultReleaseError(
                    "The public package manifest is missing."
                )
            previous = unit_of_work.participant_result_releases.get_active_for_session(
                command.session_id, for_update=True
            )
            version_number = unit_of_work.participant_result_releases.next_version(
                command.session_id
            )
            if previous is not None:
                withdrawn = previous.withdraw(
                    at=now,
                    actor_id=command.actor_id,
                    reason=f"Superseded by participant release {version_number}.",
                )
                unit_of_work.participant_result_releases.save(withdrawn)
            release = ParticipantResultRelease(
                release_id=self._id_factory(),
                session_id=command.session_id,
                package_run_id=package.package_run_id,
                package_artifact_id=public_artifact.package_artifact_id,
                version_number=version_number,
                status=ParticipantReleaseStatus.ACTIVE,
                released_at=now,
                released_by=command.actor_id,
            )
            unit_of_work.participant_result_releases.add(release)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=now,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.PUBLISHED,
                    entity_type="participant_result_release",
                    entity_id=release.release_id,
                    correlation_id=command.correlation_id,
                    use_case="release_participant_results",
                    after_json={
                        "release_version": version_number,
                        "package_run_id": package.package_run_id,
                        "package_output_hash": package.output_hash,
                    },
                )
            )
            unit_of_work.commit()
            return release


class WithdrawParticipantResults:
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
        self, command: WithdrawParticipantResultsCommand
    ) -> ParticipantResultRelease:
        if not command.reason.strip():
            raise ParticipantResultReleaseError("A withdrawal reason is required.")
        now = self._clock()
        with self._unit_of_work_factory() as unit_of_work:
            active = unit_of_work.participant_result_releases.get_active_for_session(
                command.session_id, for_update=True
            )
            if active is None:
                raise ParticipantResultReleaseError(
                    "There is no active participant result release."
                )
            withdrawn = active.withdraw(
                at=now, actor_id=command.actor_id, reason=command.reason.strip()
            )
            unit_of_work.participant_result_releases.save(withdrawn)
            unit_of_work.audit_events.add(
                operational_audit_event(
                    event_id=self._id_factory(),
                    occurred_at=now,
                    session_id=command.session_id,
                    actor_id=command.actor_id,
                    actor_type=command.actor_type,
                    action=AuditAction.WITHDRAWN,
                    entity_type="participant_result_release",
                    entity_id=withdrawn.release_id,
                    correlation_id=command.correlation_id,
                    use_case="withdraw_participant_results",
                    before_json={"status": ParticipantReleaseStatus.ACTIVE.value},
                    after_json={"status": ParticipantReleaseStatus.WITHDRAWN.value},
                    reason_text=command.reason.strip(),
                )
            )
            unit_of_work.commit()
            return withdrawn


class ParticipantResultAccess:
    def __init__(
        self,
        unit_of_work_factory: Callable[[], UnitOfWork],
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    def available(self, participant_id: str) -> bool:
        if not participant_id.strip():
            return False
        with self._unit_of_work_factory() as unit_of_work:
            participant = unit_of_work.participants.get(participant_id)
            if participant is None:
                return False
            release = unit_of_work.participant_result_releases.get_active_for_session(
                participant.session_id
            )
            if release is None:
                return False
            package = unit_of_work.result_packages.get(release.package_run_id)
            if package is None:
                return False
            source = unit_of_work.processing_runs.get(package.source_processing_run_id)
            if (
                source is None
                or _current_roster_hash(unit_of_work, source)
                != package.source_roster_hash
            ):
                return False
            return any(
                item.participant_id == participant_id for item in package.subjects
            )

    def execute(self, access_token: str) -> ReleasedParticipantResult:
        generic_error = "Released participant results are unavailable for this link."
        try:
            with self._unit_of_work_factory() as unit_of_work:
                participant = authorize_participant_access(
                    unit_of_work, access_token=access_token, at=self._clock()
                )
                release = (
                    unit_of_work.participant_result_releases.get_active_for_session(
                        participant.session_id
                    )
                )
                if release is None:
                    raise ParticipantResultReleaseError(generic_error)
                package = unit_of_work.result_packages.get(release.package_run_id)
                session = unit_of_work.session.get(participant.session_id)
                if package is None or session is None:
                    raise ParticipantResultReleaseError(generic_error)
                source = unit_of_work.processing_runs.get(
                    package.source_processing_run_id
                )
                if (
                    source is None
                    or _current_roster_hash(unit_of_work, source)
                    != package.source_roster_hash
                ):
                    raise ParticipantResultReleaseError(generic_error)
                subject = next(
                    (
                        item
                        for item in package.subjects
                        if item.participant_id == participant.participant_id
                    ),
                    None,
                )
                if subject is None:
                    raise ParticipantResultReleaseError(generic_error)
                common = {
                    item.name: item.content_json
                    for item in package.artifacts
                    if item.artifact_type == PackageArtifactType.COMMON_SECTION
                }
                unit_of_work.commit()
                return ReleasedParticipantResult(
                    session_id=session.session_id,
                    session_title=session.title,
                    public_slug=session.public_slug,
                    release_version=release.version_number,
                    package_run_id=package.package_run_id,
                    alias=subject.alias_snapshot,
                    stakeholder_group=subject.stakeholder_group_label,
                    result=subject.result_json,
                    aggregate_sections=common,
                )
        except (ParticipantAccessError, ParticipantResultReleaseError) as error:
            raise ParticipantResultReleaseError(generic_error) from error


class ListParticipantResultReleases:
    """Return immutable release history for the moderator workspace."""

    def __init__(self, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def execute(self, session_id: str) -> tuple[ParticipantResultRelease, ...]:
        if not session_id.strip():
            raise ValueError("Session ID cannot be empty.")
        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.participant_result_releases.list_for_session(session_id)


def _current_roster_hash(unit_of_work: UnitOfWork, source) -> str:
    session = unit_of_work.session.get(source.session_id)
    if session is None:
        return "missing"
    configuration = next(
        (
            item
            for item in session.configurations
            if item.configuration_version_id == source.configuration_version_id
        ),
        None,
    )
    if configuration is None:
        return "missing"
    if (
        session.active_configuration_version_id
        != configuration.configuration_version_id
    ):
        return "configuration-mismatch"
    submissions = unit_of_work.submissions.list_effective_for_configuration(
        configuration.configuration_version_id
    )
    participants = {
        item.participant_id: item
        for item in unit_of_work.participants.get_many(
            tuple(item.participant_id for item in submissions)
        )
    }
    return hash_json(
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
