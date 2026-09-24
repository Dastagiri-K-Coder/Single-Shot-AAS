# -*- coding: utf-8 -*-
"""
overrides.py — Three-level attendance fallback for Single Shot AAS v2.5.

Implements the three correction levels defined in §9:
    L1 — Manual Toggle (small discrepancies / missed students)
    L2 — Individual Close-Up Retake
    L3 — Bulk Manual Addition

All override operations require the session to be in HUMAN_REVIEW state.
Each correction is provenance-tracked via the AttendanceRecord.source field.
"""

from __future__ import annotations

from typing import Any, Optional

from aas.attendance.records import (
    AttendanceRecord,
    RecordSource,
    RecordStatus,
    records_from_bulk_add,
    record_from_individual_retake,
    record_from_manual_toggle,
)
from aas.attendance.session import AttendanceSession, SessionService
from aas.attendance.state_machine import SessionState
from aas.core.db import get_db_connection


def _utcnow() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class OverrideService:
    """Handles all three attendance fallback levels (§9)."""

    def __init__(self, session_service: Optional[SessionService] = None) -> None:
        self._session_svc = session_service or SessionService()

    # ------------------------------------------------------------------
    # L1 — Manual Toggle
    # ------------------------------------------------------------------

    def l1_toggle(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        student_name: str,
        new_status: str,        # PRESENT | ABSENT
    ) -> AttendanceRecord:
        """Toggle a student's attendance status manually (L1).

        Args:
            session_id: Target session.
            requesting_user_id: Faculty performing the toggle.
            student_name: Student to toggle.
            new_status: 'PRESENT' or 'ABSENT'.

        Returns:
            Upserted AttendanceRecord.

        Raises:
            SessionStateError: If session is not in HUMAN_REVIEW.
            ValueError: If new_status is invalid.
        """
        self._assert_human_review(session_id, requesting_user_id)

        if new_status not in (RecordStatus.PRESENT, RecordStatus.ABSENT):
            raise ValueError(f"Invalid status: {new_status!r}")

        conn = get_db_connection()
        now = _utcnow()

        # Check if record exists
        existing = conn.execute(
            "SELECT id FROM attendance_records WHERE session_id = ? AND student_name = ?",
            (session_id, student_name),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE attendance_records
                   SET status = ?, source = ?, modified_by = ?, updated_at = ?
                   WHERE session_id = ? AND student_name = ?""",
                (new_status, RecordSource.MANUAL_L1, requesting_user_id, now,
                 session_id, student_name),
            )
        else:
            record = record_from_manual_toggle(
                session_id=session_id,
                student_name=student_name,
                new_status=new_status,
                modified_by=requesting_user_id,
            )
            conn.execute(
                """INSERT INTO attendance_records
                   (session_id, student_name, student_email, status, source,
                    confidence, detection_status, face_width, face_height, ipd,
                    modified_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, record.student_name, record.student_email,
                 record.status, record.source, record.confidence,
                 record.detection_status, record.face_width, record.face_height,
                 record.ipd, record.modified_by, record.created_at, record.updated_at),
            )

        # Increment session override counter
        conn.execute(
            """UPDATE attendance_sessions
               SET manual_override_count = manual_override_count + 1, updated_at = ?
               WHERE session_id = ?""",
            (now, session_id),
        )
        conn.commit()

        # Return updated record
        row = conn.execute(
            "SELECT * FROM attendance_records WHERE session_id = ? AND student_name = ?",
            (session_id, student_name),
        ).fetchone()
        return AttendanceRecord(**dict(row))

    # ------------------------------------------------------------------
    # L2 — Individual Close-Up Retake
    # ------------------------------------------------------------------

    def l2_individual_retake(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        student_name: str,
        student_email: str = "",
        confidence: float = 0.0,
        detection_status: str = "valid",
        face_width: int = 0,
        face_height: int = 0,
        ipd: int = 0,
    ) -> AttendanceRecord:
        """Mark a student PRESENT after individual close-up retake (L2).

        The recognition engine may be restricted to this student's
        encodings during the retake (handled at the caller/CV level).

        Args:
            session_id: Target session.
            requesting_user_id: Faculty performing the retake.
            student_name: Identified student.
            student_email: Student email (optional).
            confidence: Recognition confidence from retake.
            detection_status: Face detection quality status.
            face_width: Detected face width in pixels.
            face_height: Detected face height in pixels.
            ipd: Inter-pupillary distance in pixels.

        Returns:
            Upserted AttendanceRecord.
        """
        self._assert_human_review(session_id, requesting_user_id)

        conn = get_db_connection()
        now = _utcnow()

        existing = conn.execute(
            "SELECT id FROM attendance_records WHERE session_id = ? AND student_name = ?",
            (session_id, student_name),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE attendance_records
                   SET status = ?, source = ?, confidence = ?, detection_status = ?,
                       face_width = ?, face_height = ?, ipd = ?,
                       modified_by = ?, updated_at = ?
                   WHERE session_id = ? AND student_name = ?""",
                (RecordStatus.PRESENT, RecordSource.INDIVIDUAL_L2,
                 confidence, detection_status, face_width, face_height, ipd,
                 requesting_user_id, now, session_id, student_name),
            )
        else:
            record = record_from_individual_retake(
                session_id=session_id,
                student_name=student_name,
                student_email=student_email,
                confidence=confidence,
                detection_status=detection_status,
                face_width=face_width,
                face_height=face_height,
                ipd=ipd,
                modified_by=requesting_user_id,
            )
            conn.execute(
                """INSERT INTO attendance_records
                   (session_id, student_name, student_email, status, source,
                    confidence, detection_status, face_width, face_height, ipd,
                    modified_by, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (session_id, record.student_name, record.student_email,
                 record.status, record.source, record.confidence,
                 record.detection_status, record.face_width, record.face_height,
                 record.ipd, record.modified_by, record.created_at, record.updated_at),
            )

        conn.execute(
            """UPDATE attendance_sessions
               SET manual_override_count = manual_override_count + 1, updated_at = ?
               WHERE session_id = ?""",
            (now, session_id),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM attendance_records WHERE session_id = ? AND student_name = ?",
            (session_id, student_name),
        ).fetchone()
        return AttendanceRecord(**dict(row))

    # ------------------------------------------------------------------
    # L3 — Bulk Manual Addition
    # ------------------------------------------------------------------

    def l3_bulk_add(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        students: list[dict[str, str]],
    ) -> list[AttendanceRecord]:
        """Mark multiple students PRESENT via bulk addition (L3).

        Args:
            session_id: Target session.
            requesting_user_id: Faculty performing the bulk add.
            students: List of {"name": ..., "email": ...} dicts.

        Returns:
            List of upserted AttendanceRecord objects.
        """
        self._assert_human_review(session_id, requesting_user_id)

        records = records_from_bulk_add(
            session_id=session_id,
            students=students,
            modified_by=requesting_user_id,
        )

        conn = get_db_connection()
        now = _utcnow()

        for record in records:
            existing = conn.execute(
                "SELECT id FROM attendance_records WHERE session_id = ? AND student_name = ?",
                (session_id, record.student_name),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE attendance_records
                       SET status = ?, source = ?, modified_by = ?, updated_at = ?
                       WHERE session_id = ? AND student_name = ?""",
                    (RecordStatus.PRESENT, RecordSource.BULK_L3,
                     requesting_user_id, now, session_id, record.student_name),
                )
            else:
                conn.execute(
                    """INSERT INTO attendance_records
                       (session_id, student_name, student_email, status, source,
                        confidence, detection_status, face_width, face_height, ipd,
                        modified_by, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (session_id, record.student_name, record.student_email,
                     record.status, record.source, record.confidence,
                     record.detection_status, record.face_width, record.face_height,
                     record.ipd, record.modified_by, record.created_at, record.updated_at),
                )

        conn.execute(
            """UPDATE attendance_sessions
               SET manual_override_count = manual_override_count + ?, updated_at = ?
               WHERE session_id = ?""",
            (len(records), now, session_id),
        )
        conn.commit()

        rows = conn.execute(
            "SELECT * FROM attendance_records WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [AttendanceRecord(**dict(r)) for r in rows]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _assert_human_review(self, session_id: str, user_id: str) -> None:
        """Raise if session is not in HUMAN_REVIEW or user doesn't own it."""
        conn = get_db_connection()
        row = conn.execute(
            "SELECT status, faculty_user_id FROM attendance_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            from aas.attendance.session import SessionNotFoundError
            raise SessionNotFoundError(session_id)

        if row["faculty_user_id"] != user_id:
            from aas.attendance.session import SessionOwnershipError
            raise SessionOwnershipError(session_id, user_id)

        if row["status"] != SessionState.HUMAN_REVIEW.value:
            from aas.attendance.state_machine import AttendanceStateError
            raise AttendanceStateError(
                SessionState(row["status"]),
                SessionState.HUMAN_REVIEW,
            )
