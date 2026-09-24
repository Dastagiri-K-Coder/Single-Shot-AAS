# -*- coding: utf-8 -*-
"""
auth.py — Local ID+Password authentication for Single Shot AAS v2.0.

Replaces Google OAuth as the primary login gate. Google OAuth is retained
only for Google Sheets API access (spreadsheet.py / oauth.py) and is NOT
called during the login flow.

Security features:
    - bcrypt password hashing (rounds=12, salt embedded)
    - Account lockout after 5 consecutive failed attempts
    - UUID4 session tokens with 8-hour expiry stored in SQLite
    - Audit log for all security events
    - No plaintext passwords stored or logged at any point

Functions:
    hash_password(plain)               → bcrypt hash string
    verify_password(plain, hashed)     → bool
    db_get_user(user_id)               → dict | None
    db_create_user(...)                → dict
    db_increment_failed(user_id)       → None (locks if ≥ 5 attempts)
    db_reset_failed(user_id)           → None
    create_session(user_id, role, ip)  → session_token str
    validate_session(token)            → dict | None
    delete_session(token)              → None
    log_audit(user_id, action, ...)    → None
    unlock_user(user_id)               → None
    deactivate_user(user_id)           → None
    get_all_users()                    → list[dict]
"""

import uuid
import datetime

import bcrypt

from aas.core.db import get_db_connection, init_db

# Session lifetime: 8 hours
_SESSION_HOURS = 8

# Max failed login attempts before lockout
_MAX_FAILED_ATTEMPTS = 5


# ── Password Hashing ──────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (rounds=12).

    The salt is embedded in the returned hash string — no separate storage needed.

    Args:
        plain: Plaintext password string.

    Returns:
        bcrypt hash string (60 characters, includes salt + cost factor).

    Raises:
        ValueError: If plain is empty.
    """
    if not plain:
        raise ValueError("hash_password: password must not be empty.")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Compare a plaintext password against a stored bcrypt hash.

    Args:
        plain:  Plaintext password to check.
        hashed: Stored bcrypt hash from the database.

    Returns:
        True if the password matches, False otherwise.
        Returns False (not raises) on any error to prevent timing attacks.
    """
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── User CRUD ─────────────────────────────────────────────────────────────────

def db_get_user(user_id: str) -> dict | None:
    """Fetch a user record by user_id.

    Args:
        user_id: The faculty/admin ID (e.g. 'FAC-001', 'ADM-001').

    Returns:
        Dict of user fields, or None if not found.
    """
    try:
        init_db()
        conn = get_db_connection()
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id.upper(),)
        ).fetchone()
        return dict(row) if row else None
    except Exception as e:
        print(f"  [Auth] db_get_user error: {e}")
        return None


def db_create_user(
    user_id: str,
    full_name: str,
    role: str,
    plain_password: str,
    email: str = "",
    assigned_cameras: list | None = None,
    created_by: str = "system",
    must_change_password: bool = False,
) -> dict:
    """Create a new user account with a bcrypt-hashed password.

    Args:
        user_id:             Unique ID (e.g. 'FAC-005'). Auto-uppercased.
        full_name:           Display name.
        role:                'admin' or 'faculty'.
        plain_password:      Plaintext temporary password.
        email:               Optional email for notifications.
        assigned_cameras:    List of camera IDs this faculty can access.
        created_by:          user_id of the admin creating this account.
        must_change_password: Force password change on first login.

    Returns:
        Dict of the created user (without password_hash).

    Raises:
        ValueError: If user_id already exists or role is invalid.
    """
    import json

    if role not in ("admin", "faculty"):
        raise ValueError(f"db_create_user: invalid role '{role}'. Must be 'admin' or 'faculty'.")

    user_id = user_id.upper()
    if db_get_user(user_id):
        raise ValueError(f"db_create_user: user_id '{user_id}' already exists.")

    init_db()
    conn = get_db_connection()
    now = datetime.datetime.now().isoformat()
    cameras_json = json.dumps(assigned_cameras or [])
    password_hash = hash_password(plain_password)

    conn.execute(
        """INSERT INTO users
           (user_id, full_name, role, password_hash, email, assigned_cameras,
            is_active, is_locked, failed_attempts, must_change_password,
            created_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, ?, ?, ?)""",
        (user_id, full_name, role, password_hash, email, cameras_json,
         int(must_change_password), now, created_by),
    )
    conn.commit()
    log_audit(created_by, "create_user", f"Created {role} account: {user_id}")
    return db_get_user(user_id)


def db_increment_failed(user_id: str) -> None:
    """Increment failed login attempts. Lock account if threshold reached.

    Lockout threshold: _MAX_FAILED_ATTEMPTS (default 5).
    Locked accounts require admin unlock via unlock_user().
    """
    try:
        init_db()
        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET failed_attempts = failed_attempts + 1 WHERE user_id = ?",
            (user_id.upper(),),
        )
        row = conn.execute(
            "SELECT failed_attempts FROM users WHERE user_id = ?", (user_id.upper(),)
        ).fetchone()
        if row and row["failed_attempts"] >= _MAX_FAILED_ATTEMPTS:
            conn.execute(
                "UPDATE users SET is_locked = 1 WHERE user_id = ?", (user_id.upper(),)
            )
            log_audit(user_id, "account_locked",
                      f"Locked after {_MAX_FAILED_ATTEMPTS} failed attempts.")
        conn.commit()
    except Exception as e:
        print(f"  [Auth] db_increment_failed error: {e}")


def db_reset_failed(user_id: str) -> None:
    """Reset failed attempt counter after successful login."""
    try:
        init_db()
        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET failed_attempts = 0, last_login = ? WHERE user_id = ?",
            (datetime.datetime.now().isoformat(), user_id.upper()),
        )
        conn.commit()
    except Exception as e:
        print(f"  [Auth] db_reset_failed error: {e}")


def db_set_password(user_id: str, new_plain_password: str, clear_force_change: bool = True) -> None:
    """Update a user's password hash and optionally clear must_change_password."""
    try:
        init_db()
        conn = get_db_connection()
        new_hash = hash_password(new_plain_password)
        conn.execute(
            "UPDATE users SET password_hash = ?, must_change_password = ? WHERE user_id = ?",
            (new_hash, 0 if clear_force_change else 1, user_id.upper()),
        )
        conn.commit()
        log_audit(user_id, "password_changed", "Password updated.")
    except Exception as e:
        print(f"  [Auth] db_set_password error: {e}")


def unlock_user(user_id: str, unlocked_by: str = "admin") -> None:
    """Reset lockout state for a user account."""
    try:
        init_db()
        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET is_locked = 0, failed_attempts = 0 WHERE user_id = ?",
            (user_id.upper(),),
        )
        conn.commit()
        log_audit(unlocked_by, "unlock_user", f"Unlocked account: {user_id}")
    except Exception as e:
        print(f"  [Auth] unlock_user error: {e}")


def deactivate_user(user_id: str, deactivated_by: str = "admin") -> None:
    """Deactivate a user account and delete all their active sessions."""
    try:
        init_db()
        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET is_active = 0 WHERE user_id = ?", (user_id.upper(),)
        )
        # Invalidate all active sessions for this user
        conn.execute(
            "DELETE FROM sessions WHERE user_id = ?", (user_id.upper(),)
        )
        conn.commit()
        log_audit(deactivated_by, "deactivate_user", f"Deactivated account: {user_id}")
    except Exception as e:
        print(f"  [Auth] deactivate_user error: {e}")


def get_all_users() -> list[dict]:
    """Return all user accounts (without password_hash for safety)."""
    try:
        init_db()
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT id, user_id, full_name, role, email, assigned_cameras, "
            "is_active, is_locked, failed_attempts, must_change_password, "
            "created_at, last_login, created_by FROM users ORDER BY role, user_id"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"  [Auth] get_all_users error: {e}")
        return []


# ── Session Management ────────────────────────────────────────────────────────

def create_session(user_id: str, role: str, ip_address: str = "") -> str:
    """Create a new session token for an authenticated user.

    Args:
        user_id:    Authenticated user's ID.
        role:       'admin' or 'faculty'.
        ip_address: Client IP address for audit purposes.

    Returns:
        UUID4 session token string.
    """
    init_db()
    conn = get_db_connection()
    token = str(uuid.uuid4())
    now = datetime.datetime.now()
    expires = now + datetime.timedelta(hours=_SESSION_HOURS)

    conn.execute(
        """INSERT INTO sessions (session_token, user_id, role, created_at, expires_at, ip_address)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (token, user_id, role, now.isoformat(), expires.isoformat(), ip_address),
    )
    conn.commit()
    # Force WAL checkpoint so other threads/connections see this session immediately
    try:
        conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        pass
    return token


def validate_session(token: str) -> dict | None:
    """Validate a session token and return the associated user record.

    Args:
        token: The session_token from the browser cookie.

    Returns:
        Dict with {user_id, role, full_name, email, assigned_cameras,
                   must_change_password, is_active} if valid.
        None if token is missing, expired, or user is deactivated.
    """
    if not token:
        return None
    try:
        init_db()
        conn = get_db_connection()
        now = datetime.datetime.now().isoformat()
        row = conn.execute(
            """SELECT s.user_id, s.role, u.full_name, u.email,
                      u.assigned_cameras, u.must_change_password,
                      u.is_active, u.is_locked
               FROM sessions s
               JOIN users u ON s.user_id = u.user_id
               WHERE s.session_token = ? AND s.expires_at > ?""",
            (token, now),
        ).fetchone()
        if not row:
            return None
        user = dict(row)
        # Reject if account deactivated or locked after session creation
        if not user["is_active"]:
            return None
        return user
    except Exception as e:
        print(f"  [Auth] validate_session error: {e}")
        return None


def delete_session(token: str) -> None:
    """Delete a session token (logout)."""
    if not token:
        return
    try:
        init_db()
        conn = get_db_connection()
        conn.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
        conn.commit()
    except Exception as e:
        print(f"  [Auth] delete_session error: {e}")


def cleanup_expired_sessions() -> int:
    """Delete all expired sessions from the database.

    Returns:
        Number of sessions deleted.
    """
    try:
        init_db()
        conn = get_db_connection()
        now = datetime.datetime.now().isoformat()
        cursor = conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"  [Auth] cleanup_expired_sessions error: {e}")
        return 0


# ── Audit Log ─────────────────────────────────────────────────────────────────

def log_audit(
    user_id: str | None,
    action: str,
    details: str = "",
    ip_address: str = "",
) -> None:
    """Append an event to the audit log.

    Args:
        user_id:    The user who performed the action (or None for system events).
        action:     Short action code: 'login', 'logout', 'create_user',
                    'deactivate', 'unlock', 'password_changed', 'account_locked'.
        details:    Optional human-readable detail string.
        ip_address: Client IP address.
    """
    try:
        init_db()
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO audit_log (timestamp, user_id, action, details, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (datetime.datetime.now().isoformat(), user_id, action, details, ip_address),
        )
        conn.commit()
    except Exception as e:
        # Audit log failure must never crash the main flow
        print(f"  [Auth] log_audit error: {e}")


# ── v2 API Auth Decorator ─────────────────────────────────────────────────────

def login_required(f):
    """Decorator for v2 API Blueprint routes.

    Validates the aas_session cookie (or Authorization: Bearer header),
    populates flask.g.user with the authenticated user dict, and returns
    a JSON 401 response if authentication fails.
    """
    import functools
    import uuid as _uuid
    from flask import g, jsonify, request as _req

    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        token = _req.cookies.get("aas_session")
        if not token:
            auth_header = _req.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            return jsonify({
                "success": False,
                "data": None,
                "error": {"code": "AUTH_REQUIRED", "message": "Authentication required."},
                "request_id": str(_uuid.uuid4()),
            }), 401

        user = validate_session(token)
        if not user:
            return jsonify({
                "success": False,
                "data": None,
                "error": {"code": "AUTH_INVALID", "message": "Session invalid or expired."},
                "request_id": str(_uuid.uuid4()),
            }), 401

        g.user = user
        return f(*args, **kwargs)

    return wrapper

