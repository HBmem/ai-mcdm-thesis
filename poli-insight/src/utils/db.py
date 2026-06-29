from __future__ import annotations

import os
import sqlite3

from pathlib import Path

DEFAULT_DB_PATH = Path("database/poli-insight.sqlite")

def get_db_path() -> Path:
    """Get the path to the database file."""
    db_path = os.getenv("DB_PATH", str(DEFAULT_DB_PATH))
    return Path(db_path)

def get_db_connection() -> sqlite3.Connection:
    """Get a connection to the SQLite database."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure the directory exists
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
    conn.execute("PRAGMA foreign_keys = ON")  # Enable foreign key support
    conn.execute("PRAGMA journal_mode = WAL")  # Enable Write-Ahead Logging for better concurrency
    return conn

def initialize_db():
    """Initialize the database with the required tables."""
    with get_db_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS scenario_snapshots (
                scenario_id TEXT NOT NULL,
                scenario_version TEXT NOT NULL,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                config_snapshot_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (scenario_id, scenario_version)
            );

            CREATE TABLE IF NOT EXISTS scenario_sessions (
                session_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                scenario_version TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                admin_notes TEXT,
                visibility TEXT NOT NULL,
                participation_mode TEXT NOT NULL,
                preference_method TEXT NOT NULL,
                weighting_method TEXT NOT NULL,
                ranking_method TEXT NOT NULL,
                aggregation_method TEXT NOT NULL,
                require_access_code INTEGER NOT NULL DEFAULT 0,
                access_code_type TEXT,
                allow_resubmissions INTEGER NOT NULL DEFAULT 0,
                start_at TEXT,
                end_at TEXT,
                status TEXT NOT NULL,
                opened_at TEXT,
                closed_at TEXT,
                archived_at TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (status IN ('draft', 'active', 'closed', 'archived')),
                CHECK (opened_at <= closed_at),
                CHECK (closed_at <= archived_at),
                CHECK (created_at <= updated_at),
                FOREIGN KEY (scenario_id, scenario_version) REFERENCES scenario_snapshots(scenario_id, scenario_version)
            );

            CREATE TABLE IF NOT EXISTS session_stakeholder_groups(
                session_id TEXT NOT NULL,
                stakeholder_group_id TEXT NOT NULL,
                stakeholder_group_name TEXT NOT NULL,
                default_voting_power REAL NOT NULL DEFAULT 1.0 CHECK (default_voting_power > 0),
                current_voting_power REAL NOT NULL DEFAULT 1.0 CHECK (current_voting_power > 0),
                normalized_voting_power REAL NOT NULL DEFAULT 1.0 CHECK (normalized_voting_power > 0),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (is_active IN (0, 1)),
                PRIMARY KEY (session_id, stakeholder_group_id),
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS session_participants (
                participant_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                stakeholder_group_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL,
                access_code_hash TEXT,
                access_code_created_at TEXT,
                access_code_regenerated_at TEXT,
                access_code_expires_at TEXT,
                invited_at TEXT,
                submitted_at TEXT,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (session_id, participant_id),
                CHECK (status IN ('invited', 'active', 'submitted', 'disabled', 'expired')),
                FOREIGN KEY (session_id, stakeholder_group_id) REFERENCES session_stakeholder_groups(session_id, stakeholder_group_id)
            );

            CREATE TABLE IF NOT EXISTS preference_submissions (
                submission_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                participant_id TEXT NOT NULL,
                submission_version INTEGER NOT NULL,
                preference_scale TEXT NOT NULL,
                raw_preference_json TEXT NOT NULL,
                transformed_preference_json TEXT,
                validation_status TEXT,
                is_current INTEGER NOT NULL DEFAULT 1,
                submitted_at TEXT NOT NULL,
                superseded_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                CHECK (submission_version >= 0),
                CHECK (is_current IN (0, 1)),
                UNIQUE (participant_id, submission_version),
                FOREIGN KEY (session_id, participant_id) REFERENCES session_participants(session_id, participant_id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_current_submissions
            ON preference_submissions(session_id, participant_id)
            WHERE is_current = 1;

            CREATE TABLE IF NOT EXISTS audit_events (
                audit_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                actor_type TEXT NOT NULL,
                actor_id TEXT,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                before_json TEXT,
                after_json TEXT,
                reason TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id)
            );
            """
        )
