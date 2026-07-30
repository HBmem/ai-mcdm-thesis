"""Bidirectional mappings for submissions and their answer evidence.

Submission comments are intentionally not mapped here yet because the domain
does not currently define a comment entity. The submission aggregate owns its
answer rows, while comment moderation has an independent lifecycle.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping

from poli_insight.core.time import as_utc
from poli_insight.domain.enum import (
    ResponseFormat,
    ResponseTargetType,
    SubmissionStatus,
)
from poli_insight.domain.submission import Submission, SubmissionAnswer
from poli_insight.infrastructure.database.models.submission import (
    SubmissionAnswerRow,
    SubmissionRow,
)


def _required_utc(value: datetime, field_name: str) -> datetime:
    utc_value = as_utc(value)
    if utc_value is None:
        raise ValueError(f"Persisted submission is missing {field_name}.")
    return utc_value


def _optional_utc(value: datetime | None) -> datetime | None:
    return as_utc(value) if value is not None else None


def _optional_id(value: object | None) -> str | None:
    return str(value) if value is not None else None


def _copy_json(value: Mapping[str, Any]) -> dict[str, Any]:
    """Detach nested JSON values from the source object being mapped."""

    return deepcopy(dict(value))


def _optional_json(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    return _copy_json(value) if value is not None else None


def _exact_numeric_value(row: SubmissionAnswerRow) -> Decimal | None:
    """Reconstruct the authored Decimal representation from hashed JSON.

    Fixed-scale SQL ``Numeric`` columns pad trailing zeros. The raw answer is
    the immutable evidence and retains the representation used by the
    canonical manifest, while the typed column remains an independently
    checked query convenience value.
    """

    if row.numeric_value is None:
        return None

    persisted_value = Decimal(row.numeric_value)
    raw_value = row.raw_value_json.get("numeric_value")
    try:
        exact_value = Decimal(str(raw_value))
    except (ArithmeticError, ValueError):
        return persisted_value
    if exact_value != persisted_value:
        raise ValueError(
            "Persisted numeric answer does not match its raw value."
        )
    return exact_value


def submission_answer_to_row(
    answer: SubmissionAnswer,
) -> SubmissionAnswerRow:
    """Map one immutable answer value to its queryable persistence row."""

    return SubmissionAnswerRow(
        submission_answer_id=answer.submission_answer_id,
        submission_id=answer.submission_id,
        question_definition_id=answer.question_definition_id,
        raw_value_json=_copy_json(answer.raw_value_json),
        value_schema_version=answer.value_schema_version,
        raw_value_hash=answer.raw_value_hash,
        selected_scale_value_id=answer.selected_scale_value_id,
        numeric_value=answer.numeric_value,
        rank_value=answer.rank_value,
        answered_at=answer.answered_at,
        response_time_ms=answer.response_time_ms,
    )


def submission_answer_to_domain(
    row: SubmissionAnswerRow,
) -> SubmissionAnswer:
    """Reconstruct a detached answer while preserving exact numeric values."""

    return SubmissionAnswer(
        submission_answer_id=str(row.submission_answer_id),
        submission_id=str(row.submission_id),
        question_definition_id=str(row.question_definition_id),
        raw_value_json=_copy_json(row.raw_value_json),
        value_schema_version=row.value_schema_version,
        raw_value_hash=row.raw_value_hash,
        selected_scale_value_id=_optional_id(row.selected_scale_value_id),
        numeric_value=_exact_numeric_value(row),
        rank_value=row.rank_value,
        answered_at=_required_utc(row.answered_at, "answer answered_at"),
        response_time_ms=row.response_time_ms,
    )


def apply_submission_answer(
    row: SubmissionAnswerRow,
    answer: SubmissionAnswer,
) -> None:
    """Apply a replacement draft answer without changing row identity."""

    if str(row.submission_answer_id) != answer.submission_answer_id:
        raise ValueError("Cannot map answer state to another answer row.")
    if str(row.submission_id) != answer.submission_id:
        raise ValueError("An answer's submission cannot be replaced.")
    if str(row.question_definition_id) != answer.question_definition_id:
        raise ValueError("An answer's question cannot be replaced.")

    row.raw_value_json = _copy_json(answer.raw_value_json)
    row.value_schema_version = answer.value_schema_version
    row.raw_value_hash = answer.raw_value_hash
    row.selected_scale_value_id = answer.selected_scale_value_id
    row.numeric_value = answer.numeric_value
    row.rank_value = answer.rank_value
    row.answered_at = answer.answered_at
    row.response_time_ms = answer.response_time_ms


def submission_to_row(submission: Submission) -> SubmissionRow:
    """Map a complete submission aggregate to a new ORM row graph."""

    return SubmissionRow(
        submission_id=submission.submission_id,
        session_id=submission.session_id,
        participant_id=submission.participant_id,
        configuration_version_id=submission.configuration_version_id,
        scenario_snapshot_id=submission.scenario_snapshot_id,
        session_stakeholder_group_id=(
            submission.session_stakeholder_group_id
        ),
        attempt_number=submission.attempt_number,
        previous_submission_id=submission.previous_submission_id,
        status=submission.status.value,
        response_format=submission.response_format.value,
        response_target_type=submission.response_target_type.value,
        answer_manifest_json=_optional_json(
            submission.answer_manifest_json
        ),
        answer_schema_version=submission.answer_schema_version,
        answers_hash=submission.answers_hash,
        started_at=submission.started_at,
        last_saved_at=submission.last_saved_at,
        submitted_at=submission.submitted_at,
        submitted_by=submission.submitted_by,
        superseded_at=submission.superseded_at,
        superseded_by=submission.superseded_by,
        withdrawn_at=submission.withdrawn_at,
        withdrawn_by=submission.withdrawn_by,
        withdrawal_reason=submission.withdrawal_reason,
        client_metadata_json=_copy_json(submission.client_metadata_json),
        created_at=submission.created_at,
        created_by=submission.created_by,
        updated_at=submission.updated_at,
        updated_by=submission.updated_by,
        answers=[
            submission_answer_to_row(answer)
            for answer in sorted(
                submission.answers,
                key=lambda item: (
                    item.question_definition_id,
                    item.submission_answer_id,
                ),
            )
        ],
    )


def submission_to_domain(row: SubmissionRow) -> Submission:
    """Reconstruct a detached submission with immutable ordered answers."""

    return Submission(
        submission_id=str(row.submission_id),
        session_id=str(row.session_id),
        participant_id=str(row.participant_id),
        configuration_version_id=str(row.configuration_version_id),
        scenario_snapshot_id=str(row.scenario_snapshot_id),
        session_stakeholder_group_id=str(
            row.session_stakeholder_group_id
        ),
        attempt_number=row.attempt_number,
        previous_submission_id=_optional_id(row.previous_submission_id),
        status=SubmissionStatus(row.status),
        response_format=ResponseFormat(row.response_format),
        response_target_type=ResponseTargetType(row.response_target_type),
        answers=tuple(
            submission_answer_to_domain(answer_row)
            for answer_row in sorted(
                row.answers,
                key=lambda item: (
                    str(item.question_definition_id),
                    str(item.submission_answer_id),
                ),
            )
        ),
        answer_manifest_json=_optional_json(row.answer_manifest_json),
        answer_schema_version=row.answer_schema_version,
        answers_hash=row.answers_hash,
        started_at=_required_utc(row.started_at, "started_at"),
        last_saved_at=_required_utc(row.last_saved_at, "last_saved_at"),
        submitted_at=_optional_utc(row.submitted_at),
        submitted_by=row.submitted_by,
        superseded_at=_optional_utc(row.superseded_at),
        superseded_by=row.superseded_by,
        withdrawn_at=_optional_utc(row.withdrawn_at),
        withdrawn_by=row.withdrawn_by,
        withdrawal_reason=row.withdrawal_reason,
        client_metadata_json=_copy_json(row.client_metadata_json),
        created_at=_required_utc(row.created_at, "created_at"),
        created_by=row.created_by,
        updated_at=_required_utc(row.updated_at, "updated_at"),
        updated_by=row.updated_by,
    )


def apply_submission_aggregate(
    row: SubmissionRow,
    submission: Submission,
) -> tuple[SubmissionAnswerRow, ...]:
    """Apply aggregate state and return draft answer rows to delete.

    The repository must explicitly delete returned rows before flushing. This
    is restricted to persisted drafts; finalized evidence is compared but
    never rewritten. The function deliberately leaves the row's comment
    collection untouched because comments have a separate lifecycle.
    """

    _validate_root_identity(row, submission)
    persisted_status = SubmissionStatus(row.status)
    _validate_status_transition(persisted_status, submission.status)

    if persisted_status is SubmissionStatus.DRAFT:
        removed_answers = _synchronize_draft_answers(row, submission)
    else:
        _require_unchanged_finalized_evidence(row, submission)
        removed_answers = ()

    row.status = submission.status.value
    row.answer_manifest_json = _optional_json(
        submission.answer_manifest_json
    )
    row.answer_schema_version = submission.answer_schema_version
    row.answers_hash = submission.answers_hash
    row.last_saved_at = submission.last_saved_at
    row.submitted_at = submission.submitted_at
    row.submitted_by = submission.submitted_by
    row.superseded_at = submission.superseded_at
    row.superseded_by = submission.superseded_by
    row.withdrawn_at = submission.withdrawn_at
    row.withdrawn_by = submission.withdrawn_by
    row.withdrawal_reason = submission.withdrawal_reason
    row.updated_at = submission.updated_at
    row.updated_by = submission.updated_by
    return removed_answers


def _synchronize_draft_answers(
    row: SubmissionRow,
    submission: Submission,
) -> tuple[SubmissionAnswerRow, ...]:
    existing_by_id = {
        str(answer_row.submission_answer_id): answer_row
        for answer_row in row.answers
    }
    existing_by_question = {
        str(answer_row.question_definition_id): answer_row
        for answer_row in row.answers
    }
    desired_ids = {
        answer.submission_answer_id for answer in submission.answers
    }
    removed = tuple(
        answer_row
        for answer_id, answer_row in existing_by_id.items()
        if answer_id not in desired_ids
    )

    synchronized: list[SubmissionAnswerRow] = []
    for answer in sorted(
        submission.answers,
        key=lambda item: (
            item.question_definition_id,
            item.submission_answer_id,
        ),
    ):
        answer_row = existing_by_id.get(answer.submission_answer_id)
        if answer_row is None:
            previous_question_row = existing_by_question.get(
                answer.question_definition_id
            )
            if previous_question_row is not None:
                raise ValueError(
                    "Editing a draft answer must preserve its answer identity."
                )
            answer_row = submission_answer_to_row(answer)
        else:
            apply_submission_answer(answer_row, answer)
        synchronized.append(answer_row)
    row.answers = synchronized
    return removed


def _validate_root_identity(
    row: SubmissionRow,
    submission: Submission,
) -> None:
    immutable_fields = (
        ("submission ID", str(row.submission_id), submission.submission_id),
        ("session", str(row.session_id), submission.session_id),
        ("participant", str(row.participant_id), submission.participant_id),
        (
            "configuration",
            str(row.configuration_version_id),
            submission.configuration_version_id,
        ),
        (
            "scenario snapshot",
            str(row.scenario_snapshot_id),
            submission.scenario_snapshot_id,
        ),
        (
            "stakeholder group",
            str(row.session_stakeholder_group_id),
            submission.session_stakeholder_group_id,
        ),
        ("attempt number", row.attempt_number, submission.attempt_number),
        (
            "previous submission",
            _optional_id(row.previous_submission_id),
            submission.previous_submission_id,
        ),
        (
            "response format",
            row.response_format,
            submission.response_format.value,
        ),
        (
            "response target type",
            row.response_target_type,
            submission.response_target_type.value,
        ),
        (
            "started_at",
            _required_utc(row.started_at, "started_at"),
            as_utc(submission.started_at),
        ),
        (
            "created_at",
            _required_utc(row.created_at, "created_at"),
            as_utc(submission.created_at),
        ),
        ("created_by", row.created_by, submission.created_by),
        (
            "client metadata",
            _copy_json(row.client_metadata_json),
            _copy_json(submission.client_metadata_json),
        ),
    )
    for field_name, persisted, replacement in immutable_fields:
        if persisted != replacement:
            raise ValueError(
                f"Submission {field_name} cannot be replaced during save."
            )


def _validate_status_transition(
    persisted: SubmissionStatus,
    replacement: SubmissionStatus,
) -> None:
    allowed = {
        SubmissionStatus.DRAFT: {
            SubmissionStatus.DRAFT,
            SubmissionStatus.SUBMITTED,
        },
        SubmissionStatus.SUBMITTED: {
            SubmissionStatus.SUBMITTED,
            SubmissionStatus.SUPERSEDED,
            SubmissionStatus.WITHDRAWN,
        },
        SubmissionStatus.SUPERSEDED: {SubmissionStatus.SUPERSEDED},
        SubmissionStatus.WITHDRAWN: {SubmissionStatus.WITHDRAWN},
    }
    if replacement not in allowed[persisted]:
        raise ValueError(
            f"Invalid persisted submission transition: "
            f"{persisted.value} -> {replacement.value}."
        )


def _require_unchanged_finalized_evidence(
    row: SubmissionRow,
    submission: Submission,
) -> None:
    persisted_answers = tuple(
        submission_answer_to_domain(answer_row)
        for answer_row in sorted(
            row.answers,
            key=lambda item: (
                str(item.question_definition_id),
                str(item.submission_answer_id),
            ),
        )
    )
    replacement_answers = tuple(
        sorted(
            submission.answers,
            key=lambda item: (
                item.question_definition_id,
                item.submission_answer_id,
            ),
        )
    )
    if persisted_answers != replacement_answers:
        raise ValueError("Finalized submission answers cannot be rewritten.")

    frozen_fields = (
        (
            "answer manifest",
            _optional_json(row.answer_manifest_json),
            _optional_json(submission.answer_manifest_json),
        ),
        (
            "answer schema version",
            row.answer_schema_version,
            submission.answer_schema_version,
        ),
        ("answers hash", row.answers_hash, submission.answers_hash),
        (
            "submitted_at",
            _optional_utc(row.submitted_at),
            _optional_utc(submission.submitted_at),
        ),
        ("submitted_by", row.submitted_by, submission.submitted_by),
        (
            "last_saved_at",
            _required_utc(row.last_saved_at, "last_saved_at"),
            as_utc(submission.last_saved_at),
        ),
    )
    for field_name, persisted, replacement in frozen_fields:
        if persisted != replacement:
            raise ValueError(
                f"Finalized submission {field_name} cannot be rewritten."
            )
