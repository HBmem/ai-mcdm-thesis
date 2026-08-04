"""complete the admin session core registry and audit vocabulary

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-03
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

from poli_insight.infrastructure.database.types import UUIDString

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_AHP_ID = "10000000-0000-4000-8000-000000000001"
_TOPSIS_ID = "10000000-0000-4000-8000-000000000002"
_ORIGINAL_ACTIONS = (
    "created",
    "updated",
    "opened",
    "closed",
    "invited",
    "redeemed",
    "submitted",
    "validated",
    "included",
    "excluded",
    "processed",
    "analyzed",
    "approved",
    "published",
    "withdrawn",
    "redacted",
)
_ADMIN_SESSION_ACTIONS = (
    "activated",
    "scheduled",
    "paused",
    "resumed",
    "canceled",
    "archived",
)


def _action_constraint(values: tuple[str, ...]) -> str:
    return "action IN (" + ", ".join(repr(value) for value in values) + ")"


def upgrade() -> None:
    created_at = datetime.now(UTC)
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint(
            "ck_audit_events_action_allowed",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_audit_events_action_allowed",
            _action_constraint((*_ORIGINAL_ACTIONS, *_ADMIN_SESSION_ACTIONS)),
        )

    implementations = sa.table(
        "algorithm_implementations",
        sa.column("algorithm_implementation_id", UUIDString()),
        sa.column("stable_key", sa.String()),
        sa.column("role", sa.String()),
        sa.column("conceptual_method", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("library_name", sa.String()),
        sa.column("library_version", sa.String()),
        sa.column("implementation_version", sa.String()),
        sa.column("adapter_version", sa.String()),
        sa.column("parameter_schema_json", sa.JSON()),
        sa.column("capabilities_json", sa.JSON()),
        sa.column("status", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        implementations,
        [
            {
                "algorithm_implementation_id": _AHP_ID,
                "stable_key": "pydecision.ahp",
                "role": "weighting",
                "conceptual_method": "AHP",
                "provider": "pydecision",
                "library_name": "pyDecision",
                "library_version": "5.1.1",
                "implementation_version": "1.0.0",
                "adapter_version": "1.0.0",
                "parameter_schema_json": {
                    "type": "object",
                    "additionalProperties": False,
                },
                "capabilities_json": {
                    "response_formats": ["pairwise", "direct_rating"],
                    "response_targets": ["criterion"],
                },
                "status": "active",
                "created_at": created_at,
            },
            {
                "algorithm_implementation_id": _TOPSIS_ID,
                "stable_key": "pydecision.topsis",
                "role": "ranking",
                "conceptual_method": "TOPSIS",
                "provider": "pydecision",
                "library_name": "pyDecision",
                "library_version": "5.1.1",
                "implementation_version": "1.0.0",
                "adapter_version": "1.0.0",
                "parameter_schema_json": {
                    "type": "object",
                    "additionalProperties": False,
                },
                "capabilities_json": {
                    "scenario_types": ["standard"],
                },
                "status": "active",
                "created_at": created_at,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM algorithm_implementations "
            "WHERE algorithm_implementation_id IN (:ahp_id, :topsis_id)"
        ).bindparams(ahp_id=_AHP_ID, topsis_id=_TOPSIS_ID)
    )
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint(
            "ck_audit_events_action_allowed",
            type_="check",
        )
        batch_op.create_check_constraint(
            "ck_audit_events_action_allowed",
            _action_constraint(_ORIGINAL_ACTIONS),
        )
