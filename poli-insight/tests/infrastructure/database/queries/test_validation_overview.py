from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from poli_insight.application.queries.page_queries import (
    ProcessingQueueMode,
    SessionDateField,
    SessionSearchFilters,
)
from poli_insight.domain.enum import AlgorithmRole, RunStatus, SessionStatus
from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.json_codec import json_to_storage
from poli_insight.infrastructure.database.models import audit as audit_models
from poli_insight.infrastructure.database.models import (
    operations as operations_models,
)
from poli_insight.infrastructure.database.models import (
    participation as participation_models,
)
from poli_insight.infrastructure.database.models import (
    processing as processing_models,
)
from poli_insight.infrastructure.database.models import scenario as scenario_models
from poli_insight.infrastructure.database.models import session as session_models
from poli_insight.infrastructure.database.models import (
    submission as submission_models,
)
from poli_insight.infrastructure.database.models import (
    validation as validation_models,
)
from poli_insight.infrastructure.database.models.operations import (
    SubmissionReviewDecisionRow,
)
from poli_insight.infrastructure.database.models.participation import ParticipantRow
from poli_insight.infrastructure.database.models.processing import (
    ProcessingMatrixRow,
    ProcessingRunRow,
)
from poli_insight.infrastructure.database.models.ranking import (
    RankingResultRow,
    RankingRunRow,
)
from poli_insight.infrastructure.database.models.scenario import (
    ScenarioDefinitionRow,
    ScenarioSnapshotRow,
)
from poli_insight.infrastructure.database.models.session import (
    SessionConfigurationVersionRow,
    SessionRow,
    SessionStakeholderGroupRow,
)
from poli_insight.infrastructure.database.models.submission import SubmissionRow
from poli_insight.infrastructure.database.models.validation import (
    SubmissionValidationRow,
)
from poli_insight.infrastructure.database.queries.page_queries import (
    SqlAlchemyPageQueries,
)

NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


class SessionValidationOverviewQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        # These imports register every referenced table before create_all.
        registered_modules = (
            audit_models,
            operations_models,
            participation_models,
            processing_models,
            scenario_models,
            session_models,
            submission_models,
            validation_models,
        )
        self.assertTrue(all(module is not None for module in registered_modules))
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.session_factory = sessionmaker(
            bind=engine,
            class_=DatabaseSession,
            expire_on_commit=False,
            autoflush=False,
        )
        self.queries = SqlAlchemyPageQueries(self.session_factory)
        self.session_id = uuid4()
        self.configuration_id = uuid4()
        self.snapshot_id = uuid4()
        self.algorithm_id = uuid4()
        self.group_id = uuid4()
        with self.session_factory() as database_session:
            definition_id = uuid4()
            database_session.add(
                ScenarioDefinitionRow(
                    scenario_definition_id=definition_id,
                    scenario_key="validation-scenario",
                    title="Validation scenario",
                    domain="Public policy",
                    description="Validation fixture.",
                    status="active",
                    created_at=NOW - timedelta(days=4),
                    created_by="admin",
                    updated_at=NOW,
                    updated_by="admin",
                )
            )
            database_session.add(
                ScenarioSnapshotRow(
                    scenario_snapshot_id=self.snapshot_id,
                    scenario_definition_id=definition_id,
                    declared_version="1.0",
                    scenario_type="standard",
                    schema_version=1,
                    status="ready",
                    title="Validation scenario",
                    domain="Public policy",
                    summary="Validation fixture.",
                    policy_question="Which option?",
                    manifest_json={"schema_version": 1},
                    manifest_schema_version=1,
                    root_hash="a" * 64,
                    materialized_input_hash="b" * 64,
                    source_uri="urn:test:validation",
                    importer_version="test/1",
                    import_environment_json={},
                    created_at=NOW - timedelta(days=4),
                    created_by="admin",
                    ready_at=NOW - timedelta(days=4),
                )
            )
            database_session.add(
                SessionRow(
                    session_id=self.session_id,
                    scenario_snapshot_id=self.snapshot_id,
                    public_slug="validation-overview",
                    title="Validation overview",
                    description=None,
                    admin_notes=None,
                    status="closed",
                    discoverability="unlisted",
                    enrollment_mode="open",
                    access_code_mode="none",
                    identity_policy="pseudonymous",
                    stakeholder_selection_mode="self_select",
                    opens_at=NOW - timedelta(days=2),
                    closes_at=NOW - timedelta(days=1),
                    opened_at=NOW - timedelta(days=2),
                    paused_at=None,
                    closed_at=NOW - timedelta(days=1),
                    canceled_at=None,
                    archived_at=None,
                    active_configuration_version_id=self.configuration_id,
                    created_at=NOW - timedelta(days=3),
                    created_by="admin",
                    updated_at=NOW - timedelta(days=1),
                    updated_by="admin",
                )
            )
            database_session.add(
                SessionConfigurationVersionRow(
                    configuration_version_id=self.configuration_id,
                    session_id=self.session_id,
                    version_number=1,
                    scenario_snapshot_id=self.snapshot_id,
                    response_format="direct_rating",
                    response_target_type="criterion",
                    scale_id=uuid4(),
                    allow_resubmissions=True,
                    max_submissions_per_participant=3,
                    allow_incomplete_submission=False,
                    minimum_valid_submissions=1,
                    missing_group_policy="fail",
                    required_group_policy_json={},
                    consistency_threshold=Decimal("0.1"),
                    configuration_json={},
                    schema_version=1,
                    config_hash="c" * 64,
                    allocation_total_units=100,
                    created_at=NOW - timedelta(days=3),
                    created_by="admin",
                    activated_at=NOW - timedelta(days=2),
                    activated_by="admin",
                )
            )
            database_session.add(
                SessionStakeholderGroupRow(
                    session_stakeholder_group_id=self.group_id,
                    configuration_version_id=self.configuration_id,
                    group_key="community",
                    name="Community",
                    description="Community participants",
                    allocation_units=60,
                    display_order=0,
                    is_active=True,
                    within_group_algorithm_config_id=None,
                    created_at=NOW - timedelta(days=3),
                    created_by="admin",
                )
            )
            database_session.commit()

    def test_counts_only_current_submitted_and_exact_reviews(self) -> None:
        statuses = (
            None,
            "pending",
            "running",
            "valid",
            "valid_with_warnings",
            "valid_with_warnings",
            "invalid",
            "error",
        )
        submission_ids: list[UUID] = []
        validation_ids: list[UUID | None] = []
        with self.session_factory() as database_session:
            for index, status in enumerate(statuses, start=1):
                submission_id = self._add_submission(
                    database_session,
                    index=index,
                    status="submitted",
                )
                submission_ids.append(submission_id)
                validation_ids.append(
                    None
                    if status is None
                    else self._add_validation(
                        database_session,
                        submission_id=submission_id,
                        index=index,
                        status=status,
                    )
                )

            # A review tied to older evidence must not resolve the current warning.
            database_session.add(
                SubmissionReviewDecisionRow(
                    decision_id=uuid4(),
                    submission_id=submission_ids[4],
                    validation_id=uuid4(),
                    status="accepted",
                    reviewer_notes=None,
                    decided_at=NOW,
                    decided_by="admin",
                    correlation_id="old-evidence-review",
                )
            )
            # The second warning has an exact-result acknowledgement.
            database_session.add(
                SubmissionReviewDecisionRow(
                    decision_id=uuid4(),
                    submission_id=submission_ids[5],
                    validation_id=validation_ids[5],
                    status="accepted",
                    reviewer_notes=None,
                    decided_at=NOW,
                    decided_by="admin",
                    correlation_id="exact-evidence-review",
                )
            )
            self._add_submission(
                database_session,
                index=20,
                status="superseded",
            )
            self._add_submission(
                database_session,
                index=21,
                status="withdrawn",
            )
            database_session.add(
                ProcessingRunRow(
                    processing_run_id=uuid4(),
                    session_id=self.session_id,
                    configuration_version_id=self.configuration_id,
                    scenario_snapshot_id=self.snapshot_id,
                    run_number=3,
                    status="awaiting_review",
                    roster_hash="d" * 64,
                    input_hash="e" * 64,
                    environment_json={"adapter": "test"},
                    created_at=NOW,
                    created_by="admin",
                    completed_at=None,
                    output_hash=None,
                    failure_code=None,
                    failure_detail=None,
                )
            )
            database_session.commit()

        overview = self.queries.get_session_validation_overview(str(self.session_id))

        self.assertIsNotNone(overview)
        assert overview is not None
        self.assertEqual(overview.session_status, SessionStatus.CLOSED)
        self.assertTrue(overview.has_active_configuration)
        self.assertEqual(overview.effective_submitted_count, 8)
        self.assertEqual(overview.unvalidated_count, 1)
        self.assertEqual(overview.active_count, 2)
        self.assertEqual(overview.valid_count, 1)
        self.assertEqual(overview.warned_count, 2)
        self.assertEqual(overview.invalid_count, 1)
        self.assertEqual(overview.error_count, 1)
        self.assertEqual(overview.warning_decisions_required, 1)
        self.assertEqual(overview.latest_batch_number, 3)
        self.assertEqual(overview.latest_batch_status, RunStatus.AWAITING_REVIEW)
        self.assertEqual(overview.latest_batch_roster_hash, "d" * 64)
        self.assertIsNotNone(overview.current_roster_hash)
        self.assertFalse(overview.roster_is_current)
        self.assertFalse(overview.validation_complete)
        self.assertEqual(overview.readiness_state, "validation_active")

    def test_missing_session_returns_none(self) -> None:
        self.assertIsNone(self.queries.get_session_validation_overview(str(uuid4())))

    def test_new_active_retry_is_the_latest_validation_attempt(self) -> None:
        with self.session_factory() as database_session:
            submission_id = self._add_submission(
                database_session,
                index=30,
                status="submitted",
            )
            self._add_validation(
                database_session,
                submission_id=submission_id,
                index=30,
                status="error",
            )
            self._add_validation(
                database_session,
                submission_id=submission_id,
                index=31,
                status="running",
                attempt_number=2,
            )
            database_session.commit()

        overview = self.queries.get_session_validation_overview(str(self.session_id))

        self.assertIsNotNone(overview)
        assert overview is not None
        self.assertEqual(overview.active_count, 1)
        self.assertEqual(overview.error_count, 0)

    def test_processing_submission_context_aggregates_all_attempts_by_group(
        self,
    ) -> None:
        participants = tuple(uuid4() for _ in range(4))
        first_submission_id = uuid4()
        current_submission_id = uuid4()
        with self.session_factory() as database_session:
            for index, participant_id in enumerate(participants):
                database_session.add(
                    ParticipantRow(
                        participant_id=participant_id,
                        session_id=self.session_id,
                        configuration_version_id=self.configuration_id,
                        session_stakeholder_group_id=self.group_id,
                        user_id=None,
                        invitation_id=None,
                        alias=f"Participant {index}",
                        access_status="active",
                        enrolled_at=NOW - timedelta(hours=1),
                        joined_at=None,
                        started_at=None,
                        submitted_at=None,
                        completed_at=None,
                        disabled_at=None,
                        disabled_by=None,
                        disable_reason=None,
                        withdrawn_at=None,
                        withdrawn_by=None,
                        withdrawal_reason=None,
                        created_at=NOW - timedelta(hours=1),
                        created_by="participant",
                        updated_at=NOW - timedelta(hours=1),
                        updated_by="participant",
                    )
                )

            def add_attempt(
                *,
                submission_id: UUID,
                participant_id: UUID,
                attempt_number: int,
                status: str,
                previous_submission_id: UUID | None = None,
            ) -> None:
                final = status != "draft"
                database_session.add(
                    SubmissionRow(
                        submission_id=submission_id,
                        session_id=self.session_id,
                        participant_id=participant_id,
                        configuration_version_id=self.configuration_id,
                        scenario_snapshot_id=self.snapshot_id,
                        session_stakeholder_group_id=self.group_id,
                        attempt_number=attempt_number,
                        previous_submission_id=previous_submission_id,
                        status=status,
                        response_format="direct_rating",
                        response_target_type="criterion",
                        answer_manifest_json={"answers": []} if final else None,
                        answer_schema_version=1 if final else None,
                        answers_hash=(
                            f"{attempt_number + len(status):064x}" if final else None
                        ),
                        started_at=NOW - timedelta(minutes=2),
                        last_saved_at=NOW - timedelta(minutes=1),
                        submitted_at=NOW - timedelta(minutes=1) if final else None,
                        submitted_by="participant" if final else None,
                        superseded_at=NOW if status == "superseded" else None,
                        superseded_by=(
                            "participant" if status == "superseded" else None
                        ),
                        withdrawn_at=NOW if status == "withdrawn" else None,
                        withdrawn_by=("participant" if status == "withdrawn" else None),
                        withdrawal_reason=(
                            "withdrawn" if status == "withdrawn" else None
                        ),
                        client_metadata_json={},
                        created_at=NOW - timedelta(minutes=2),
                        created_by="participant",
                        updated_at=NOW,
                        updated_by="participant",
                    )
                )

            add_attempt(
                submission_id=first_submission_id,
                participant_id=participants[0],
                attempt_number=1,
                status="superseded",
            )
            add_attempt(
                submission_id=current_submission_id,
                participant_id=participants[0],
                attempt_number=2,
                status="submitted",
                previous_submission_id=first_submission_id,
            )
            add_attempt(
                submission_id=uuid4(),
                participant_id=participants[1],
                attempt_number=1,
                status="draft",
            )
            add_attempt(
                submission_id=uuid4(),
                participant_id=participants[2],
                attempt_number=1,
                status="withdrawn",
            )
            add_attempt(
                submission_id=uuid4(),
                participant_id=participants[3],
                attempt_number=1,
                status="submitted",
            )
            self._add_validation(
                database_session,
                submission_id=current_submission_id,
                index=60,
                status="valid",
            )
            database_session.commit()

        context = self.queries.get_processing_submission_context(str(self.session_id))

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(len(context.groups), 1)
        group = context.groups[0]
        self.assertEqual(group.stakeholder_group_name, "Community")
        self.assertEqual(group.configured_voting_power, "0.6")
        self.assertEqual(group.enrolled_count, 4)
        self.assertEqual(group.submitted_count, 2)
        self.assertEqual(group.valid_count, 1)
        self.assertEqual(group.unvalidated_count, 1)
        self.assertEqual(group.superseded_attempt_count, 1)
        self.assertEqual(group.draft_attempt_count, 1)
        self.assertEqual(group.withdrawn_attempt_count, 1)
        self.assertEqual(group.resubmission_attempt_count, 1)

    def test_processing_session_queues_are_exclusive_without_final_contract(
        self,
    ) -> None:
        run_ids = []
        criterion_ids = (str(uuid4()), str(uuid4()))
        with self.session_factory() as database_session:
            for run_number, status in (
                (1, RunStatus.SUCCEEDED.value),
                (2, RunStatus.AWAITING_REVIEW.value),
            ):
                run_id = uuid4()
                run_ids.append(run_id)
                database_session.add(
                    ProcessingRunRow(
                        processing_run_id=run_id,
                        session_id=self.session_id,
                        configuration_version_id=self.configuration_id,
                        scenario_snapshot_id=self.snapshot_id,
                        run_number=run_number,
                        status=status,
                        roster_hash=f"{run_number}" * 64,
                        input_hash=f"{run_number + 2}" * 64,
                        environment_json={},
                        created_at=NOW + timedelta(minutes=run_number),
                        created_by="admin",
                        completed_at=(NOW if status == RunStatus.SUCCEEDED else None),
                        output_hash=(
                            "f" * 64 if status == RunStatus.SUCCEEDED else None
                        ),
                        failure_code=None,
                        failure_detail=None,
                    )
                )
            database_session.add(
                ProcessingMatrixRow(
                    processing_matrix_id=uuid4(),
                    processing_run_id=run_ids[-1],
                    level="session",
                    stakeholder_group_id=None,
                    validation_id=None,
                    criterion_ids_json=list(criterion_ids),
                    matrix_json=json_to_storage(
                        {
                            "shape": "crisp",
                            "values": [
                                [Decimal(1), Decimal(2)],
                                [Decimal("0.5"), Decimal(1)],
                            ],
                        }
                    ),
                    weights_json=json_to_storage(
                        {
                            "shape": "crisp",
                            "values": [
                                {
                                    "criterion_id": criterion_ids[0],
                                    "weight": Decimal("0.166666666666666667"),
                                },
                                {
                                    "criterion_id": criterion_ids[1],
                                    "weight": Decimal("0.833333333333333333"),
                                },
                            ],
                        }
                    ),
                    diagnostics_json=json_to_storage(
                        {
                            "consistency_ratio": Decimal("0.01"),
                            "threshold_exceeded": False,
                        }
                    ),
                    matrix_hash="a" * 64,
                )
            )
            database_session.commit()

        filters = SessionSearchFilters(
            search="validation scenario",
            statuses=(SessionStatus.CLOSED,),
            domain="Public policy",
            date_field=SessionDateField.CREATED,
            date_from=(NOW - timedelta(days=3)).date(),
            date_to=(NOW - timedelta(days=3)).date(),
        )
        in_progress = self.queries.list_processing_sessions(
            filters=filters,
            mode=ProcessingQueueMode.IN_PROGRESS,
        )
        processed = self.queries.list_processing_sessions(
            filters=filters,
            mode=ProcessingQueueMode.PROCESSED,
        )

        unprocessed = self.queries.list_processing_sessions(
            filters=filters,
            mode=ProcessingQueueMode.UNPROCESSED,
        )

        self.assertEqual(in_progress.total, 1)
        self.assertEqual(processed.total, 0)
        self.assertEqual(unprocessed.total, 0)
        self.assertEqual(in_progress.items[0].latest_run_number, 2)
        self.assertEqual(in_progress.items[0].successful_run_count, 1)
        self.assertEqual(in_progress.items[0].next_stage, "session_validation")
        self.assertEqual(
            in_progress.items[0].last_processing_activity_at,
            NOW + timedelta(minutes=2),
        )
        matrices = self.queries.list_run_matrices(str(run_ids[-1]))
        self.assertEqual(len(matrices), 1)
        self.assertEqual(
            matrices[0].weights,
            ("0.166666666666666667", "0.833333333333333333"),
        )
        self.assertEqual(
            matrices[0].values,
            (("1", "2"), ("0.5", "1")),
        )
        self.assertEqual(
            matrices[0].diagnostics["consistency_ratio"],
            Decimal("0.01"),
        )
        self.assertIsNone(
            self.queries.get_session_algorithm_configuration(
                str(self.session_id),
                AlgorithmRole.RANKING,
            )
        )
        newer_work = self.queries.list_processing_sessions(
            filters=SessionSearchFilters(processing_states=("newer_work",)),
            mode=ProcessingQueueMode.IN_PROGRESS,
        )
        not_started = self.queries.list_processing_sessions(
            filters=SessionSearchFilters(processing_states=("not_started",)),
            mode=ProcessingQueueMode.UNPROCESSED,
        )
        self.assertEqual(newer_work.total, 1)
        self.assertEqual(not_started.total, 0)

    def test_never_started_archived_session_is_excluded_from_all_queues(
        self,
    ) -> None:
        closed = self.queries.list_processing_sessions(
            filters=SessionSearchFilters(statuses=(SessionStatus.CLOSED,)),
            mode=ProcessingQueueMode.UNPROCESSED,
        )
        self.assertEqual(closed.total, 1)
        with self.session_factory() as database_session:
            session_row = database_session.get(SessionRow, self.session_id)
            assert session_row is not None
            session_row.status = SessionStatus.ARCHIVED.value
            session_row.archived_at = NOW
            session_row.updated_at = NOW
            database_session.commit()

        archived_filters = SessionSearchFilters(statuses=(SessionStatus.ARCHIVED,))
        totals = tuple(
            self.queries.list_processing_sessions(
                filters=archived_filters,
                mode=mode,
            ).total
            for mode in ProcessingQueueMode
        )
        self.assertEqual(totals, (0, 0, 0))

    def test_ranking_result_projection_preserves_level_and_generic_metrics(
        self,
    ) -> None:
        processing_run_id = uuid4()
        processing_matrix_id = uuid4()
        ranking_run_id = uuid4()
        ranking_result_id = uuid4()
        alternative_id = uuid4()
        with self.session_factory() as database_session:
            database_session.add(
                ProcessingRunRow(
                    processing_run_id=processing_run_id,
                    session_id=self.session_id,
                    configuration_version_id=self.configuration_id,
                    scenario_snapshot_id=self.snapshot_id,
                    run_number=1,
                    status=RunStatus.SUCCEEDED.value,
                    roster_hash="a" * 64,
                    input_hash="b" * 64,
                    environment_json={},
                    created_at=NOW,
                    created_by="admin",
                    completed_at=NOW,
                    output_hash="c" * 64,
                    failure_code=None,
                    failure_detail=None,
                )
            )
            database_session.add(
                ProcessingMatrixRow(
                    processing_matrix_id=processing_matrix_id,
                    processing_run_id=processing_run_id,
                    level="session",
                    stakeholder_group_id=None,
                    validation_id=None,
                    criterion_ids_json=[str(uuid4())],
                    matrix_json={},
                    weights_json={},
                    diagnostics_json={},
                    matrix_hash="d" * 64,
                )
            )
            database_session.add(
                RankingRunRow(
                    ranking_run_id=ranking_run_id,
                    session_id=self.session_id,
                    source_processing_run_id=processing_run_id,
                    configuration_version_id=self.configuration_id,
                    scenario_snapshot_id=self.snapshot_id,
                    run_number=1,
                    status=RunStatus.SUCCEEDED.value,
                    roster_hash="a" * 64,
                    input_hash="e" * 64,
                    algorithm_implementation_id=self.algorithm_id,
                    implementation_version="1.0.0",
                    adapter_version="1.0.0",
                    parameter_json={},
                    environment_json={},
                    created_at=NOW,
                    created_by="admin",
                    completed_at=NOW,
                    output_hash="f" * 64,
                    failure_code=None,
                    failure_detail=None,
                )
            )
            database_session.add(
                RankingResultRow(
                    ranking_result_id=ranking_result_id,
                    ranking_run_id=ranking_run_id,
                    source_processing_matrix_id=processing_matrix_id,
                    level="session",
                    stakeholder_group_id=None,
                    validation_id=None,
                    alternatives_json=json_to_storage(
                        {
                            "values": [
                                {
                                    "alternative_id": str(alternative_id),
                                    "rank": 1,
                                    "preference_value": Decimal("0.75"),
                                    "method_metrics": {
                                        "future_metric": Decimal("2.5")
                                    },
                                }
                            ]
                        }
                    ),
                    metric_label="Preference",
                    diagnostics_json=json_to_storage({"provider": "test"}),
                    result_hash="1" * 64,
                )
            )
            database_session.commit()

        results = self.queries.list_ranking_results(str(ranking_run_id))

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].level, "session")
        self.assertIsNone(results[0].participant_label)
        self.assertIsNone(results[0].validation_id)
        self.assertEqual(results[0].alternatives[0].preference_value, "0.75")
        self.assertEqual(
            results[0].alternatives[0].method_metrics["future_metric"],
            Decimal("2.5"),
        )

    def _add_submission(
        self,
        database_session: DatabaseSession,
        *,
        index: int,
        status: str,
    ) -> UUID:
        submission_id = uuid4()
        final_at = NOW - timedelta(minutes=index)
        is_superseded = status == "superseded"
        is_withdrawn = status == "withdrawn"
        database_session.add(
            SubmissionRow(
                submission_id=submission_id,
                session_id=self.session_id,
                participant_id=uuid4(),
                configuration_version_id=self.configuration_id,
                scenario_snapshot_id=self.snapshot_id,
                session_stakeholder_group_id=uuid4(),
                attempt_number=1,
                previous_submission_id=None,
                status=status,
                response_format="direct_rating",
                response_target_type="criterion",
                answer_manifest_json={"answers": []},
                answer_schema_version=1,
                answers_hash=f"{index + 100:064x}",
                started_at=final_at - timedelta(minutes=1),
                last_saved_at=final_at,
                submitted_at=final_at,
                submitted_by="participant",
                superseded_at=NOW if is_superseded else None,
                superseded_by="participant" if is_superseded else None,
                withdrawn_at=NOW if is_withdrawn else None,
                withdrawn_by="participant" if is_withdrawn else None,
                withdrawal_reason="withdrawn" if is_withdrawn else None,
                client_metadata_json={},
                created_at=final_at - timedelta(minutes=1),
                created_by="participant",
                updated_at=final_at,
                updated_by="participant",
            )
        )
        return submission_id

    def _add_validation(
        self,
        database_session: DatabaseSession,
        *,
        submission_id: UUID,
        index: int,
        status: str,
        attempt_number: int = 1,
    ) -> UUID:
        validation_id = uuid4()
        terminal = status in {
            "valid",
            "valid_with_warnings",
            "invalid",
            "error",
        }
        started = None if status == "pending" else NOW - timedelta(seconds=2)
        database_session.add(
            SubmissionValidationRow(
                validation_id=validation_id,
                submission_id=submission_id,
                answers_hash=f"{index + 200:064x}",
                configuration_hash="a" * 64,
                validator_implementation_id=self.algorithm_id,
                validator_version="test/1",
                parameter_json={},
                parameter_hash="b" * 64,
                status=status,
                attempt_number=attempt_number,
                completion_ratio=(
                    Decimal(1)
                    if status in {"valid", "valid_with_warnings"}
                    else Decimal(0)
                ),
                consistency_ratio=(
                    Decimal("0.12")
                    if status in {"valid", "valid_with_warnings", "invalid"}
                    else None
                ),
                quality_metrics_json={},
                started_at=started,
                completed_at=NOW if terminal else None,
                validated_by_actor_type="system" if terminal else None,
                validated_by_actor_id="validator" if terminal else None,
                input_hash=f"{index + 300:064x}",
                output_hash=f"{index + 400:064x}" if terminal else None,
                failure_code="provider.error" if status == "error" else None,
                failure_detail="Provider failed." if status == "error" else None,
            )
        )
        return validation_id


if __name__ == "__main__":
    unittest.main()
