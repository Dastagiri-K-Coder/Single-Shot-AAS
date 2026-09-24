# -*- coding: utf-8 -*-
"""
outbox.py — Durable synchronization outbox for Single Shot AAS v2.5.

Implements the sync_outbox table operations described in §14.4 and §17.

The outbox is the durable bridge between local attendance and Google Sheets.
Once an event is written to the outbox, Google sync failure cannot cause
attendance data loss — the outbox entry persists and is retried by the
sync worker until SYNCHRONIZED or PERMANENT_FAILURE.

Outbox status flow (§17):
    PENDING → PROCESSING → SYNCHRONIZED
                        ↘ RETRY_WAIT → PROCESSING
                                    ↘ PERMANENT_FAILURE
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aas.core.db import get_db_connection

MAX_RETRY_ATTEMPTS = 10
BASE_BACKOFF_SECONDS = 30


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_retry_at(attempt_count: int) -> str:
    """Exponential backoff: 30s * 2^attempt, capped at 1 hour."""
    delay = min(BASE_BACKOFF_SECONDS * (2 ** attempt_count), 3600)
    next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    return next_at.isoformat()


class SyncOutbox:
    """CRUD operations for the sync_outbox table."""

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def create_event(
        self,
        *,
        session_id: str,
        operation: str,
        target_type: str = "",
        target_id: str = "",
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> str:
        """Insert a new PENDING outbox event.

        Args:
            session_id:       Owning attendance session.
            operation:        Operation type (e.g. 'MARK_ATTENDANCE').
            target_type:      Target kind (e.g. 'google_sheet').
            target_id:        Target identifier (e.g. camera_id / sheet_id).
            payload:          Dict to serialize as JSON payload.
            idempotency_key:  Unique key ensuring only one event per logical op.

        Returns:
            event_id (UUID string).
        """
        event_id = str(uuid.uuid4())
        now = _utcnow()
        conn = get_db_connection()
        conn.execute(
            """INSERT OR IGNORE INTO sync_outbox (
                event_id, session_id, operation,
                target_type, target_id,
                payload_json, idempotency_key,
                status, attempt_count,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, session_id, operation,
                target_type, target_id,
                json.dumps(payload), idempotency_key,
                "PENDING", 0, now,
            ),
        )
        conn.commit()
        return event_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_event(self, event_id: str) -> Optional[dict[str, Any]]:
        """Return a single outbox event dict, or None."""
        conn = get_db_connection()
        row = conn.execute(
            "SELECT * FROM sync_outbox WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_pending_events(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return PENDING events ready for processing.

        Respects next_attempt_at so that backoff events are not returned
        until their scheduled retry time has elapsed.
        """
        now = _utcnow()
        conn = get_db_connection()
        rows = conn.execute(
            """SELECT * FROM sync_outbox
               WHERE status IN ('PENDING', 'RETRY_WAIT')
                 AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
               ORDER BY created_at ASC
               LIMIT ?""",
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events_for_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return all outbox events for a session."""
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM sync_outbox WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_overall_status(self) -> dict[str, int]:
        """Return counts by status for observability / health."""
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM sync_outbox GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def mark_processing(self, event_id: str) -> None:
        """Set event to PROCESSING (picked up by sync worker)."""
        conn = get_db_connection()
        conn.execute(
            """UPDATE sync_outbox
               SET status = 'PROCESSING', last_attempt_at = ?
               WHERE event_id = ?""",
            (_utcnow(), event_id),
        )
        conn.commit()

    def mark_synchronized(self, event_id: str) -> None:
        """Mark event as successfully synchronized with Google Sheets/Drive."""
        now = _utcnow()
        conn = get_db_connection()
        conn.execute(
            """UPDATE sync_outbox
               SET status = 'SYNCHRONIZED', synchronized_at = ?, last_attempt_at = ?,
                   last_error = NULL
               WHERE event_id = ?""",
            (now, now, event_id),
        )
        # Update owning session
        row = conn.execute(
            "SELECT session_id FROM sync_outbox WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE attendance_sessions
                   SET sync_status = 'SYNCHRONIZED', synchronized_at = ?, updated_at = ?
                   WHERE session_id = ?""",
                (now, now, row["session_id"]),
            )
        conn.commit()

    def mark_retry(self, event_id: str, error: str, attempt_count: int) -> None:
        """Schedule a retry with exponential backoff."""
        new_attempt = attempt_count + 1
        if new_attempt >= MAX_RETRY_ATTEMPTS:
            self.mark_permanent_failure(event_id, error)
            return

        next_at = _next_retry_at(new_attempt)
        conn = get_db_connection()
        conn.execute(
            """UPDATE sync_outbox
               SET status = 'RETRY_WAIT', attempt_count = ?,
                   next_attempt_at = ?, last_error = ?, last_attempt_at = ?
               WHERE event_id = ?""",
            (new_attempt, next_at, error, _utcnow(), event_id),
        )
        conn.commit()

    def mark_permanent_failure(self, event_id: str, error: str) -> None:
        """Mark event as permanently failed after exceeding retry limit."""
        now = _utcnow()
        conn = get_db_connection()
        conn.execute(
            """UPDATE sync_outbox
               SET status = 'PERMANENT_FAILURE', last_error = ?, last_attempt_at = ?
               WHERE event_id = ?""",
            (error, now, event_id),
        )
        row = conn.execute(
            "SELECT session_id FROM sync_outbox WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE attendance_sessions
                   SET sync_status = 'PERMANENT_FAILURE', last_error = ?, updated_at = ?
                   WHERE session_id = ?""",
                (error, now, row["session_id"]),
            )
        conn.commit()

    def retry_event_manually(self, event_id: str) -> bool:
        """Reset a PERMANENT_FAILURE or RETRY_WAIT event back to PENDING.

        Returns:
            True if reset succeeded, False if event not found.
        """
        conn = get_db_connection()
        result = conn.execute(
            """UPDATE sync_outbox
               SET status = 'PENDING', next_attempt_at = NULL, last_error = NULL
               WHERE event_id = ? AND status IN ('PERMANENT_FAILURE', 'RETRY_WAIT')""",
            (event_id,),
        )
        conn.commit()
        return result.rowcount > 0
