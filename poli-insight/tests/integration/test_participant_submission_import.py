from __future__ import annotations

import csv
import io
import os
import sqlite3
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig

from poli_insight.application.use_cases.activate_session_configuration import (
    ActivateSessionConfigurationCommand,
)
from poli_insight.application.use_cases.create_session import CreateSessionCommand
from poli_insight.application.use_cases.create_session_configuration import (
    AlgorithmSelectionInput,
    CreateSessionConfigurationCommand,
    StakeholderGroupInput,
)
from poli_insight.application.use_cases.import_bundled_scenarios import (
    ImportBundledScenariosCommand,
)
from poli_insight.application.use_cases.participant_submission_import import (
    ApplyParticipantSubmissionImportCommand,
    GenerateParticipantImportTemplateCommand,
    ParticipantSubmissionImportError,
    PreviewParticipantSubmissionImportCommand,
    RedactExpiredImportedIdentity,
    RedactExpiredImportedIdentityCommand,
)
from poli_insight.bootstrap import create_container
from poli_insight.config import Settings
from poli_insight.domain.enum import (
    AlgorithmRole,
    ResponseFormat,
    ResponseTargetType,
    ScenarioSnapshotStatus,
)
from poli_insight.infrastructure.database.engine import build_session_factory
from poli_insight.infrastructure.database.unit_of_work import SqlAlchemyUnitOfWork

PROJECT_ROOT = Path(__file__).parents[2]


def test_atomic_import_persists_only_keyed_reference_and_no_access_grant(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "participant-import.sqlite"
    database_url = f"sqlite+pysqlite:///{database_path}"
    with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
        alembic_command.upgrade(
            AlembicConfig(str(PROJECT_ROOT / "alembic.ini")), "head"
        )
    container = create_container(
        Settings(
            database_url=database_url,
            app_timezone="UTC",
            scenario_source_root=PROJECT_ROOT / "scenarios",
            scenario_template_directory="_template",
            participant_import_hmac_secret="import-hmac-secret-32-bytes-minimum-value",
            participant_identity_encryption_key=(
                "identity-encryption-secret-32-bytes-minimum"
            ),
        )
    )
    container.import_bundled_scenarios.execute(
        ImportBundledScenariosCommand(actor_id="import-admin")
    )
    snapshot = container.page_queries.list_scenario_snapshots(
        status=ScenarioSnapshotStatus.READY, page_size=10
    ).items[0]
    scenario = container.page_queries.get_scenario_snapshot_detail(
        snapshot.scenario_snapshot_id
    )
    assert scenario is not None
    scale = next(
        item for item in scenario.scales
        if item.scale_key == "direct_five_point_v1"
    )
    weighting = container.page_queries.list_active_algorithm_implementations(
        role=AlgorithmRole.WEIGHTING
    )[0]
    ranking = container.page_queries.list_active_algorithm_implementations(
        role=AlgorithmRole.RANKING
    )[0]
    session = container.sessions.create.execute(
        CreateSessionCommand(
            scenario_snapshot_id=snapshot.scenario_snapshot_id,
            public_slug="participant-import-integration",
            title="Participant import integration",
            actor_id="import-admin",
        )
    )
    configuration = container.sessions.create_configuration.execute(
        CreateSessionConfigurationCommand(
            session_id=session.session_id,
            actor_id="import-admin",
            response_format=ResponseFormat.DIRECT_RATING,
            response_target_type=ResponseTargetType.CRITERION,
            scale_id=scale.scale_id,
            stakeholder_groups=(
                StakeholderGroupInput(
                    group_key="community",
                    name="Community",
                    description="Community members",
                    allocation_units=10_000,
                    required=True,
                ),
            ),
            algorithms=(
                AlgorithmSelectionInput(
                    weighting.algorithm_implementation_id,
                    AlgorithmRole.WEIGHTING,
                ),
                AlgorithmSelectionInput(
                    ranking.algorithm_implementation_id,
                    AlgorithmRole.RANKING,
                ),
            ),
        )
    )
    container.sessions.activate_configuration.execute(
        ActivateSessionConfigurationCommand(
            session_id=session.session_id,
            configuration_version_id=configuration.configuration_version_id,
            actor_id="import-admin",
        )
    )
    template = container.participant_imports.generate_template.execute(
        GenerateParticipantImportTemplateCommand(
            session_id=session.session_id,
            file_format="csv",
            filled_example=True,
        )
    )
    preview = container.participant_imports.preview.execute(
        PreviewParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename=template.filename,
            content=template.content,
        )
    )
    assert not preview.has_blocking_errors
    assert preview.summary.new_participants == 1
    result = container.participant_imports.apply.execute(
        ApplyParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename=template.filename,
            content=template.content,
            expected_file_hash=preview.file_hash,
            expected_plan_hash=preview.plan_hash,
            actor_id="import-admin",
            actor_roles=frozenset({"admin"}),
        )
    )
    assert result.created_participant_count == 1
    assert result.submitted_count == 1
    validation_queue = container.page_queries.list_validation_queue(
        session.session_id
    )
    assert validation_queue.total == 1
    assert validation_queue.items[0].submission_id == result.rows[0].submission_id
    retried = container.participant_imports.apply.execute(
        ApplyParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename=template.filename,
            content=template.content,
            expected_file_hash=preview.file_hash,
            expected_plan_hash=preview.plan_hash,
            actor_id="import-admin",
            actor_roles=frozenset({"admin"}),
        )
    )
    assert retried.already_applied
    replacement_preview = container.participant_imports.preview.execute(
        PreviewParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename=template.filename,
            content=template.content,
            replace_row_numbers=frozenset({2}),
        )
    )
    assert replacement_preview.summary.planned_replacements == 1
    with pytest.raises(
        ParticipantSubmissionImportError, match="resubmission-policy override"
    ):
        container.participant_imports.apply.execute(
            ApplyParticipantSubmissionImportCommand(
                session_id=session.session_id,
                filename=template.filename,
                content=template.content,
                expected_file_hash=replacement_preview.file_hash,
                expected_plan_hash=replacement_preview.plan_hash,
                actor_id="import-admin",
                actor_roles=frozenset({"admin"}),
                replace_row_numbers=frozenset({2}),
            )
        )
    replacement = container.participant_imports.apply.execute(
        ApplyParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename=template.filename,
            content=template.content,
            expected_file_hash=replacement_preview.file_hash,
            expected_plan_hash=replacement_preview.plan_hash,
            actor_id="import-admin",
            actor_roles=frozenset({"admin"}),
            replace_row_numbers=frozenset({2}),
            resubmission_override=True,
            resubmission_override_reason="Approved test replacement",
        )
    )
    assert replacement.replaced_count == 1

    reader = csv.DictReader(io.StringIO(template.content.decode("utf-8")))
    identity_row = next(reader)
    identity_row.update(
        {
            "participant_ref": "identity-reference-002",
            "participant_alias": "Imported identity 002",
            "participant_name": "Authored Name",
            "participant_email": "Authored.Email@Example.test",
        }
    )
    identity_stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        identity_stream, fieldnames=reader.fieldnames, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow(identity_row)
    identity_content = identity_stream.getvalue().encode("utf-8")
    identity_preview = container.participant_imports.preview.execute(
        PreviewParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename="identity-import.csv",
            content=identity_content,
        )
    )
    identity_result = container.participant_imports.apply.execute(
        ApplyParticipantSubmissionImportCommand(
            session_id=session.session_id,
            filename="identity-import.csv",
            content=identity_content,
            expected_file_hash=identity_preview.file_hash,
            expected_plan_hash=identity_preview.plan_hash,
            actor_id="import-admin",
            actor_roles=frozenset({"admin"}),
            identity_processing_attested=True,
            identity_processing_basis="Moderator authorization on file",
        )
    )
    assert identity_result.identity_count == 1
    with sqlite3.connect(database_path) as connection:
        encrypted_identity = connection.execute(
            "SELECT display_name_ciphertext, email_ciphertext, "
            "email_lookup_hash FROM participant_identities"
        ).fetchone()
    assert encrypted_identity is not None
    assert all(value is not None for value in encrypted_identity)
    assert b"Authored Name" not in encrypted_identity[0]
    assert b"Authored.Email@Example.test" not in encrypted_identity[1]
    assert len(encrypted_identity[2]) == 64

    future_redactor = RedactExpiredImportedIdentity(
        lambda: SqlAlchemyUnitOfWork(
            build_session_factory(container.settings)
        ),
        clock=lambda: identity_result.imported_at + timedelta(days=366),
    )
    redacted = future_redactor.execute(
        RedactExpiredImportedIdentityCommand(limit=10)
    )
    assert redacted.redacted_count == 1

    with sqlite3.connect(database_path) as connection:
        participant_count = connection.execute(
            "SELECT count(*) FROM participants"
        ).fetchone()
        submission_statuses = connection.execute(
            "SELECT status FROM submissions ORDER BY status"
        ).fetchall()
        grant_count = connection.execute(
            "SELECT count(*) FROM participant_access_grants"
        ).fetchone()
        reference = connection.execute(
            "SELECT reference_digest FROM participant_import_references"
        ).fetchone()
        consent = connection.execute(
            "SELECT reason_code FROM admin_import_consent_dispositions"
        ).fetchone()
        identity = connection.execute(
            "SELECT display_name_ciphertext, email_ciphertext, "
            "email_lookup_hash, redacted_at FROM participant_identities"
        ).fetchone()
        authority = connection.execute(
            "SELECT processing_basis FROM imported_identity_authorities"
        ).fetchone()
        persisted_text = " ".join(
            str(value)
            for row in connection.execute(
                "SELECT reference_digest FROM participant_import_references"
            )
            for value in row
        )
        audit_text = " ".join(
            str(value)
            for row in connection.execute(
                "SELECT before_json, after_json, source_metadata_json "
                "FROM audit_events"
            )
            for value in row
            if value is not None
        )
    assert participant_count == (2,)
    assert submission_statuses == [
        ("submitted",),
        ("submitted",),
        ("superseded",),
    ]
    assert grant_count == (0,)
    assert reference is not None and len(reference[0]) == 64
    assert "example-participant-001" not in persisted_text
    assert consent == ("not_applicable_admin_import",)
    assert identity is not None
    assert identity[:3] == (None, None, None)
    assert identity[3] is not None
    assert authority == ("Moderator authorization on file",)
    for sensitive in (
        "example-participant-001",
        "identity-reference-002",
        "Authored Name",
        "Authored.Email@Example.test",
    ):
        assert sensitive not in audit_text
