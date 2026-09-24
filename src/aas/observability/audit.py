# -*- coding: utf-8 -*-
"""
audit.py — Structured observability events for Single Shot AAS v2.5.

Implements the event catalogue defined in §24 of the technical paper.
Extends the existing audit_log table with structured event emission.

Events are persisted to audit_log and emitted to the Python logging system.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from aas.core.db import get_db_connection

log = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Event Catalogue (§24) ─────────────────────────────────────────────────────

class AuditEvent:
    # Authentication
    AUTH_LOGIN      = "AUTH_LOGIN"
    AUTH_FAILURE    = "AUTH_FAILURE"

    # Session lifecycle
    SESSION_CREATED = "SESSION_CREATED"
    IMAGE_RECEIVED  = "IMAGE_RECEIVED"
    IMAGE_REJECTED  = "IMAGE_REJECTED"

    # Recognition
    RECOGNITION_STARTED   = "RECOGNITION_STARTED"
    RECOGNITION_COMPLETED = "RECOGNITION_COMPLETED"

    # Human review
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"

    # Finalization
    SESSION_FINALIZED = "SESSION_FINALIZED"
    LOCAL_COMMIT      = "LOCAL_COMMIT"

    # Sync
    SYNC_STARTED = "SYNC_STARTED"
    SYNC_SUCCESS = "SYNC_SUCCESS"
    SYNC_FAILURE = "SYNC_FAILURE"

    # Hardware
    CAMERA_FAILURE    = "CAMERA_FAILURE"
    SYSTEM_RECOVERY   = "SYSTEM_RECOVERY"


# ── Severity Levels ───────────────────────────────────────────────────────────

class Severity:
    DEBUG   = "DEBUG"
    INFO    = "INFO"
    WARNING = "WARNING"
    ERROR   = "ERROR"
    CRITICAL = "CRITICAL"


# ── Core Emit ─────────────────────────────────────────────────────────────────

def emit(
    action: str,
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    severity: str = Severity.INFO,
    message: str = "",
    ip_address: str = "",
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    """Emit a structured audit event.

    Persists to audit_log table and logs to Python logger.

    Args:
        action:     One of AuditEvent.* constants.
        user_id:    Acting user.
        session_id: Associated attendance session.
        camera_id:  Associated camera.
        severity:   One of Severity.* constants.
        message:    Human-readable event description.
        ip_address: Client IP address.
        metadata:   Additional structured data dict.

    Returns:
        event_id (UUID string).
    """
    event_id = str(uuid.uuid4())
    now = _utcnow()

    details_dict: dict[str, Any] = {
        "event_id": event_id,
        "severity": severity,
        "message": message,
    }
    if session_id:
        details_dict["session_id"] = session_id
    if camera_id:
        details_dict["camera_id"] = camera_id
    if metadata:
        details_dict["metadata"] = metadata

    details_json = json.dumps(details_dict)

    # Persist to existing audit_log table
    try:
        conn = get_db_connection()
        conn.execute(
            """INSERT INTO audit_log (timestamp, user_id, action, details, ip_address)
               VALUES (?, ?, ?, ?, ?)""",
            (now, user_id or "", action, details_json, ip_address),
        )
        conn.commit()
    except Exception as exc:
        log.error("[Audit] Failed to persist audit event: %s", exc)

    # Also emit to Python logger
    log_level = {
        Severity.DEBUG:    logging.DEBUG,
        Severity.INFO:     logging.INFO,
        Severity.WARNING:  logging.WARNING,
        Severity.ERROR:    logging.ERROR,
        Severity.CRITICAL: logging.CRITICAL,
    }.get(severity, logging.INFO)

    log.log(
        log_level,
        "[%s] user=%s session=%s camera=%s | %s",
        action,
        user_id or "-",
        session_id or "-",
        camera_id or "-",
        message or action,
    )

    return event_id


# ── Convenience wrappers for common events ────────────────────────────────────

def auth_login(user_id: str, ip_address: str = "") -> str:
    return emit(AuditEvent.AUTH_LOGIN, user_id=user_id,
                message=f"Successful login for {user_id}", ip_address=ip_address)


def auth_failure(user_id: str, ip_address: str = "", reason: str = "") -> str:
    return emit(AuditEvent.AUTH_FAILURE, user_id=user_id,
                severity=Severity.WARNING,
                message=f"Login failure for {user_id}: {reason}",
                ip_address=ip_address)


def session_created(session_id: str, user_id: str, camera_id: str) -> str:
    return emit(AuditEvent.SESSION_CREATED, user_id=user_id,
                session_id=session_id, camera_id=camera_id,
                message=f"Attendance session created: {session_id}")


def image_received(session_id: str, user_id: str, image_path: str) -> str:
    return emit(AuditEvent.IMAGE_RECEIVED, user_id=user_id,
                session_id=session_id,
                message=f"Image received: {image_path}",
                metadata={"image_path": image_path})


def image_rejected(session_id: str, user_id: str, reason: str) -> str:
    return emit(AuditEvent.IMAGE_REJECTED, user_id=user_id,
                session_id=session_id, severity=Severity.WARNING,
                message=f"Image rejected: {reason}",
                metadata={"reason": reason})


def recognition_started(session_id: str, job_id: str, camera_id: str) -> str:
    return emit(AuditEvent.RECOGNITION_STARTED,
                session_id=session_id, camera_id=camera_id,
                message=f"Recognition job started: {job_id}",
                metadata={"job_id": job_id})


def recognition_completed(
    session_id: str,
    job_id: str,
    recognized: int,
    unknown: int,
    low_res: int,
) -> str:
    return emit(AuditEvent.RECOGNITION_COMPLETED,
                session_id=session_id,
                message=f"Recognition complete: {recognized} recognized, {unknown} unknown",
                metadata={"job_id": job_id, "recognized": recognized,
                          "unknown": unknown, "low_res": low_res})


def manual_override(
    session_id: str,
    user_id: str,
    level: str,
    student_name: str,
    new_status: str,
) -> str:
    return emit(AuditEvent.MANUAL_OVERRIDE, user_id=user_id,
                session_id=session_id,
                message=f"{level} override: {student_name} → {new_status}",
                metadata={"level": level, "student": student_name, "status": new_status})


def session_finalized(session_id: str, user_id: str, record_count: int) -> str:
    return emit(AuditEvent.SESSION_FINALIZED, user_id=user_id,
                session_id=session_id,
                message=f"Session finalized with {record_count} records")


def local_commit(session_id: str, user_id: str) -> str:
    return emit(AuditEvent.LOCAL_COMMIT, user_id=user_id,
                session_id=session_id,
                message=f"Local SQLite commit completed for session {session_id}")


def sync_started(session_id: str, event_id: str) -> str:
    return emit(AuditEvent.SYNC_STARTED, session_id=session_id,
                message=f"Google sync started for event {event_id}",
                metadata={"event_id": event_id})


def sync_success(session_id: str, event_id: str) -> str:
    return emit(AuditEvent.SYNC_SUCCESS, session_id=session_id,
                message=f"Google sync succeeded for event {event_id}",
                metadata={"event_id": event_id})


def sync_failure(session_id: str, event_id: str, error: str, attempt: int) -> str:
    return emit(AuditEvent.SYNC_FAILURE, session_id=session_id,
                severity=Severity.WARNING,
                message=f"Google sync failed (attempt {attempt}): {error[:200]}",
                metadata={"event_id": event_id, "attempt": attempt, "error": error[:500]})


def camera_failure(camera_id: str, error: str) -> str:
    return emit(AuditEvent.CAMERA_FAILURE, camera_id=camera_id,
                severity=Severity.ERROR,
                message=f"Camera failure: {error}",
                metadata={"error": error})


def system_recovery(detail: str) -> str:
    return emit(AuditEvent.SYSTEM_RECOVERY,
                severity=Severity.WARNING,
                message=f"System recovery: {detail}")
