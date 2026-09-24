# -*- coding: utf-8 -*-
"""
attendance.py — v2 attendance session API routes for Single Shot AAS v2.5.

Implements all /api/v2/attendance/ endpoints defined in §20.1:

    POST   /api/v2/attendance/sessions
    GET    /api/v2/attendance/sessions/{id}
    POST   /api/v2/attendance/sessions/{id}/image
    GET    /api/v2/attendance/sessions/{id}/status
    GET    /api/v2/attendance/sessions/{id}/records
    POST   /api/v2/attendance/sessions/{id}/override
    POST   /api/v2/attendance/sessions/{id}/retry-student
    POST   /api/v2/attendance/sessions/{id}/finalize
    POST   /api/v2/attendance/sessions/{id}/cancel

HTTP handlers are thin — business logic is in service layer (§33 principle 11).
Response format follows §21 (success/error envelope with request_id).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request

from aas.attendance.overrides import OverrideService
from aas.attendance.records import RecordStatus
from aas.attendance.repository import AttendanceRepository
from aas.attendance.session import SessionNotFoundError, SessionOwnershipError, SessionService
from aas.attendance.state_machine import AttendanceStateError, SessionState
from aas.core.auth import login_required
from aas.observability import audit

log = logging.getLogger(__name__)

attendance_v2_bp = Blueprint("attendance_v2", __name__)

_session_svc   = SessionService()
_override_svc  = OverrideService()
_repo          = AttendanceRepository()


def _ok(data: dict, status: int = 200) -> tuple:
    return jsonify({
        "success": True,
        "data": data,
        "error": None,
        "request_id": str(uuid.uuid4()),
    }), status


def _err(code: str, message: str, status: int = 400) -> tuple:
    return jsonify({
        "success": False,
        "data": None,
        "error": {"code": code, "message": message},
        "request_id": str(uuid.uuid4()),
    }), status


# ── POST /api/v2/attendance/sessions ─────────────────────────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions", methods=["POST"])
@login_required
def create_session():
    """Create a new attendance session."""
    body = request.get_json(silent=True) or {}

    camera_id    = body.get("camera_id", "").strip()
    section_code = body.get("section_code", "").strip()
    subject      = body.get("subject", "").strip()
    subject_abbr = body.get("subject_abbr", "").strip()
    period       = body.get("period", "").strip()
    source_mode  = body.get("source_mode", "MOBILE_UPLOAD").strip()

    if not camera_id:
        return _err("VALIDATION_ERROR", "camera_id is required.", 400)
    if not section_code:
        return _err("VALIDATION_ERROR", "section_code is required.", 400)

    # RBAC: verify camera is assigned to this faculty
    user_id = g.user["user_id"]
    role    = g.user["role"]
    if role != "admin":
        assigned = g.user.get("assigned_cameras", "[]")
        import json
        cameras = json.loads(assigned) if isinstance(assigned, str) else assigned
        if camera_id not in cameras:
            return _err("CAMERA_NOT_ASSIGNED",
                        "You are not assigned to this camera.", 403)

    try:
        session = _session_svc.create_session(
            camera_id=camera_id,
            faculty_user_id=user_id,
            section_code=section_code,
            subject=subject,
            subject_abbr=subject_abbr,
            period=period,
            source_mode=source_mode,
        )
        audit.session_created(session.session_id, user_id, camera_id)
        return _ok(session.to_dict(), 201)
    except Exception as exc:
        log.exception("create_session failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


# ── GET /api/v2/attendance/sessions/<session_id> ──────────────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>", methods=["GET"])
@login_required
def get_session(session_id: str):
    """Get full session details by ID."""
    try:
        session = _session_svc.get_session_required(session_id)
        _assert_ownership(session)
        return _ok(session.to_dict())
    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)
    except Exception as exc:
        log.exception("get_session failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


# ── POST /api/v2/attendance/sessions/<session_id>/image ───────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>/image", methods=["POST"])
@login_required
def upload_image(session_id: str):
    """Upload classroom image for recognition (§19 upload security boundary)."""
    from aas.core.config import CONFIG_DIR

    # Load and verify session
    try:
        session = _session_svc.get_session_required(session_id)
        _assert_ownership(session)
    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)

    # Validate state
    if session.status not in (SessionState.SESSION_CREATED, SessionState.IMAGE_RECEIVED):
        return _err("SESSION_INVALID_STATE",
                    f"Cannot upload image in state {session.status.value}.", 409)

    # Content-Type validation (§19)
    if "file" not in request.files:
        return _err("IMAGE_MISSING", "No file part in request.", 400)

    file = request.files["file"]
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        return _err("IMAGE_INVALID",
                    f"Unsupported content type: {file.content_type}", 422)

    # Max size check: 20 MB
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 20 * 1024 * 1024:
        return _err("IMAGE_TOO_LARGE", "Image exceeds 20 MB limit.", 413)

    # Save to captured directory
    import imghdr
    captured_dir = os.path.join(
        os.path.dirname(os.path.dirname(CONFIG_DIR)), "captured"
    )
    os.makedirs(captured_dir, exist_ok=True)
    tmp_path  = os.path.join(captured_dir, f"tmp_{uuid.uuid4().hex}")
    final_path = os.path.join(captured_dir, f"session_{session_id}_{uuid.uuid4().hex}.jpg")

    file.save(tmp_path)

    # Verify it's actually an image (§19: decode check)
    detected = imghdr.what(tmp_path)
    if detected not in ("jpeg", "png", "webp"):
        os.unlink(tmp_path)
        return _err("IMAGE_INVALID", "File is not a valid image.", 422)

    os.rename(tmp_path, final_path)

    # Advance session state
    _session_svc.set_image(session, final_path)
    audit.image_received(session_id, g.user["user_id"], final_path)

    return _ok({"session_id": session_id, "image_path": final_path, "status": session.status.value})


# ── GET /api/v2/attendance/sessions/<session_id>/status ──────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>/status", methods=["GET"])
@login_required
def get_status(session_id: str):
    """Lightweight status poll (browser refresh recovery, §23)."""
    try:
        session = _session_svc.get_session_required(session_id)
        _assert_ownership(session)
        return _ok({
            "session_id": session_id,
            "status": session.status.value,
            "sync_status": session.sync_status,
            "updated_at": session.updated_at,
        })
    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)


# ── GET /api/v2/attendance/sessions/<session_id>/records ─────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>/records", methods=["GET"])
@login_required
def get_records(session_id: str):
    """Return all attendance records for a session."""
    try:
        session = _session_svc.get_session_required(session_id)
        _assert_ownership(session)
        records = _repo.get_records(session_id)
        return _ok({"records": [r.to_dict() for r in records]})
    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)


# ── POST /api/v2/attendance/sessions/<session_id>/override ───────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>/override", methods=["POST"])
@login_required
def override(session_id: str):
    """L1/L2/L3 attendance override (§9)."""
    body  = request.get_json(silent=True) or {}
    level = body.get("level", "L1").upper()
    user_id = g.user["user_id"]

    try:
        if level == "L1":
            student_name = body.get("student_name", "").strip()
            new_status   = body.get("status", "").upper()
            if not student_name:
                return _err("VALIDATION_ERROR", "student_name required.", 400)
            if new_status not in (RecordStatus.PRESENT, RecordStatus.ABSENT):
                return _err("VALIDATION_ERROR", "status must be PRESENT or ABSENT.", 400)
            rec = _override_svc.l1_toggle(
                session_id=session_id,
                requesting_user_id=user_id,
                student_name=student_name,
                new_status=new_status,
            )
            audit.manual_override(session_id, user_id, "L1", student_name, new_status)
            return _ok({"record": rec.to_dict()})

        elif level == "L2":
            student_name = body.get("student_name", "").strip()
            if not student_name:
                return _err("VALIDATION_ERROR", "student_name required.", 400)
            rec = _override_svc.l2_individual_retake(
                session_id=session_id,
                requesting_user_id=user_id,
                student_name=student_name,
                student_email=body.get("student_email", ""),
                confidence=float(body.get("confidence", 0.0)),
            )
            audit.manual_override(session_id, user_id, "L2", student_name, "PRESENT")
            return _ok({"record": rec.to_dict()})

        elif level == "L3":
            students = body.get("students", [])
            if not students:
                return _err("VALIDATION_ERROR", "students list required for L3.", 400)
            records = _override_svc.l3_bulk_add(
                session_id=session_id,
                requesting_user_id=user_id,
                students=students,
            )
            for s in students:
                audit.manual_override(session_id, user_id, "L3",
                                      s.get("name", ""), "PRESENT")
            return _ok({"records": [r.to_dict() for r in records]})

        else:
            return _err("VALIDATION_ERROR", f"Unknown override level: {level!r}", 400)

    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)
    except AttendanceStateError as exc:
        return _err("SESSION_INVALID_STATE", str(exc), 409)
    except ValueError as exc:
        return _err("VALIDATION_ERROR", str(exc), 400)
    except Exception as exc:
        log.exception("override failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


# ── POST /api/v2/attendance/sessions/<session_id>/finalize ────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>/finalize", methods=["POST"])
@login_required
def finalize(session_id: str):
    """Finalize session and perform atomic local SQLite commit (§15)."""
    user_id = g.user["user_id"]

    try:
        # Load current records (built from recognition + overrides)
        records = _repo.get_records(session_id)

        # Execute durable commit transaction
        session = _repo.finalize_and_commit(
            session_id=session_id,
            requesting_user_id=user_id,
            records=records,
        )

        audit.session_finalized(session_id, user_id, len(records))
        audit.local_commit(session_id, user_id)

        # Trigger sync worker to pick up the outbox event
        try:
            from aas.sync.worker import get_sync_worker
            worker = get_sync_worker()
            if not worker.is_running():
                worker.start()
        except Exception:
            pass  # Sync worker failure does not block local commit response

        return _ok({
            "session_id": session_id,
            "status": session.status.value,
            "local_committed_at": session.local_committed_at,
            "record_count": len(records),
            "message": "Attendance saved locally. Google Sheets sync queued.",
        })

    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)
    except AttendanceStateError as exc:
        return _err("SESSION_INVALID_STATE", str(exc), 409)
    except ValueError as exc:
        return _err("VALIDATION_ERROR", str(exc), 400)
    except Exception as exc:
        log.exception("finalize failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


# ── POST /api/v2/attendance/sessions/<session_id>/cancel ─────────────────────

@attendance_v2_bp.route("/api/v2/attendance/sessions/<session_id>/cancel", methods=["POST"])
@login_required
def cancel_session_route(session_id: str):
    """Cancel an in-progress session."""
    try:
        session = _session_svc.get_session_required(session_id)
        _assert_ownership(session)
        _session_svc.cancel_session(session)
        return _ok({"session_id": session_id, "status": session.status.value})
    except SessionNotFoundError:
        return _err("SESSION_NOT_FOUND", f"Session {session_id!r} not found.", 404)
    except SessionOwnershipError:
        return _err("ACCESS_DENIED", "You do not own this session.", 403)
    except AttendanceStateError as exc:
        return _err("SESSION_INVALID_STATE", str(exc), 409)
    except Exception as exc:
        log.exception("cancel_session failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _assert_ownership(session) -> None:
    """Raise SessionOwnershipError if the current user doesn't own the session."""
    if g.user["role"] != "admin" and session.faculty_user_id != g.user["user_id"]:
        raise SessionOwnershipError(session.session_id, g.user["user_id"])
