# -*- coding: utf-8 -*-
"""
session.py — Attendance session management for Single Shot AAS v2.5.

Implements the AttendanceSession domain object and the session lifecycle
defined in §13 and §14.1 of the technical paper.

Each session represents one "take attendance" event:
    Faculty opens camera → uploads classroom image → CV recognizes faces →
    Human reviews → Finalizes → Local SQLite commit → Sync outbox → Google Sheets.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from aas.attendance.state_machine import (
    AttendanceStateError,
    SessionState,
    validate_transition,
)
from aas.core.db import get_db_connection


def _utcnow() -> str:
    """Return current UTC timestamp as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ── Domain Object ─────────────────────────────────────────────────────────────

@dataclass
class AttendanceSession:
    """Represents a single attendance capture event (§14.1)."""
    session_id:                 str
    camera_id:                  str
    faculty_user_id:            str
    section_code:               str
    attendance_date:            str
    started_at:                 str
    updated_at:                 str

    subject:                    str = ""
    subject_abbr:               str = ""
    period:                     str = ""
    source_mode:                str = "MOBILE_UPLOAD"
    status:                     SessionState = SessionState.SESSION_CREATED

    image_path:                 Optional[str] = None
    recognized_count:           int = 0
    unknown_count:              int = 0
    low_res_count:              int = 0
    manual_override_count:      int = 0
    total_faces:                int = 0

    recognition_model:          str = ""
    recognition_model_version:  str = ""
    recognition_config_version: str = ""

    finalized_at:               Optional[str] = None
    local_committed_at:         Optional[str] = None
    synchronized_at:            Optional[str] = None
    sync_status:                str = "PENDING"
    last_error:                 Optional[str] = None

    def transition_to(self, new_state: SessionState) -> None:
        """Validate and apply a state transition.

        Raises:
            AttendanceStateError: if the transition is illegal.
        """
        validate_transition(self.status, new_state)
        self.status = new_state
        self.updated_at = _utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable dict of this session."""
        return {
            "session_id": self.session_id,
            "camera_id": self.camera_id,
            "faculty_user_id": self.faculty_user_id,
            "section_code": self.section_code,
            "subject": self.subject,
            "subject_abbr": self.subject_abbr,
            "period": self.period,
            "attendance_date": self.attendance_date,
            "source_mode": self.source_mode,
            "status": self.status.value,
            "image_path": self.image_path,
            "recognized_count": self.recognized_count,
            "unknown_count": self.unknown_count,
            "low_res_count": self.low_res_count,
            "manual_override_count": self.manual_override_count,
            "total_faces": self.total_faces,
            "recognition_model": self.recognition_model,
            "recognition_model_version": self.recognition_model_version,
            "recognition_config_version": self.recognition_config_version,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finalized_at": self.finalized_at,
            "local_committed_at": self.local_committed_at,
            "synchronized_at": self.synchronized_at,
            "sync_status": self.sync_status,
            "last_error": self.last_error,
        }


# ── Session Service ───────────────────────────────────────────────────────────

class SessionService:
    """Business logic for creating and managing attendance sessions."""

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_session(
        self,
        *,
        camera_id: str,
        faculty_user_id: str,
        section_code: str,
        subject: str = "",
        subject_abbr: str = "",
        period: str = "",
        attendance_date: Optional[str] = None,
        source_mode: str = "MOBILE_UPLOAD",
        recognition_model: str = "",
        recognition_model_version: str = "",
        recognition_config_version: str = "",
    ) -> AttendanceSession:
        """Create, persist, and return a new attendance session.

        Args:
            camera_id:   ID of the camera/section being used.
            faculty_user_id: Logged-in faculty user_id.
            section_code: Class section code (e.g. "CSE-A").
            subject:     Full subject name.
            subject_abbr: Abbreviated subject name for sheet column header.
            period:      Period number/name.
            attendance_date: ISO date string (defaults to today).
            source_mode: Capture mode (MOBILE_UPLOAD, RTSP, WEBCAM, IP_CAMERA).
            recognition_model: Model identifier string.
            recognition_model_version: Model version string.
            recognition_config_version: Config/encoding snapshot identifier.

        Returns:
            Persisted AttendanceSession.
        """
        now = _utcnow()
        session_id = str(uuid.uuid4())
        date_str = attendance_date or datetime.now(timezone.utc).date().isoformat()

        session = AttendanceSession(
            session_id=session_id,
            camera_id=camera_id,
            faculty_user_id=faculty_user_id,
            section_code=section_code,
            subject=subject,
            subject_abbr=subject_abbr,
            period=period,
            attendance_date=date_str,
            source_mode=source_mode,
            status=SessionState.SESSION_CREATED,
            started_at=now,
            updated_at=now,
            recognition_model=recognition_model,
            recognition_model_version=recognition_model_version,
            recognition_config_version=recognition_config_version,
        )
        self._persist(session)
        return session

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_session(self, session_id: str) -> Optional[AttendanceSession]:
        """Load a session from SQLite by session_id.

        Returns:
            AttendanceSession or None if not found.
        """
        conn = get_db_connection()
        row = conn.execute(
            "SELECT * FROM attendance_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return self._from_row(row)

    def get_session_required(self, session_id: str) -> AttendanceSession:
        """Load a session or raise SessionNotFoundError."""
        session = self.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(session_id)
        return session

    def list_sessions_for_faculty(
        self,
        faculty_user_id: str,
        date: Optional[str] = None,
        limit: int = 50,
    ) -> list[AttendanceSession]:
        """Return recent sessions for a faculty member.

        Args:
            faculty_user_id: The faculty's user_id.
            date: Optional ISO date filter.
            limit: Maximum rows to return.
        """
        conn = get_db_connection()
        if date:
            rows = conn.execute(
                """SELECT * FROM attendance_sessions
                   WHERE faculty_user_id = ? AND attendance_date = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (faculty_user_id, date, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM attendance_sessions
                   WHERE faculty_user_id = ?
                   ORDER BY started_at DESC LIMIT ?""",
                (faculty_user_id, limit),
            ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def set_image(self, session: AttendanceSession, image_path: str) -> None:
        """Record image receipt and advance state to IMAGE_RECEIVED."""
        session.image_path = image_path
        session.transition_to(SessionState.IMAGE_RECEIVED)
        self._update_fields(
            session,
            image_path=image_path,
            status=session.status.value,
            updated_at=session.updated_at,
        )

    def set_recognition_results(
        self,
        session: AttendanceSession,
        *,
        recognized_count: int = 0,
        unknown_count: int = 0,
        low_res_count: int = 0,
        total_faces: int = 0,
        recognition_model: str = "",
        recognition_model_version: str = "",
    ) -> None:
        """Record recognition output and advance to HUMAN_REVIEW."""
        session.recognized_count = recognized_count
        session.unknown_count = unknown_count
        session.low_res_count = low_res_count
        session.total_faces = total_faces
        if recognition_model:
            session.recognition_model = recognition_model
        if recognition_model_version:
            session.recognition_model_version = recognition_model_version

        session.transition_to(SessionState.HUMAN_REVIEW)
        self._update_fields(
            session,
            recognized_count=recognized_count,
            unknown_count=unknown_count,
            low_res_count=low_res_count,
            total_faces=total_faces,
            recognition_model=session.recognition_model,
            recognition_model_version=session.recognition_model_version,
            status=session.status.value,
            updated_at=session.updated_at,
        )

    def increment_manual_overrides(self, session: AttendanceSession, count: int = 1) -> None:
        """Increment the manual_override_count counter."""
        session.manual_override_count += count
        self._update_fields(
            session,
            manual_override_count=session.manual_override_count,
            updated_at=_utcnow(),
        )

    def set_error(self, session: AttendanceSession, error: str) -> None:
        """Record an error message without changing state."""
        session.last_error = error
        self._update_fields(session, last_error=error, updated_at=_utcnow())

    def cancel_session(self, session: AttendanceSession) -> None:
        """Cancel an in-progress session."""
        session.transition_to(SessionState.CANCELLED)
        self._update_fields(
            session,
            status=SessionState.CANCELLED.value,
            updated_at=session.updated_at,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _persist(self, session: AttendanceSession) -> None:
        """INSERT a new session row."""
        conn = get_db_connection()
        conn.execute(
            """INSERT INTO attendance_sessions (
                session_id, camera_id, faculty_user_id, section_code,
                subject, subject_abbr, period, attendance_date, source_mode,
                status, image_path,
                recognized_count, unknown_count, low_res_count,
                manual_override_count, total_faces,
                recognition_model, recognition_model_version, recognition_config_version,
                started_at, updated_at,
                finalized_at, local_committed_at, synchronized_at,
                sync_status, last_error
            ) VALUES (
                :session_id, :camera_id, :faculty_user_id, :section_code,
                :subject, :subject_abbr, :period, :attendance_date, :source_mode,
                :status, :image_path,
                :recognized_count, :unknown_count, :low_res_count,
                :manual_override_count, :total_faces,
                :recognition_model, :recognition_model_version, :recognition_config_version,
                :started_at, :updated_at,
                :finalized_at, :local_committed_at, :synchronized_at,
                :sync_status, :last_error
            )""",
            session.to_dict(),
        )
        conn.commit()

    def _update_fields(self, session: AttendanceSession, **kwargs: Any) -> None:
        """UPDATE individual columns for *session* by session_id."""
        if not kwargs:
            return
        conn = get_db_connection()
        set_clause = ", ".join(f"{k} = :{k}" for k in kwargs)
        kwargs["session_id"] = session.session_id
        conn.execute(
            f"UPDATE attendance_sessions SET {set_clause} WHERE session_id = :session_id",
            kwargs,
        )
        conn.commit()

    @staticmethod
    def _from_row(row: Any) -> AttendanceSession:
        """Build an AttendanceSession domain object from a sqlite3.Row."""
        d = dict(row)
        d["status"] = SessionState(d["status"])
        return AttendanceSession(**d)


# ── Exceptions ────────────────────────────────────────────────────────────────

class SessionNotFoundError(Exception):
    def __init__(self, session_id: str) -> None:
        super().__init__(f"Attendance session not found: {session_id}")
        self.session_id = session_id


class SessionOwnershipError(Exception):
    def __init__(self, session_id: str, user_id: str) -> None:
        super().__init__(
            f"User '{user_id}' does not own session '{session_id}'."
        )
