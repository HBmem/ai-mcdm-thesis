from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DatabaseSession
from sqlalchemy.orm import sessionmaker

from poli_insight.infrastructure.database.base import Base
from poli_insight.infrastructure.database.engine import _REGISTERED_MODEL_MODULES
from poli_insight.infrastructure.database.models.analysis import (
    AnalysisCaseRow,
    AnalysisRunRow,
)
from poli_insight.infrastructure.database.queries.page_queries import (
    SqlAlchemyPageQueries,
)


def test_analysis_case_query_filters_scopes_and_paginates_rows() -> None:
    assert _REGISTERED_MODEL_MODULES
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        class_=DatabaseSession,
        expire_on_commit=False,
        autoflush=False,
    )
    run_id = uuid4()
    now = datetime(2026, 9, 8, tzinfo=UTC)
    with factory() as database_session:
        database_session.add(
            AnalysisRunRow(
                analysis_run_id=run_id,
                session_id=uuid4(),
                source_processing_run_id=uuid4(),
                source_ranking_run_id=uuid4(),
                run_number=1,
                analysis_type="sensitivity",
                method="one_at_a_time_weight_perturbation",
                status="succeeded",
                source_processing_output_hash="a" * 64,
                source_ranking_output_hash="b" * 64,
                input_hash="c" * 64,
                parameter_json={},
                environment_json={},
                created_at=now,
                created_by="admin-1",
                completed_at=now,
                correlation_id="correlation-1",
                output_hash="d" * 64,
            )
        )
        database_session.add_all(
            AnalysisCaseRow(
                analysis_case_id=uuid4(),
                analysis_run_id=run_id,
                sequence=sequence,
                status="evaluated",
                scope_type="session",
                scope_id=None,
                subject_type="criterion",
                subject_id=None,
                input_json={"candidate_weight": str(sequence / 100)},
                result_json={"metrics": {"top_set_changed": False}},
                warnings_json={"values": []},
                content_hash=f"{sequence:064x}",
            )
            for sequence in range(1, 31)
        )
        database_session.commit()

    queries = SqlAlchemyPageQueries(factory)
    page = queries.list_analysis_cases(
        str(run_id), scope_type="session", page=2, page_size=10
    )
    scopes = queries.list_analysis_scopes(str(run_id))
    summary = queries.summarize_analysis_level(str(run_id), result_level="session")

    assert page.total == 30
    assert tuple(item.sequence for item in page.items) == tuple(range(11, 21))
    assert len(page.items) == 10
    assert len(scopes) == 1
    assert scopes[0].label == "Session aggregate"
    assert summary.case_count == 30
    assert summary.evaluated_count == 30
    assert summary.not_evaluable_count == 0
    assert summary.top_set_change_count == 0
    assert summary.displacement_distribution == {0: 30}


def test_participant_aggregate_summaries_do_not_project_identities() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine,
        class_=DatabaseSession,
        expire_on_commit=False,
        autoflush=False,
    )
    run_id = uuid4()
    group_id = uuid4()
    participant_id = uuid4()
    now = datetime(2026, 9, 9, tzinfo=UTC)
    with factory() as database_session:
        database_session.add(
            AnalysisRunRow(
                analysis_run_id=run_id,
                session_id=uuid4(),
                source_processing_run_id=uuid4(),
                source_ranking_run_id=uuid4(),
                run_number=1,
                analysis_type="participant_impact",
                method="participant_influence",
                status="succeeded",
                source_processing_output_hash="a" * 64,
                source_ranking_output_hash="b" * 64,
                input_hash="c" * 64,
                parameter_json={},
                environment_json={},
                created_at=now,
                created_by="admin-1",
                completed_at=now,
                correlation_id="correlation-1",
                output_hash="d" * 64,
            )
        )
        database_session.add(
            AnalysisCaseRow(
                analysis_case_id=uuid4(),
                analysis_run_id=run_id,
                sequence=1,
                status="evaluated",
                scope_type="participant",
                scope_id=str(group_id),
                subject_type="participant",
                subject_id=str(participant_id),
                input_json={"omitted_participant_id": str(participant_id)},
                result_json={
                    "session_metrics": {
                        "top_set_changed": True,
                        "strict_reversals": 1,
                        "maximum_rank_displacement": 2,
                    },
                    "group_metrics": {
                        "top_set_changed": False,
                        "strict_reversals": 0,
                        "maximum_rank_displacement": 1,
                    },
                },
                warnings_json={"values": []},
                content_hash="e" * 64,
            )
        )
        database_session.commit()

    queries = SqlAlchemyPageQueries(factory)
    session_summary = queries.summarize_analysis_level(
        str(run_id), result_level="session"
    )
    group_summary = queries.summarize_analysis_level(
        str(run_id),
        result_level="stakeholder_group",
        stakeholder_group_id=str(group_id),
    )

    assert session_summary.top_set_change_count == 1
    assert session_summary.maximum_rank_displacement == 2
    assert group_summary.top_set_change_count == 0
    assert group_summary.maximum_rank_displacement == 1
    assert str(participant_id) not in repr(session_summary)
    assert str(participant_id) not in repr(group_summary)
