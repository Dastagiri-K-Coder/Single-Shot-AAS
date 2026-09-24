# -*- coding: utf-8 -*-
"""
db.py — SQLite database manager for Single Shot AAS v2.0 local login system.

Manages the aas_users.db file (config/aas_users.db) which stores:
    - users        : Faculty and admin accounts (ID + bcrypt password hash)
    - sessions     : Active login session tokens (UUID4, 8-hour expiry)
    - audit_log    : Security event log (login, logout, create, deactivate, etc.)

This module has NO Flask dependency — it can be imported from any context.

Usage:
    from aas.core.db import init_db, get_db_connection
    init_db()          # safe to call multiple times (idempotent)
    conn = get_db_connection()
"""

import os
import sqlite3
import threading

from aas.core.config import CONFIG_DIR

# Path to the SQLite database file
DB_PATH = os.path.join(CONFIG_DIR, "aas_users.db")

# Thread-local storage for connections (one connection per thread)
_local = threading.local()

# Module-level init lock (ensures schema creation is thread-safe on first run)
_init_lock = threading.Lock()
_db_initialized = False


# ── Schema Definitions ────────────────────────────────────────────────────────

_SCHEMA_SQL = """
-- Users table: faculty and admin accounts
CREATE TABLE IF NOT EXISTS users (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          TEXT    UNIQUE NOT NULL,
    full_name        TEXT    NOT NULL,
    role             TEXT    NOT NULL CHECK(role IN ('admin', 'faculty')),
    password_hash    TEXT    NOT NULL,
    email            TEXT    DEFAULT '',
    assigned_cameras TEXT    DEFAULT '[]',
    is_active        INTEGER DEFAULT 1,
    is_locked        INTEGER DEFAULT 0,
    failed_attempts  INTEGER DEFAULT 0,
    must_change_password INTEGER DEFAULT 0,
    created_at       TEXT    NOT NULL,
    last_login       TEXT,
    created_by       TEXT
);

-- Sessions table: active login tokens
CREATE TABLE IF NOT EXISTS sessions (
    session_token TEXT    PRIMARY KEY,
    user_id       TEXT    NOT NULL,
    role          TEXT    NOT NULL,
    created_at    TEXT    NOT NULL,
    expires_at    TEXT    NOT NULL,
    ip_address    TEXT    DEFAULT ''
);

-- Audit log: security events
CREATE TABLE IF NOT EXISTS audit_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp  TEXT    NOT NULL,
    user_id    TEXT,
    action     TEXT    NOT NULL,
    details    TEXT,
    ip_address TEXT    DEFAULT ''
);

-- ── v2.5 Tables ───────────────────────────────────────────────────────────────

-- Attendance sessions: one per classroom image capture event (§14.1)
CREATE TABLE IF NOT EXISTS attendance_sessions (
    session_id               TEXT    PRIMARY KEY,
    camera_id                TEXT    NOT NULL,
    faculty_user_id          TEXT    NOT NULL,
    section_code             TEXT    NOT NULL,
    subject                  TEXT    DEFAULT '',
    subject_abbr             TEXT    DEFAULT '',
    period                   TEXT    DEFAULT '',
    attendance_date          TEXT    NOT NULL,
    source_mode              TEXT    DEFAULT 'MOBILE_UPLOAD',
    status                   TEXT    NOT NULL DEFAULT 'SESSION_CREATED',
    image_path               TEXT,
    recognized_count         INTEGER DEFAULT 0,
    unknown_count            INTEGER DEFAULT 0,
    low_res_count            INTEGER DEFAULT 0,
    manual_override_count    INTEGER DEFAULT 0,
    total_faces              INTEGER DEFAULT 0,
    recognition_model        TEXT    DEFAULT '',
    recognition_model_version TEXT   DEFAULT '',
    recognition_config_version TEXT  DEFAULT '',
    started_at               TEXT    NOT NULL,
    updated_at               TEXT    NOT NULL,
    finalized_at             TEXT,
    local_committed_at       TEXT,
    synchronized_at          TEXT,
    sync_status              TEXT    DEFAULT 'PENDING',
    last_error               TEXT,
    FOREIGN KEY (faculty_user_id) REFERENCES users(user_id)
);

-- Attendance records: one row per student per session (§14.2)
CREATE TABLE IF NOT EXISTS attendance_records (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT    NOT NULL,
    student_name     TEXT    NOT NULL,
    student_email    TEXT    DEFAULT '',
    status           TEXT    NOT NULL CHECK(status IN ('PRESENT', 'ABSENT')),
    source           TEXT    NOT NULL CHECK(source IN
                         ('AUTO_RECOGNITION', 'MANUAL_L1', 'INDIVIDUAL_L2', 'BULK_L3', 'SYSTEM')),
    confidence       REAL    DEFAULT 0.0,
    detection_status TEXT    DEFAULT 'valid',
    face_width       INTEGER DEFAULT 0,
    face_height      INTEGER DEFAULT 0,
    ipd              INTEGER DEFAULT 0,
    modified_by      TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    FOREIGN KEY (session_id) REFERENCES attendance_sessions(session_id)
);

-- Recognition jobs: tracks CV pipeline execution per session (§14.3)
CREATE TABLE IF NOT EXISTS recognition_jobs (
    job_id             TEXT    PRIMARY KEY,
    session_id         TEXT    NOT NULL,
    image_path         TEXT    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'PENDING'
                           CHECK(status IN ('PENDING','PROCESSING','COMPLETED','FAILED','INTERRUPTED')),
    detector           TEXT    DEFAULT 'yunet',
    recognition_model  TEXT    DEFAULT 'dlib_resnet',
    model_version      TEXT    DEFAULT '',
    scale_factor       REAL    DEFAULT 1.0,
    match_tolerance    REAL    DEFAULT 0.55,
    started_at         TEXT,
    completed_at       TEXT,
    result_json        TEXT,
    error_message      TEXT,
    FOREIGN KEY (session_id) REFERENCES attendance_sessions(session_id)
);

-- Sync outbox: durable bridge to Google Sheets/Drive (§14.4)
CREATE TABLE IF NOT EXISTS sync_outbox (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id         TEXT    UNIQUE NOT NULL,
    session_id       TEXT    NOT NULL,
    operation        TEXT    NOT NULL,
    target_type      TEXT    DEFAULT '',
    target_id        TEXT    DEFAULT '',
    payload_json     TEXT    NOT NULL DEFAULT '{}',
    idempotency_key  TEXT    UNIQUE NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'PENDING'
                         CHECK(status IN ('PENDING','PROCESSING','SYNCHRONIZED','RETRY_WAIT','PERMANENT_FAILURE')),
    attempt_count    INTEGER DEFAULT 0,
    next_attempt_at  TEXT,
    last_attempt_at  TEXT,
    last_error       TEXT,
    created_at       TEXT    NOT NULL,
    synchronized_at  TEXT,
    FOREIGN KEY (session_id) REFERENCES attendance_sessions(session_id)
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_att_sessions_faculty ON attendance_sessions(faculty_user_id);
CREATE INDEX IF NOT EXISTS idx_att_sessions_date    ON attendance_sessions(attendance_date);
CREATE INDEX IF NOT EXISTS idx_att_sessions_status  ON attendance_sessions(status);
CREATE INDEX IF NOT EXISTS idx_att_records_session  ON attendance_records(session_id);
CREATE INDEX IF NOT EXISTS idx_recog_jobs_session   ON recognition_jobs(session_id);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_status   ON sync_outbox(status, next_attempt_at);
CREATE INDEX IF NOT EXISTS idx_sync_outbox_session  ON sync_outbox(session_id);
"""

_PRAGMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
PRAGMA synchronous=NORMAL;
"""


# ── Connection Management ─────────────────────────────────────────────────────

def get_db_connection() -> sqlite3.Connection:
    """Return a thread-local SQLite connection to aas_users.db.

    Creates the connection if this thread doesn't have one yet.
    Row factory is set to sqlite3.Row for dict-like access.

    Returns:
        sqlite3.Connection with row_factory=sqlite3.Row

    Raises:
        OSError: If CONFIG_DIR cannot be created.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(_PRAGMA_SQL)
        _local.conn = conn
    return _local.conn


def close_db_connection() -> None:
    """Close and discard the thread-local connection (call at request teardown)."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None


# ── Schema Initialisation ─────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they do not already exist.

    Idempotent — safe to call on every application startup.
    Uses CREATE TABLE IF NOT EXISTS so existing data is never dropped.

    Raises:
        sqlite3.Error: If the schema SQL fails (e.g. disk full).
    """
    global _db_initialized
    with _init_lock:
        if _db_initialized:
            return
        conn = get_db_connection()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()
        _db_initialized = True
        print(f"  ✓ [DB] aas_users.db initialised at: {DB_PATH}")


def db_exists() -> bool:
    """Return True if the database file exists on disk."""
    return os.path.exists(DB_PATH)


def has_any_users() -> bool:
    """Return True if at least one user account exists (setup complete check)."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT COUNT(*) FROM users").fetchone()
        return row[0] > 0
    except sqlite3.OperationalError:
        # Table doesn't exist yet — init_db has not been called
        return False
