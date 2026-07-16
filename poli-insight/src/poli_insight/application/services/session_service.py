from __future__ import annotations

import uuid

from collections.abc import Callable
from datetime import UTC, datetime

from poli_insight.application.dto import CreateSessionCommand
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.enums import SessionStatus
from poli_insight.domain.sessions import (
    SessionScenario,
    SessionStakeholderGroup,
)

class CreateSessionError(ValueError):
    pass

UnitOfWorkFactory = Callable[[], UnitOfWork]

class SessionService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def create_session(self, command: CreateSessionCommand) -> str:
        title = command.title.strip()

        if not title:
            raise CreateSessionError("Session title is required.")

        if (
            command.start_at is not None
            and command.end_at is not None
            and command.end_at <= command.start_at
        ):
            raise CreateSessionError(
                "Session end time must be later than its start time."
            )

        if command.require_access_code and not command.access_code_type:
            raise CreateSessionError(
                "Access-code type is required when access codes are enabled."
            )

        weights = dict(command.voting_power)
        expected_group_ids = {
            group["id"]
            for group in command.scenario.stakeholder_groups
        }

        if set(weights) != expected_group_ids:
            raise CreateSessionError(
                "Voting power must be provided for every stakeholder group."
            )

        if any(weight < 0 for weight in weights.values()):
            raise CreateSessionError(
                "Voting power cannot be negative."
            )

        total_weight = sum(weights.values())

        if total_weight <= 0:
            raise CreateSessionError(
                "Total voting power must be greater than zero."
            )

        now = datetime.now(UTC)
        session_id = _new_id("session")

        session = SessionScenario(
            session_id=session_id,
            scenario_id=command.scenario.scenario_id,
            scenario_version=command.scenario.scenario_version,
            title=title,
            description=command.description,
            admin_notes=command.admin_notes,
            status=SessionStatus.DRAFT,
            visibility=command.visibility,
            participation_method=command.participation_method,
            preference_scale=command.preference_scale,
            weighting_method=command.weighting_method,
            ranking_method=command.ranking_method,
            aggregation_method=command.aggregation_method,
            require_access_code=command.require_access_code,
            access_code_type=command.access_code_type,
            allow_resubmissions=command.allow_resubmissions,
            start_at=command.start_at,
            end_at=command.end_at,
            opened_at=None,
            closed_at=None,
            archived_at=None,
            created_at=now,
            created_by=command.actor_id,
            updated_at=now,
            updated_by=command.actor_id,
        )

        stakeholder_groups = [
            SessionStakeholderGroup(
                session_id=session_id,
                stakeholder_group_id=group["id"],
                name=group["label"],
                default_voting_power=float(
                    group.get("default_group_voting_power", 1.0)
                ),
                current_voting_power=weights[group["id"]],
                normalized_voting_power=(
                    weights[group["id"]] / total_weight
                ),
                created_at=now,
                updated_at=now,
                updated_by=command.actor_id,
                is_active=True,
            )
            for group in command.scenario.stakeholder_groups
        ]

        with self._unit_of_work_factory() as unit_of_work:
            unit_of_work.scenarios.ensure_snapshot(command.scenario)
            unit_of_work.sessions.add(session, stakeholder_groups)
            unit_of_work.commit()

        return session_id
    
def _new_id(prefix: str) -> str:
    """Create a stable, unique ID for prototype records."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"