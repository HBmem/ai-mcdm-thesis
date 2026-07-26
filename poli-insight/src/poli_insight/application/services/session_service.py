from __future__ import annotations

import uuid

from collections.abc import Callable
from datetime import UTC, datetime

from poli_insight.domain.sessions import (
    Session,
    SessionStakeholderGroup,
)

from poli_insight.application.dto import CreateSessionCommand, UpdateSessionCommand
from poli_insight.application.ports.unit_of_work import UnitOfWork
from poli_insight.domain.enums import SessionStatus

from poli_insight.application.session_queries import (
    SessionFilters,
    SessionPage,
    SessionTableItem,
    SessionTablePage,
)
from poli_insight.application.services.scenario_service import ScenarioSnapshotNotFoundError, SessionDetails

class CreateSessionError(ValueError):
    pass

class SessionNotFoundError(LookupError):
    pass

class SessionScenarioNotFoundError(LookupError):
    pass

UnitOfWorkFactory = Callable[[], UnitOfWork]

class SessionService:
    def __init__(self, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    def create_session(
        self,
        command: CreateSessionCommand,
    ) -> str:
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

        session = Session(
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

    def get_session(
        self,
        session_id: str,
    ) -> Session:
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.get(session_id)

        if session is None:
            raise SessionNotFoundError(
                f"Session {session_id!r} was not found."
            )

        return session
    
    def get_session_details(
        self,
        session_id: str,
    ) -> SessionDetails:
        with self._unit_of_work_factory() as unit_of_work:
            session = unit_of_work.sessions.get(session_id)

            if session is None:
                raise SessionScenarioNotFoundError(
                    f"Session {session_id!r} was not found."
                )

            snapshot = unit_of_work.scenarios.get_snapshot(
                session.scenario_id,
                session.scenario_version,
            )

            if snapshot is None:
                raise ScenarioSnapshotNotFoundError(
                    f"Snapshot for session {session_id!r} "
                    f"was not found."
                )

            return SessionDetails(
                snapshot=snapshot,
                session=session,
            )
        
    @staticmethod
    def _get_required_session(
        unit_of_work: UnitOfWork,
        session_id: str,
    ) -> Session:
        session = unit_of_work.sessions.get(session_id)

        if session is None:
            raise SessionScenarioNotFoundError(
                f"Session {session_id!r} was not found."
            )

        return session
    
    def open_session(
        self,
        session_id: str,
        *,
        actor_id: str,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            session = self._get_required_session(
                unit_of_work,
                session_id,
            )

            session.open(actor_id=actor_id)

            unit_of_work.sessions.save(session)
            unit_of_work.commit()

    def close_session(
        self,
        session_id: str,
        *,
        actor_id: str,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            session = self._get_required_session(
                unit_of_work,
                session_id,
            )

            session.close(actor_id=actor_id)

            unit_of_work.sessions.save(session)
            unit_of_work.commit()

    def archive_session(
        self,
        session_id: str,
        *,
        actor_id: str,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            session = self._get_required_session(
                unit_of_work,
                session_id,
            )

            session.archive(actor_id=actor_id)

            unit_of_work.sessions.save(session)
            unit_of_work.commit()


    def update_session(
        self,
        command: UpdateSessionCommand,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            session = self._get_required_session(
                unit_of_work,
                command.session_id,
            )

            session.update_details(
                title=command.title,
                description=command.description,
                admin_notes=command.admin_notes,
                visibility=command.visibility,
                end_at=command.end_at,
                actor_id=command.actor_id,
            )

            unit_of_work.sessions.save(session)
            unit_of_work.commit()

    def delete_session(
        self,
        session_id: str,
    ) -> None:
        with self._unit_of_work_factory() as unit_of_work:
            session = self._get_required_session(
                unit_of_work,
                session_id,
            )

            if session.status not in {
                SessionStatus.DRAFT,
            }:
                raise ValueError(
                    "Only Draft sessions can be deleted."
                )

            deleted = unit_of_work.sessions.delete(
                session_id
            )

            if not deleted:
                raise SessionScenarioNotFoundError(
                    f"Session {session_id!r} was not found."
                )

            unit_of_work.commit()

    def list_sessions(
        self,
        filters: SessionFilters,
        *,
        page: int = 1,
        page_size: int = 10,
    ) -> SessionPage:
        if page < 1:
            raise ValueError("Page must be at least 1.")

        if not 1 <= page_size <= 100:
            raise ValueError(
                "Page size must be between 1 and 100."
            )

        with self._unit_of_work_factory() as unit_of_work:
            return unit_of_work.sessions.list_filtered(
                filters,
                page=page,
                page_size=page_size,
            )

    def list_session_table(
        self,
        filters: SessionFilters,
        *,
        page: int = 1,
        page_size: int = 10,
    ) -> SessionTablePage:
        if page < 1:
            raise ValueError("Page must be at least 1.")

        if not 1 <= page_size <= 100:
            raise ValueError(
                "Page size must be between 1 and 100."
            )

        with self._unit_of_work_factory() as unit_of_work:
            session_page = (
                unit_of_work.sessions.list_filtered(
                    filters,
                    page=page,
                    page_size=page_size,
                )
            )

            snapshot_identities = {
                (
                    session.scenario_id,
                    session.scenario_version,
                )
                for session in session_page.items
            }

            snapshots = unit_of_work.scenarios.get_many(
                snapshot_identities
            )

            items = tuple(
                SessionTableItem(
                    session=session,
                    snapshot=snapshots.get(
                        (
                            session.scenario_id,
                            session.scenario_version,
                        )
                    ),
                )
                for session in session_page.items
            )

            return SessionTablePage(
                items=items,
                total=session_page.total,
                page=session_page.page,
                page_size=session_page.page_size,
            )
    
def _new_id(prefix: str) -> str:
    """Create a stable, unique ID for prototype records."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"