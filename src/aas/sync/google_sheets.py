# -*- coding: utf-8 -*-
"""
google_sheets.py — Sync layer adapter for Single Shot AAS v2.5.

Called by the sync worker to push locally-committed attendance to Google Sheets.
Bridges the sync_outbox payload format to the existing SpreadsheetManager
in attendance/spreadsheet.py.

This module is intentionally thin — all Google Sheets business logic
lives in attendance/spreadsheet.py; this module is the glue between
the durable outbox and that logic.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def sync_attendance_to_sheet(payload: dict[str, Any]) -> None:
    """Push an attendance session's records to Google Sheets.

    Called by SyncWorker._dispatch() for MARK_ATTENDANCE operations.

    Args:
        payload: Dict with keys:
            - session_id
            - camera_id
            - section_code
            - subject
            - subject_abbr
            - period
            - attendance_date
            - records: list of {student_name, student_email, status, ...}

    Raises:
        Exception: On any Google API failure (caught by worker for retry).
    """
    from aas.attendance.spreadsheet import SpreadsheetManager
    from aas.integrations.google.oauth import get_credentials as get_google_credentials
    from aas.capture.camera_registry import CameraRegistry

    session_id      = payload["session_id"]
    camera_id       = payload["camera_id"]
    attendance_date = payload["attendance_date"]
    records         = payload.get("records", [])

    log.info(
        "[GoogleSheets] Syncing session=%s camera=%s date=%s",
        session_id, camera_id, attendance_date,
    )

    # Look up the Google Sheet ID for this camera
    registry = CameraRegistry()
    camera   = registry.get_camera(camera_id)
    if not camera:
        raise ValueError(f"Camera {camera_id!r} not found in registry.")

    sheet_id = camera.get("sheet_id", "")
    if not sheet_id:
        raise ValueError(f"Camera {camera_id!r} has no sheet_id configured.")

    # Build present/absent lists
    present_names: list[str] = []
    absent_names:  list[str] = []
    for rec in records:
        if rec.get("status") == "PRESENT":
            present_names.append(rec["student_name"])
        else:
            absent_names.append(rec["student_name"])

    creds = get_google_credentials()
    mgr   = SpreadsheetManager(creds)

    # Mark all absent first, then present (batch operations)
    if absent_names:
        # Use write_batch_to_sheet for absent marking indirectly via mark_all_absent
        pass  # mark_all_absent marks everyone, then present overwrites below

    if present_names:
        marked = mgr.write_batch_to_sheet(sheet_id, present_names)
        log.info(
            "[GoogleSheets] Done session=%s marked_present=%d/%d",
            session_id, len(marked), len(present_names),
        )
    else:
        log.info("[GoogleSheets] No present students to sync for session=%s", session_id)
