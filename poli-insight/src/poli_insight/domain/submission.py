"""Immutable submission attempts and participant-authored answers.

Draft submissions may replace or remove answer rows. Submitting an attempt
builds a deterministic manifest from those rows, freezes its SHA-256 digest,
and prevents any further content edits. Resubmissions form an explicit,
monotonic predecessor chain; withdrawal and supersession preserve the final
answer evidence instead of deleting or rewriting it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Self

from poli_insight.domain.content_hash import canonical_json_bytes, hash_json
from poli_insight.domain.enum import (
    QuestionType,
    ResponseFormat,
    ResponseTargetType,
    SubmissionStatus,
)
from poli_insight.domain.participation import Participant
from poli_insight.domain.session import (
    ResponseQuestionDefinition,
    SessionConfigurationVersion,
    SessionStakeholderGroup,
)

JsonObject = Mapping[str, Any]
ANSWER_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_VALUE_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_VALUE_KEYS = frozenset(
    {
        "selected_scale_value_id",
        "numeric_value",
        "rank_value",
    }
)


class SubmissionRuleViolation(ValueError):
    """Raised when an operation violates a submission business rule."""


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise SubmissionRuleViolation(f"{field_name} cannot be empty.")
    if value != value.strip():
        raise SubmissionRuleViolation(
            f"{field_name} cannot contain leading or trailing whitespace."
        )


def _require_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _require_actor(actor_id: str) -> None:
    _require_text(actor_id, "Actor ID")


def _require_aware_datetime(
    value: datetime | None,
    field_name: str,
) -> None:
    if value is not None and (
        value.tzinfo is None or value.utcoffset() is None
    ):
        raise SubmissionRuleViolation(
            f"{field_name} must include timezone information."
        )


def _require_sha256(value: str, field_name: str) -> None:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise SubmissionRuleViolation(
            f"{field_name} must be a lowercase hexadecimal SHA-256 digest."
        )


def _require_positive_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SubmissionRuleViolation(
            f"{field_name} must be a positive integer."
        )


def _require_nonnegative_integer(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SubmissionRuleViolation(
            f"{field_name} must be a nonnegative integer."
        )


def _require_not_before(
    value: datetime,
    earliest: datetime,
    field_name: str,
) -> None:
    if value < earliest:
        raise SubmissionRuleViolation(
            f"{field_name} cannot precede {earliest.isoformat()}."
        )


def _validate_json(value: object, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise SubmissionRuleViolation(f"{field_name} must be a JSON object.")
    try:
        canonical_json_bytes(value)
    except (TypeError, ValueError) as error:
        raise SubmissionRuleViolation(
            f"{field_name} must be canonicalizable JSON: {error}"
        ) from error


@dataclass(frozen=True, slots=True)
class SubmissionAnswer:
    """One participant-authored value for one configured question."""

    submission_answer_id: str
    submission_id: str
    question_definition_id: str
    raw_value_json: JsonObject
    value_schema_version: int
    raw_value_hash: str
    answered_at: datetime

    selected_scale_value_id: str | None = None
    numeric_value: Decimal | None = None
    rank_value: int | None = None
    response_time_ms: int | None = None

    def __post_init__(self) -> None:
        for field_name, value in (
            ("Submission answer ID", self.submission_answer_id),
            ("Answer submission ID", self.submission_id),
            ("Answer question definition ID", self.question_definition_id),
        ):
            _require_text(value, field_name)
        _require_optional_text(
            self.selected_scale_value_id,
            "Selected scale value ID",
        )
        _require_positive_integer(
            self.value_schema_version,
            "Answer value schema version",
        )
        _require_aware_datetime(self.answered_at, "Answer time")
        if self.response_time_ms is not None:
            _require_nonnegative_integer(
                self.response_time_ms,
                "Answer response time",
            )
        self.validate_integrity()
        self._validate_basic_payload()

    @classmethod
    def create(
        cls,
        *,
        submission_answer_id: str,
        submission_id: str,
        question: ResponseQuestionDefinition,
        raw_value_json: JsonObject,
        answered_at: datetime,
        response_time_ms: int | None = None,
        value_schema_version: int = DEFAULT_VALUE_SCHEMA_VERSION,
    ) -> SubmissionAnswer:
        """Create an answer and derive its typed query columns safely."""

        selected_scale_value_id, numeric_value, rank_value = (
            _typed_values_from_raw(raw_value_json)
        )
        answer = cls(
            submission_answer_id=submission_answer_id,
            submission_id=submission_id,
            question_definition_id=question.question_definition_id,
            raw_value_json=deepcopy(dict(raw_value_json)),
            value_schema_version=value_schema_version,
            raw_value_hash=hash_json(raw_value_json),
            answered_at=answered_at,
            selected_scale_value_id=selected_scale_value_id,
            numeric_value=numeric_value,
            rank_value=rank_value,
            response_time_ms=response_time_ms,
        )
        answer.validate_for_question(question)
        return answer

    def validate_integrity(self) -> None:
        """Verify the raw envelope still matches its immutable digest."""

        _validate_json(self.raw_value_json, "Answer raw value")
        _require_sha256(self.raw_value_hash, "Answer raw value hash")
        if hash_json(self.raw_value_json) != self.raw_value_hash:
            raise SubmissionRuleViolation(
                "Answer raw value does not match raw_value_hash."
            )

    def validate_for_question(
        self,
        question: ResponseQuestionDefinition,
    ) -> None:
        """Validate question ownership, target semantics, and value shape."""

        self.validate_integrity()
        if self.question_definition_id != question.question_definition_id:
            raise SubmissionRuleViolation(
                "Answer references a different question definition."
            )

        if question.question_type in {
            QuestionType.CRITERION_RATING,
            QuestionType.ALTERNATIVE_RATING,
        }:
            if self.rank_value is not None:
                raise SubmissionRuleViolation(
                    "A rating answer cannot contain a rank value."
                )
            if (
                self.selected_scale_value_id is None
                and self.numeric_value is None
            ):
                raise SubmissionRuleViolation(
                    "A rating answer requires a scale selection or numeric "
                    "value."
                )
            return

        if question.question_type == QuestionType.CRITERION_PAIR:
            if self.rank_value is not None:
                raise SubmissionRuleViolation(
                    "A pairwise answer cannot contain a rank value."
                )
            if (
                self.selected_scale_value_id is None
                and self.numeric_value is None
            ):
                raise SubmissionRuleViolation(
                    "A pairwise answer requires a scale selection or numeric "
                    "ratio."
                )
            if self.numeric_value is not None and self.numeric_value <= 0:
                raise SubmissionRuleViolation(
                    "A numeric pairwise ratio must be greater than zero."
                )
            return

        if question.question_type == QuestionType.ALTERNATIVE_RANK:
            if self.rank_value is None:
                raise SubmissionRuleViolation(
                    "A ranking answer requires a positive rank value."
                )
            if (
                self.selected_scale_value_id is not None
                or self.numeric_value is not None
            ):
                raise SubmissionRuleViolation(
                    "A ranking answer cannot contain scale or numeric values."
                )
            return

        raise SubmissionRuleViolation(
            f"Unsupported question type: {question.question_type!r}."
        )

    def _validate_basic_payload(self) -> None:
        populated_values = sum(
            value is not None
            for value in (
                self.selected_scale_value_id,
                self.numeric_value,
                self.rank_value,
            )
        )
        if populated_values != 1:
            raise SubmissionRuleViolation(
                "An answer must contain exactly one typed value."
            )
        if self.numeric_value is not None:
            if not isinstance(self.numeric_value, Decimal):
                raise SubmissionRuleViolation(
                    "Answer numeric value must be a Decimal."
                )
            if not self.numeric_value.is_finite():
                raise SubmissionRuleViolation(
                    "Answer numeric value must be finite."
                )
        if self.rank_value is not None:
            _require_positive_integer(self.rank_value, "Answer rank")

        present_raw_keys = _VALUE_KEYS.intersection(self.raw_value_json)
        if len(present_raw_keys) != 1:
            raise SubmissionRuleViolation(
                "Answer raw value must contain exactly one supported value key."
            )
        raw_key = next(iter(present_raw_keys))
        expected_key = (
            "selected_scale_value_id"
            if self.selected_scale_value_id is not None
            else "numeric_value"
            if self.numeric_value is not None
            else "rank_value"
        )
        if raw_key != expected_key:
            raise SubmissionRuleViolation(
                "Answer raw value does not match its typed value column."
            )
        expected_value: object = (
            self.selected_scale_value_id
            if self.selected_scale_value_id is not None
            else self.numeric_value
            if self.numeric_value is not None
            else self.rank_value
        )
        if not _equivalent_value(self.raw_value_json[raw_key], expected_value):
            raise SubmissionRuleViolation(
                "Answer raw value does not match its typed value."
            )


@dataclass(frozen=True, slots=True)
class Submission:
    """One versioned response attempt pinned to immutable session inputs."""

    submission_id: str
    session_id: str
    participant_id: str
    configuration_version_id: str
    scenario_snapshot_id: str
    session_stakeholder_group_id: str
    attempt_number: int
    status: SubmissionStatus
    response_format: ResponseFormat
    response_target_type: ResponseTargetType
    started_at: datetime
    last_saved_at: datetime
    created_at: datetime
    created_by: str
    updated_at: datetime
    updated_by: str

    previous_submission_id: str | None = None
    answers: tuple[SubmissionAnswer, ...] = field(default_factory=tuple)
    answer_manifest_json: JsonObject | None = None
    answer_schema_version: int | None = None
    answers_hash: str | None = None
    submitted_at: datetime | None = None
    submitted_by: str | None = None
    superseded_at: datetime | None = None
    superseded_by: str | None = None
    withdrawn_at: datetime | None = None
    withdrawn_by: str | None = None
    withdrawal_reason: str | None = None
    client_metadata_json: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_attempt_lineage_shape()
        self._validate_answers()
        self._validate_schedule()
        self._validate_lifecycle_state()
        self.validate_integrity()

    @classmethod
    def start(
        cls,
        *,
        submission_id: str,
        participant: Participant,
        configuration: SessionConfigurationVersion,
        group: SessionStakeholderGroup,
        actor_id: str,
        at: datetime,
        previous_submission: Submission | None = None,
        client_metadata_json: JsonObject | None = None,
        administrative_resubmission_override: bool = False,
    ) -> Submission:
        """Start attempt one or derive the next attempt from its predecessor."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Submission start time")
        if not participant.can_access:
            raise SubmissionRuleViolation(
                "Only an active participant can start a submission."
            )
        try:
            participant.validate_binding(
                configuration=configuration,
                group=group,
            )
        except ValueError as error:
            raise SubmissionRuleViolation(str(error)) from error
        if not configuration.is_activated:
            raise SubmissionRuleViolation(
                "A submission requires an activated configuration."
            )
        if at < participant.enrolled_at:
            raise SubmissionRuleViolation(
                "Submission cannot start before participant enrollment."
            )

        if previous_submission is None:
            attempt_number = 1
            previous_submission_id = None
        else:
            _validate_resubmission_predecessor(
                previous_submission,
                participant=participant,
                configuration=configuration,
                administrative_override=administrative_resubmission_override,
            )
            if (
                not configuration.allow_resubmissions
                and not administrative_resubmission_override
            ):
                raise SubmissionRuleViolation(
                    "The active configuration does not allow resubmissions."
                )
            attempt_number = previous_submission.attempt_number + 1
            if (
                attempt_number > configuration.max_submissions_per_participant
                and not administrative_resubmission_override
            ):
                raise SubmissionRuleViolation(
                    "The participant has reached the configured submission "
                    "attempt limit."
                )
            previous_submission_id = previous_submission.submission_id

        metadata = (
            deepcopy(dict(client_metadata_json))
            if client_metadata_json is not None
            else {}
        )
        return cls(
            submission_id=submission_id,
            session_id=participant.session_id,
            participant_id=participant.participant_id,
            configuration_version_id=configuration.configuration_version_id,
            scenario_snapshot_id=configuration.scenario_snapshot_id,
            session_stakeholder_group_id=(
                participant.session_stakeholder_group_id
            ),
            attempt_number=attempt_number,
            previous_submission_id=previous_submission_id,
            status=SubmissionStatus.DRAFT,
            response_format=configuration.response_format,
            response_target_type=configuration.response_target_type,
            started_at=at,
            last_saved_at=at,
            created_at=at,
            created_by=actor_id,
            updated_at=at,
            updated_by=actor_id,
            client_metadata_json=metadata,
        )

    @property
    def is_editable(self) -> bool:
        return self.status == SubmissionStatus.DRAFT

    @property
    def is_finalized(self) -> bool:
        return self.status in {
            SubmissionStatus.SUBMITTED,
            SubmissionStatus.SUPERSEDED,
            SubmissionStatus.WITHDRAWN,
        }

    def answer_for_question(
        self,
        question_definition_id: str,
    ) -> SubmissionAnswer | None:
        _require_text(question_definition_id, "Question definition ID")
        return next(
            (
                answer
                for answer in self.answers
                if answer.question_definition_id == question_definition_id
            ),
            None,
        )

    def save_answer(
        self,
        answer: SubmissionAnswer,
        *,
        configuration: SessionConfigurationVersion,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Insert or replace one draft answer without creating a duplicate."""

        self._require_draft_edit(actor_id=actor_id, at=at)
        self._validate_configuration_binding(configuration)
        if answer.submission_id != self.submission_id:
            raise SubmissionRuleViolation(
                "Answer belongs to a different submission."
            )
        if answer.answered_at < self.started_at or answer.answered_at > at:
            raise SubmissionRuleViolation(
                "Answer time must fall between submission start and save time."
            )
        question = _question_by_id(
            configuration,
            answer.question_definition_id,
        )
        answer.validate_for_question(question)

        existing = self.answer_for_question(answer.question_definition_id)
        if (
            existing is not None
            and existing.submission_answer_id != answer.submission_answer_id
        ):
            raise SubmissionRuleViolation(
                "Editing an answer must preserve its answer identity."
            )
        retained = tuple(
            candidate
            for candidate in self.answers
            if candidate.question_definition_id
            != answer.question_definition_id
        )
        display_order = {
            question.question_definition_id: question.display_order
            for question in configuration.question_definitions
        }
        updated_answers = tuple(
            sorted(
                (*retained, answer),
                key=lambda candidate: (
                    display_order[candidate.question_definition_id],
                    candidate.question_definition_id,
                ),
            )
        )
        return replace(
            self,
            answers=updated_answers,
            last_saved_at=at,
            updated_at=at,
            updated_by=actor_id,
        )

    def remove_answer(
        self,
        question_definition_id: str,
        *,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Remove one answer while the attempt remains a draft."""

        self._require_draft_edit(actor_id=actor_id, at=at)
        existing = self.answer_for_question(question_definition_id)
        if existing is None:
            raise SubmissionRuleViolation(
                "Submission does not contain an answer for that question."
            )
        return replace(
            self,
            answers=tuple(
                answer
                for answer in self.answers
                if answer.question_definition_id != question_definition_id
            ),
            last_saved_at=at,
            updated_at=at,
            updated_by=actor_id,
        )

    def submit(
        self,
        configuration: SessionConfigurationVersion,
        *,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Validate, canonicalize, hash, and freeze the draft answers."""

        self._require_draft_edit(actor_id=actor_id, at=at)
        self._validate_configuration_binding(configuration)
        self._validate_answer_set(configuration)
        manifest = self._build_answer_manifest()
        return replace(
            self,
            status=SubmissionStatus.SUBMITTED,
            answer_manifest_json=manifest,
            answer_schema_version=ANSWER_MANIFEST_SCHEMA_VERSION,
            answers_hash=hash_json(manifest),
            submitted_at=at,
            submitted_by=actor_id,
            last_saved_at=at,
            updated_at=at,
            updated_by=actor_id,
        )

    def supersede_with(
        self,
        replacement: Submission,
        *,
        actor_id: str,
        at: datetime,
    ) -> Self:
        """Mark this effective attempt superseded by its submitted successor."""

        _require_actor(actor_id)
        _require_aware_datetime(at, "Submission supersession time")
        self.validate_integrity()
        replacement.validate_integrity()
        if self.status != SubmissionStatus.SUBMITTED:
            raise SubmissionRuleViolation(
                "Only an effective submitted attempt can be superseded."
            )
        if replacement.status != SubmissionStatus.SUBMITTED:
            raise SubmissionRuleViolation(
                "A replacement must be successfully submitted first."
            )
        replacement.validate_predecessor(self)
        if replacement.submitted_at is None:
            raise AssertionError("Submitted replacement is missing submitted_at.")
        _require_not_before(
            at,
            replacement.submitted_at,
            "Submission supersession time",
        )
        _require_not_before(
            at,
            self.updated_at,
            "Submission supersession time",
        )
        return replace(
            self,
            status=SubmissionStatus.SUPERSEDED,
            superseded_at=at,
            superseded_by=actor_id,
            updated_at=at,
            updated_by=actor_id,
        )

    def withdraw(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        """Withdraw a submitted attempt while preserving its frozen content."""

        _require_actor(actor_id)
        _require_text(reason, "Submission withdrawal reason")
        _require_aware_datetime(at, "Submission withdrawal time")
        self.validate_integrity()
        if self.status != SubmissionStatus.SUBMITTED:
            raise SubmissionRuleViolation(
                "Only an effective submitted attempt can be withdrawn."
            )
        _require_not_before(
            at,
            self.updated_at,
            "Submission withdrawal time",
        )
        return replace(
            self,
            status=SubmissionStatus.WITHDRAWN,
            withdrawn_at=at,
            withdrawn_by=actor_id,
            withdrawal_reason=reason,
            updated_at=at,
            updated_by=actor_id,
        )

    def withdraw_draft_for_replacement(
        self,
        *,
        actor_id: str,
        reason: str,
        at: datetime,
    ) -> Self:
        """Freeze and withdraw a draft before an administrative replacement.

        This transition preserves partial draft evidence without pretending it
        satisfied the configured required-answer contract.
        """

        self._require_draft_edit(actor_id=actor_id, at=at)
        _require_text(reason, "Submission withdrawal reason")
        manifest = self._build_answer_manifest()
        return replace(
            self,
            status=SubmissionStatus.WITHDRAWN,
            answer_manifest_json=manifest,
            answer_schema_version=ANSWER_MANIFEST_SCHEMA_VERSION,
            answers_hash=hash_json(manifest),
            submitted_at=at,
            submitted_by=actor_id,
            withdrawn_at=at,
            withdrawn_by=actor_id,
            withdrawal_reason=reason,
            last_saved_at=at,
            updated_at=at,
            updated_by=actor_id,
        )

    def validate_predecessor(self, predecessor: Submission) -> None:
        """Recheck that predecessor identity and attempt number are monotonic."""

        if self.previous_submission_id != predecessor.submission_id:
            raise SubmissionRuleViolation(
                "Submission does not reference the supplied predecessor."
            )
        if self.attempt_number != predecessor.attempt_number + 1:
            raise SubmissionRuleViolation(
                "Submission attempt number must immediately follow its "
                "predecessor."
            )
        for field_name, current, previous in (
            ("session", self.session_id, predecessor.session_id),
            ("participant", self.participant_id, predecessor.participant_id),
            (
                "configuration",
                self.configuration_version_id,
                predecessor.configuration_version_id,
            ),
            (
                "scenario snapshot",
                self.scenario_snapshot_id,
                predecessor.scenario_snapshot_id,
            ),
            (
                "stakeholder group",
                self.session_stakeholder_group_id,
                predecessor.session_stakeholder_group_id,
            ),
        ):
            if current != previous:
                raise SubmissionRuleViolation(
                    f"Submission {field_name} differs from its predecessor."
                )

    def validate_against_configuration(
        self,
        configuration: SessionConfigurationVersion,
    ) -> None:
        """Recheck persisted answer targets at an application trust boundary."""

        self.validate_integrity()
        self._validate_configuration_binding(configuration)
        for answer in self.answers:
            answer.validate_for_question(
                _question_by_id(
                    configuration,
                    answer.question_definition_id,
                )
            )
        if self.is_finalized:
            expected_manifest = self._build_answer_manifest()
            if self.answer_manifest_json != expected_manifest:
                raise SubmissionRuleViolation(
                    "Final answer manifest does not match the answer rows."
                )

    def validate_integrity(self) -> None:
        """Verify answer and manifest hashes without changing lifecycle state."""

        for answer in self.answers:
            answer.validate_integrity()
        if self.answer_manifest_json is not None:
            _validate_json(
                self.answer_manifest_json,
                "Submission answer manifest",
            )
        if self.answers_hash is not None:
            _require_sha256(self.answers_hash, "Submission answers hash")
            if self.answer_manifest_json is None:
                raise SubmissionRuleViolation(
                    "Submission answers hash requires an answer manifest."
                )
            if hash_json(self.answer_manifest_json) != self.answers_hash:
                raise SubmissionRuleViolation(
                    "Answer manifest does not match answers_hash."
                )
            if self.answer_manifest_json != self._build_answer_manifest():
                raise SubmissionRuleViolation(
                    "Answer manifest does not match the current answer rows."
                )

    def _validate_identity(self) -> None:
        for field_name, value in (
            ("Submission ID", self.submission_id),
            ("Submission session ID", self.session_id),
            ("Submission participant ID", self.participant_id),
            (
                "Submission configuration version ID",
                self.configuration_version_id,
            ),
            ("Submission scenario snapshot ID", self.scenario_snapshot_id),
            (
                "Submission stakeholder group ID",
                self.session_stakeholder_group_id,
            ),
            ("Submission creator", self.created_by),
            ("Submission updater", self.updated_by),
        ):
            _require_text(value, field_name)
        for field_name, optional_value in (
            ("Previous submission ID", self.previous_submission_id),
            ("Submission submitter", self.submitted_by),
            ("Submission superseder", self.superseded_by),
            ("Submission withdrawer", self.withdrawn_by),
            ("Submission withdrawal reason", self.withdrawal_reason),
        ):
            _require_optional_text(optional_value, field_name)
        _require_positive_integer(self.attempt_number, "Submission attempt")
        _validate_json(self.client_metadata_json, "Submission client metadata")

    def _validate_attempt_lineage_shape(self) -> None:
        if self.attempt_number == 1 and self.previous_submission_id is not None:
            raise SubmissionRuleViolation(
                "First submission attempt cannot have a predecessor."
            )
        if self.attempt_number > 1 and self.previous_submission_id is None:
            raise SubmissionRuleViolation(
                "Later submission attempts require a predecessor."
            )
        if self.previous_submission_id == self.submission_id:
            raise SubmissionRuleViolation(
                "Submission cannot be its own predecessor."
            )

    def _validate_answers(self) -> None:
        answer_ids: set[str] = set()
        question_ids: set[str] = set()
        for answer in self.answers:
            if answer.submission_id != self.submission_id:
                raise SubmissionRuleViolation(
                    "Submission contains an answer owned by another attempt."
                )
            if answer.submission_answer_id in answer_ids:
                raise SubmissionRuleViolation(
                    "Submission answer IDs must be unique."
                )
            if answer.question_definition_id in question_ids:
                raise SubmissionRuleViolation(
                    "Submission may contain only one answer per question."
                )
            answer_ids.add(answer.submission_answer_id)
            question_ids.add(answer.question_definition_id)

    def _validate_schedule(self) -> None:
        timestamps = {
            "started_at": self.started_at,
            "last_saved_at": self.last_saved_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "submitted_at": self.submitted_at,
            "superseded_at": self.superseded_at,
            "withdrawn_at": self.withdrawn_at,
        }
        for field_name, value in timestamps.items():
            _require_aware_datetime(value, f"Submission {field_name}")
        if self.started_at < self.created_at:
            raise SubmissionRuleViolation(
                "Submission start cannot precede creation."
            )
        if self.last_saved_at < self.started_at:
            raise SubmissionRuleViolation(
                "Submission save cannot precede its start."
            )
        if self.updated_at < self.last_saved_at:
            raise SubmissionRuleViolation(
                "Submission update cannot precede its last save."
            )
        for answer in self.answers:
            if not self.started_at <= answer.answered_at <= self.last_saved_at:
                raise SubmissionRuleViolation(
                    "Answer time must fall within the submission save window."
                )
        if self.submitted_at is not None:
            _require_not_before(
                self.submitted_at,
                self.started_at,
                "Submission finalization time",
            )
            if self.submitted_at != self.last_saved_at:
                raise SubmissionRuleViolation(
                    "Finalized submission must freeze last_saved_at at its "
                    "submission time."
                )
        if self.superseded_at is not None:
            if self.submitted_at is None:
                raise SubmissionRuleViolation(
                    "Supersession requires prior submission."
                )
            _require_not_before(
                self.superseded_at,
                self.submitted_at,
                "Submission supersession time",
            )
        if self.withdrawn_at is not None:
            if self.submitted_at is None:
                raise SubmissionRuleViolation(
                    "Withdrawal requires prior submission."
                )
            _require_not_before(
                self.withdrawn_at,
                self.submitted_at,
                "Submission withdrawal time",
            )
        for field_name in ("submitted_at", "superseded_at", "withdrawn_at"):
            value = timestamps[field_name]
            if value is not None and value > self.updated_at:
                raise SubmissionRuleViolation(
                    f"Submission {field_name} cannot follow updated_at."
                )

    def _validate_lifecycle_state(self) -> None:
        finalization_metadata = (
            self.answer_manifest_json,
            self.answer_schema_version,
            self.answers_hash,
            self.submitted_at,
            self.submitted_by,
        )
        supersession_metadata = (self.superseded_at, self.superseded_by)
        withdrawal_metadata = (
            self.withdrawn_at,
            self.withdrawn_by,
            self.withdrawal_reason,
        )

        if self.status == SubmissionStatus.DRAFT:
            if any(value is not None for value in finalization_metadata):
                raise SubmissionRuleViolation(
                    "Draft submission cannot contain finalization metadata."
                )
            if any(value is not None for value in supersession_metadata):
                raise SubmissionRuleViolation(
                    "Draft submission cannot contain supersession metadata."
                )
            if any(value is not None for value in withdrawal_metadata):
                raise SubmissionRuleViolation(
                    "Draft submission cannot contain withdrawal metadata."
                )
            return

        if not all(value is not None for value in finalization_metadata):
            raise SubmissionRuleViolation(
                "Finalized submission requires complete finalization metadata."
            )
        if self.answer_schema_version != ANSWER_MANIFEST_SCHEMA_VERSION:
            raise SubmissionRuleViolation(
                "Unsupported submission answer manifest schema version."
            )

        if self.status == SubmissionStatus.SUBMITTED:
            if any(value is not None for value in supersession_metadata):
                raise SubmissionRuleViolation(
                    "Submitted attempt cannot contain supersession metadata."
                )
            if any(value is not None for value in withdrawal_metadata):
                raise SubmissionRuleViolation(
                    "Submitted attempt cannot contain withdrawal metadata."
                )
            return

        if self.status == SubmissionStatus.SUPERSEDED:
            if not all(value is not None for value in supersession_metadata):
                raise SubmissionRuleViolation(
                    "Superseded attempt requires complete supersession metadata."
                )
            if any(value is not None for value in withdrawal_metadata):
                raise SubmissionRuleViolation(
                    "Superseded attempt cannot contain withdrawal metadata."
                )
            return

        if self.status == SubmissionStatus.WITHDRAWN:
            if not all(value is not None for value in withdrawal_metadata):
                raise SubmissionRuleViolation(
                    "Withdrawn attempt requires complete withdrawal metadata."
                )
            if any(value is not None for value in supersession_metadata):
                raise SubmissionRuleViolation(
                    "Withdrawn attempt cannot contain supersession metadata."
                )
            return

        raise SubmissionRuleViolation(
            f"Unsupported submission status: {self.status!r}."
        )

    def _require_draft_edit(self, *, actor_id: str, at: datetime) -> None:
        _require_actor(actor_id)
        _require_aware_datetime(at, "Submission edit time")
        if self.status != SubmissionStatus.DRAFT:
            raise SubmissionRuleViolation(
                "Only a draft submission can be edited."
            )
        _require_not_before(at, self.updated_at, "Submission edit time")

    def _validate_configuration_binding(
        self,
        configuration: SessionConfigurationVersion,
    ) -> None:
        for field_name, actual, expected in (
            ("session", self.session_id, configuration.session_id),
            (
                "configuration",
                self.configuration_version_id,
                configuration.configuration_version_id,
            ),
            (
                "scenario snapshot",
                self.scenario_snapshot_id,
                configuration.scenario_snapshot_id,
            ),
            (
                "response format",
                self.response_format,
                configuration.response_format,
            ),
            (
                "response target type",
                self.response_target_type,
                configuration.response_target_type,
            ),
        ):
            if actual != expected:
                raise SubmissionRuleViolation(
                    f"Submission {field_name} does not match its configuration."
                )
        # Attempt-count and resubmission policy are creation-time rules in
        # ``start``. Structural validation must continue to accept an audited
        # administrative replacement that explicitly overrode those policies.

    def _validate_answer_set(
        self,
        configuration: SessionConfigurationVersion,
    ) -> None:
        if not self.answers:
            raise SubmissionRuleViolation(
                "A submission must contain at least one answer."
            )
        questions = {
            question.question_definition_id: question
            for question in configuration.question_definitions
        }
        for answer in self.answers:
            question = questions.get(answer.question_definition_id)
            if question is None:
                raise SubmissionRuleViolation(
                    "Submission contains an answer for an unknown question."
                )
            answer.validate_for_question(question)

        answered_ids = {
            answer.question_definition_id for answer in self.answers
        }
        if not configuration.allow_incomplete_submission:
            missing_required = [
                question.question_key
                for question in configuration.question_definitions
                if question.required
                and question.question_definition_id not in answered_ids
            ]
            if missing_required:
                raise SubmissionRuleViolation(
                    "Submission is missing required questions: "
                    f"{sorted(missing_required)!r}."
                )

        if self.response_format == ResponseFormat.DIRECT_RANKING:
            rank_values = [
                answer.rank_value
                for answer in self.answers
                if answer.rank_value is not None
            ]
            if len(rank_values) != len(set(rank_values)):
                raise SubmissionRuleViolation(
                    "Direct ranking answers cannot contain duplicate ranks."
                )
            if not configuration.allow_incomplete_submission:
                expected_ranks = list(range(1, len(rank_values) + 1))
                if sorted(rank_values) != expected_ranks:
                    raise SubmissionRuleViolation(
                        "Complete direct ranking must be a contiguous "
                        "permutation starting at one."
                    )

    def _build_answer_manifest(self) -> dict[str, object]:
        answer_entries = [
            {
                "question_definition_id": answer.question_definition_id,
                "value_schema_version": answer.value_schema_version,
                "raw_value_json": deepcopy(dict(answer.raw_value_json)),
                "raw_value_hash": answer.raw_value_hash,
                "selected_scale_value_id": (
                    answer.selected_scale_value_id
                ),
                "numeric_value": (
                    str(answer.numeric_value)
                    if answer.numeric_value is not None
                    else None
                ),
                "rank_value": answer.rank_value,
            }
            for answer in sorted(
                self.answers,
                key=lambda candidate: candidate.question_definition_id,
            )
        ]
        return {
            "schema_version": ANSWER_MANIFEST_SCHEMA_VERSION,
            "configuration_version_id": self.configuration_version_id,
            "response_format": self.response_format.value,
            "response_target_type": self.response_target_type.value,
            "answers": answer_entries,
        }


def _question_by_id(
    configuration: SessionConfigurationVersion,
    question_definition_id: str,
) -> ResponseQuestionDefinition:
    question = next(
        (
            candidate
            for candidate in configuration.question_definitions
            if candidate.question_definition_id == question_definition_id
        ),
        None,
    )
    if question is None:
        raise SubmissionRuleViolation(
            "Answer references a question outside the submission configuration."
        )
    return question


def _validate_resubmission_predecessor(
    predecessor: Submission,
    *,
    participant: Participant,
    configuration: SessionConfigurationVersion,
    administrative_override: bool = False,
) -> None:
    predecessor.validate_integrity()
    if predecessor.status != SubmissionStatus.SUBMITTED and not (
        administrative_override
        and predecessor.status in {
            SubmissionStatus.WITHDRAWN,
            SubmissionStatus.SUPERSEDED,
        }
    ):
        raise SubmissionRuleViolation(
            "A resubmission must follow the current submitted attempt."
        )
    for field_name, actual, expected in (
        ("session", predecessor.session_id, participant.session_id),
        ("participant", predecessor.participant_id, participant.participant_id),
        (
            "configuration",
            predecessor.configuration_version_id,
            configuration.configuration_version_id,
        ),
        (
            "scenario snapshot",
            predecessor.scenario_snapshot_id,
            configuration.scenario_snapshot_id,
        ),
        (
            "stakeholder group",
            predecessor.session_stakeholder_group_id,
            participant.session_stakeholder_group_id,
        ),
    ):
        if actual != expected:
            raise SubmissionRuleViolation(
                f"Previous submission {field_name} does not match."
            )


def _typed_values_from_raw(
    raw_value_json: JsonObject,
) -> tuple[str | None, Decimal | None, int | None]:
    _validate_json(raw_value_json, "Answer raw value")
    present_keys = _VALUE_KEYS.intersection(raw_value_json)
    if len(present_keys) != 1:
        raise SubmissionRuleViolation(
            "Answer raw value must contain exactly one of "
            "selected_scale_value_id, numeric_value, or rank_value."
        )
    value_key = next(iter(present_keys))
    value = raw_value_json[value_key]
    if value_key == "selected_scale_value_id":
        if not isinstance(value, str):
            raise SubmissionRuleViolation(
                "selected_scale_value_id must be text."
            )
        _require_text(value, "Selected scale value ID")
        return value, None, None
    if value_key == "rank_value":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SubmissionRuleViolation("rank_value must be an integer.")
        _require_positive_integer(value, "Answer rank")
        return None, None, value
    if isinstance(value, bool) or not isinstance(
        value,
        (int, float, Decimal, str),
    ):
        raise SubmissionRuleViolation(
            "numeric_value must be a finite decimal-compatible value."
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise SubmissionRuleViolation("numeric_value must be finite.")
    try:
        numeric_value = Decimal(str(value))
    except InvalidOperation as error:
        raise SubmissionRuleViolation(
            "numeric_value must be decimal-compatible."
        ) from error
    if not numeric_value.is_finite():
        raise SubmissionRuleViolation("numeric_value must be finite.")
    return None, numeric_value, None


def _equivalent_value(raw_value: object, typed_value: object) -> bool:
    if isinstance(typed_value, Decimal):
        if isinstance(raw_value, bool) or not isinstance(
            raw_value,
            (int, float, Decimal, str),
        ):
            return False
        try:
            return Decimal(str(raw_value)) == typed_value
        except InvalidOperation:
            return False
    return raw_value == typed_value
