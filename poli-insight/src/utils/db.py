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
            CREATE TABLE IF NOT EXISTS scenario_sessions (
                session_id TEXT PRIMARY KEY,
                scenario_id TEXT NOT NULL,
                session_title TEXT NOT NULL,
                session_description TEXT,
                session_visibility TEXT NOT NULL,
                status TEXT NOT NULL,
                admin_notes TEXT,
                weighting_method TEXT NOT NULL,
                ranking_method TEXT NOT NULL,
                preference_method TEXT NOT NULL,
                participation_mode TEXT NOT NULL,
                aggregation_method TEXT NOT NULL,
                voting_power TEXT NOT NULL,
                voting_power_config TEXT NOT NULL DEFAULT '{}',
                require_access_code INTEGER NOT NULL DEFAULT 0,         
                access_code_type TEXT,
                allow_resubmissions INTEGER NOT NULL DEFAULT 0,
                start_date_time TEXT,
                end_date_time TEXT,
                opened_by TEXT,
                opened_at TEXT,
                closed_by TEXT,
                closed_at TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS session_stakeholder_groups(
                session_id TEXT NOT NULL,
                stakeholder_group_id TEXT NOT NULL,
                stakeholder_group_name TEXT NOT NULL,
                unique_voting_power REAL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (session_id, stakeholder_group_id),
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS session_participants (
                participant_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                stakeholder_group_id TEXT NOT NULL,
                access_code_hash TEXT,
                access_code_created_at TEXT,
                access_code_regenerated_at TEXT,
                access_code_expires_at TEXT NOT NULL,
                invited_at TEXT,
                started_at TEXT,
                submitted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id),
                FOREIGN KEY (stakeholder_group_id) REFERENCES session_stakeholder_groups(stakeholder_group_id)
            );

            CREATE TABLE IF NOT EXISTS session_participant_submissions (
                submission_id TEXT PRIMARY KEY,
                participant_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                stakeholder_group_id TEXT NOT NULL,
                submission_data TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (participant_id) REFERENCES session_participants(participant_id),
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id),
                FOREIGN KEY (stakeholder_group_id) REFERENCES session_stakeholder_groups(stakeholder_group_id)
            );

            CREATE TABLE IF NOT EXISTS session_participant_submission_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                submission_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (submission_id) REFERENCES session_participant_submissions(submission_id)
            );

            CREATE TABLE IF NOT EXISTS session_stakeholder_groups (
                session_id,
                stakeholder_group_id,
                group_name
                default_voting_power REAL NOT NULL DEFAULT 1.0,
                current_group_voting_power REAL NOT NULL DEFAULT 1.0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL
                PRIMARY KEY (session_id, stakeholder_group_id),
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id)
            );

            CREATE TABLE IF NOT EXISTS session_stakeholder_group_log (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                stakeholder_group_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES scenario_sessions(session_id),
                FOREIGN KEY (stakeholder_group_id) REFERENCES session_stakeholder_groups(stakeholder_group_id)
            );
            """
            
        )