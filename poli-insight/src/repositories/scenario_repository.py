from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import sqlite3

from src.models.enum import (
    SessionStatus,
    SessionVisibility,
    WeightingMethod, 
    RankingMethod,
    PreferenceMethod,
    ParticipationMethod,
    AggregationMethod
)
from src.models.scenario import ScenarioBundle
from src.models.session import SessionScenario, SessionStakeholderGroup

from src.utils.db import get_db_connection
from src.utils.ids import new_id

class ScenarioRepositoryError(RuntimeError):
    pass

def get_or_create_scenario_snapshot(conn: sqlite3.Connection, bundle: ScenarioBundle) -> tuple[str, str]:
    """Persist an immutable scenario version once and return its identity.

    The scenario ID and version form the snapshot identity. An existing row
    may only be reused when its canonical configuration hash matches the
    supplied bundle. A mismatch requires a new scenario version.
    """
    config_hash, snapshot_json = _build_scenario_snapshot(bundle)
    now = utc_now()

    conn.execute(
        """
        INSERT INTO scenario_snapshots (
            scenario_id, scenario_version, scenario_type, title, domain,
            config_hash, config_snapshot_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (scenario_id, scenario_version) DO NOTHING;
        """,
        (
            bundle.scenario_id,
            bundle.scenario_version,
            bundle.scenario_type,
            bundle.title,
            bundle.domain,
            config_hash,
            snapshot_json,
            bundle.status,
            now,
        )
    )

    existing = conn.execute(
        """
        SELECT scenario_id, scenario_version, config_hash, config_snapshot_json
        FROM scenario_snapshots
        WHERE scenario_id = ? AND scenario_version = ?;
        """,        (bundle.scenario_id, bundle.scenario_version),
    ).fetchone()

    if existing is None:
        raise ScenarioRepositoryError(
            "Scenario snapshot could not be created or retrieved."
        )

    if existing["config_hash"] != config_hash:
        try:
            stored_canonical_json = _canonicalize_snapshot_json(
                existing["config_snapshot_json"]
            )
        except (TypeError, json.JSONDecodeError) as exc:
            raise ScenarioRepositoryError(
                f"Stored snapshot for scenario {bundle.scenario_id!r} version "
                f"{bundle.scenario_version!r} contains invalid JSON."
            ) from exc

        stored_canonical_hash = hashlib.sha256(
            stored_canonical_json.encode("utf-8")
        ).hexdigest()

        if stored_canonical_hash != config_hash:
            raise ScenarioRepositoryError(
                f"Scenario {bundle.scenario_id!r} version "
                f"{bundle.scenario_version!r} already exists with different "
                "configuration. Increment scenario_version before creating a session."
            )

    return existing["scenario_id"], existing["scenario_version"]

def get_scenarios_snapshots() -> list[ScenarioBundle]:
    """
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.execute("SELECT * FROM scenario_snapshots;")
            rows = cursor.fetchall()
            return[_row_to_scenario_snapshot(row) for row in rows]
        except Exception as e:
            raise ScenarioRepositoryError(f"Error fetching scenario snapshots")

def get_scenario_snapshot(scenario_id: str) -> ScenarioBundle | None:
    """
    Fetch a scenario snapshot by its ID.

    Args:
        scenario_id (str): The unique identifier of the scenario.

    Returns:
        ScenarioBundle | None: The scenario snapshot corresponding to the provided ID.
    """
    with get_db_connection() as conn:
        try:
            cursor = conn.execute(
                "SELECT * FROM scenario_snapshots WHERE scenario_id = ?;",
                (scenario_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return _row_to_scenario_snapshot(row)
        except Exception as e:
            raise ScenarioRepositoryError(f"Error fetching scenario snapshot: {e}")


# Helper functions
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _build_scenario_snapshot(bundle: ScenarioBundle) -> tuple[str, str]:
    snapshot = {
        "scenario": bundle.scenario,
        "criteria": bundle.criteria,
        "data_sources": bundle.data_sources,
        "preprocessing": bundle.preprocessing,
        "session_rules": bundle.session_rules,
        "ui_config": bundle.ui_config,
    }

    snapshot_json = _canonicalize_snapshot(snapshot)

    config_hash = hashlib.sha256(
        snapshot_json.encode("utf-8")
    ).hexdigest()

    return config_hash, snapshot_json

def _canonicalize_snapshot_json(snapshot_json: str) -> str:
    """Normalize a legacy stored JSON representation before comparison."""
    return _canonicalize_snapshot(json.loads(snapshot_json))

def _canonicalize_snapshot(snapshot: dict) -> str:
    """Serialize snapshot content deterministically for stable hashing."""
    return json.dumps(
        snapshot,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

def _row_to_scenario_snapshot(row: sqlite3.Row) -> ScenarioBundle:
    return ScenarioBundle(
        scenario_id=row["scenario_id"],
        scenario_version=row["scenario_version"],
        scenario_type=row["scenario_type"],
        title=row["title"],
        domain=row["domain"],
        scenario=json.loads(row["config_snapshot_json"])["scenario"],
        criteria=json.loads(row["config_snapshot_json"])["criteria"],
        data_sources=json.loads(row["config_snapshot_json"])["data_sources"],
        preprocessing=json.loads(row["config_snapshot_json"]).get("preprocessing"),
        session_rules=json.loads(row["config_snapshot_json"])["session_rules"],
        ui_config=json.loads(row["config_snapshot_json"])["ui_config"],
    )