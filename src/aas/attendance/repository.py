# -*- coding: utf-8 -*-
"""
repository.py — Attendance repository for Single Shot AAS v2.5.

Implements the durable local commit transaction described in §15:

    BEGIN TRANSACTION
    1. Verify session ownership.
    2. Verify session state.
    3. Validate attendance records.
    4. Persist final session state.
    5. Persist student attendance records.
    6. Create synchronization outbox event.
    7. Mark session LOCAL_COMMITTED.
    COMMIT

    If any operation fails: ROLLBACK.

Only after local commit succeeds is the user told that attendance has been saved.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from aas.attendance.records import AttendanceRecord
from aas.attendance.session import AttendanceSession, SessionNotFoundError, SessionOwnershipError
from aas.attendance.state_machine import (
    AttendanceStateError,
    SessionState,
    is_locally_committed,
    validate_transition,
)
from aas.core.db import get_db_connection


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class AttendanceRepository:
    """Coordinates the durable finalization transaction (§15)."""

    # ------------------------------------------------------------------
    # Core durable commit — §15
    # ------------------------------------------------------------------

    def finalize_and_commit(
        self,
        *,
        session_id: str,
        requesting_user_id: str,
        records: list[AttendanceRecord],
    ) -> AttendanceSession:
        """Execute the atomic finalization transaction.

        Steps per §15:
          1. Verify ownership.
          2. Verify state (must be HUMAN_REVIEW or FINALIZED).
          3. Validate records list is non-empty.
          4. BEGIN TRANSACTION.
          5. Persist session → FINALIZED.
          6. Persist attendance_records rows.
          7. Create sync_outbox event.
          8. Mark session → LOCAL_COMMITTED.
          COMMIT.

        Args:
            session_id:          Target session.
            requesting_user_id:  Must match session.faculty_user_id.
            records:             List of AttendanceRecord objects to persist.

        Returns:
            Updated AttendanceSession in LOCAL_COMMITTED state.

        Raises:
            SessionNotFoundError: Session does not exist.
            SessionOwnershipError: Requesting user does not own the session.
            AttendanceStateError: Session is in an illegal state.
            ValueError: Records list is empty.
        """
        conn = get_db_connection()

        # ── 1. Load and verify ownership ──────────────────────────────
        row = conn.execute(
            "SELECT * FROM attendance_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)

        session_dict = dict(row)
        if session_dict["faculty_user_id"] != requesting_user_id:
            raise SessionOwnershipError(session_id, requesting_user_id)

        # ── 2. Verify state ────────────────────────────────────────────
        current_state = SessionState(session_dict["status"])

        # Idempotency guard (§16): already committed → return existing result
        if is_locally_committed(current_state):
            session_dict["status"] = current_state
            return self._session_from_dict(session_dict)

        # Must be in HUMAN_REVIEW to finalize
        validate_transition(current_state, SessionState.FINALIZED)

        # ── 3. Validate records ────────────────────────────────────────
        if not records:
            raise ValueError("Cannot finalize: attendance records list is empty.")

        # ── 4-8. Atomic SQLite transaction ─────────────────────────────
        now = _utcnow()
        event_id = str(uuid.uuid4())
        idempotency_key = f"session:{session_id}:finalize"

        # Build outbox payload
        payload = {
            "session_id": session_id,
            "camera_id": session_dict["camera_id"],
            "section_code": session_dict["section_code"],
            "subject": session_dict["subject"],
            "subject_abbr": session_dict["subject_abbr"],
            "period": session_dict["period"],
            "attendance_date": session_dict["attendance_date"],
            "records": [r.to_dict() for r in records],
        }

        try:
            conn.execute("BEGIN")

            # 5. Session → FINALIZED
            conn.execute(
                """UPDATE attendance_sessions
                   SET status = ?, updated_at = ?, finalized_at = ?
                   WHERE session_id = ?""",
                (SessionState.FINALIZED.value, now, now, session_id),
            )

            # 6. Persist attendance records
            for record in records:
                conn.execute(
                    """INSERT OR REPLACE INTO attendance_records (
                        session_id, student_name, student_email,
                        status, source, confidence, detection_status,
                        face_width, face_height, ipd,
                        modified_by, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        record.student_name,
                        record.student_email,
                        record.status,
                        record.source,
                        record.confidence,
                        record.detection_status,
                        record.face_width,
                        record.face_height,
                        record.ipd,
                        record.modified_by,
                        record.created_at or now,
                        now,
                    ),
                )

            # 7. Create sync outbox event (idempotency_key ensures uniqueness)
            conn.execute(
                """INSERT OR IGNORE INTO sync_outbox (
                    event_id, session_id, operation,
                    target_type, target_id,
                    payload_json, idempotency_key,
                    status, attempt_count,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event_id,
                    session_id,
                    "MARK_ATTENDANCE",
                    "google_sheet",
                    session_dict.get("camera_id", ""),
                    json.dumps(payload),
                    idempotency_key,
                    "PENDING",
                    0,
                    now,
                ),
            )

            # 8. Session → LOCAL_COMMITTED
            conn.execute(
                """UPDATE attendance_sessions
                   SET status = ?, local_committed_at = ?, sync_status = ?, updated_at = ?
                   WHERE session_id = ?""",
                (SessionState.LOCAL_COMMITTED.value, now, "PENDING", now, session_id),
            )

            conn.execute("COMMIT")

        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Re-load and return committed session
        row = conn.execute(
            "SELECT * FROM attendance_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return self._session_from_dict(dict(row))

    # ------------------------------------------------------------------
    # Record queries
    # ------------------------------------------------------------------

    def get_records(self, session_id: str) -> list[AttendanceRecord]:
        """Return all attendance records for *session_id*."""
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM attendance_records WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [self._record_from_row(r) for r in rows]

    def update_record_status(
        self,
        session_id: str,
        student_name: str,
        new_status: str,
        source: str,
        modified_by: str,
    ) -> None:
        """Update a single student's attendance status (L1 manual toggle)."""
        now = _utcnow()
        conn = get_db_connection()
        conn.execute(
            """UPDATE attendance_records
               SET status = ?, source = ?, modified_by = ?, updated_at = ?
               WHERE session_id = ? AND student_name = ?""",
            (new_status, source, modified_by, now, session_id, student_name),
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _session_from_dict(d: dict[str, Any]) -> AttendanceSession:
        from aas.attendance.session import AttendanceSession
        d["status"] = SessionState(d["status"])
        return AttendanceSession(**d)

    @staticmethod
    def _record_from_row(row: Any) -> AttendanceRecord:
        return AttendanceRecord(**dict(row))
