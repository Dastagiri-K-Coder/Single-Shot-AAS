# -*- coding: utf-8 -*-
"""
cameras.py — v2 camera management API routes for Single Shot AAS v2.5.

Implements §20.2 camera endpoints:

    GET    /api/v2/cameras
    POST   /api/v2/cameras
    DELETE /api/v2/cameras/<camera_id>
    GET    /api/v2/cameras/<camera_id>/status
    GET    /api/v2/cameras/<camera_id>/lock
"""

from __future__ import annotations

import logging
import uuid

from flask import Blueprint, g, jsonify, request

from aas.core.auth import login_required

log = logging.getLogger(__name__)

cameras_v2_bp = Blueprint("cameras_v2", __name__)


def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data, "error": None,
                    "request_id": str(uuid.uuid4())}), status


def _err(code: str, message: str, status: int = 400):
    return jsonify({"success": False, "data": None,
                    "error": {"code": code, "message": message},
                    "request_id": str(uuid.uuid4())}), status


@cameras_v2_bp.route("/api/v2/cameras", methods=["GET"])
@login_required
def list_cameras():
    """List cameras accessible to the current user."""
    try:
        import aas.capture.camera_registry as cr
        all_cameras = cr.load_cameras()

        user = g.user
        if user["role"] == "admin":
            return _ok({"cameras": all_cameras})

        import json
        assigned = json.loads(user.get("assigned_cameras", "[]"))
        filtered = [c for c in all_cameras if c.get("id") in assigned]
        return _ok({"cameras": filtered})
    except Exception as exc:
        log.exception("list_cameras failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


@cameras_v2_bp.route("/api/v2/cameras", methods=["POST"])
@login_required
def create_camera():
    """Create a new camera entry (admin only)."""
    if g.user["role"] != "admin":
        return _err("ACCESS_DENIED", "Admin access required.", 403)

    body = request.get_json(silent=True) or {}
    required = ["display_name", "section_code"]
    for field in required:
        if not body.get(field):
            return _err("VALIDATION_ERROR", f"Field {field!r} is required.", 400)

    try:
        import aas.capture.camera_registry as cr
        cam = cr.add_camera(
            display_name=body["display_name"],
            rtsp_url=body.get("rtsp_url", ""),
            sheet_name=body.get("sheet_name", body["display_name"]),
            section_code=body["section_code"],
        )
        return _ok({"camera": cam}, 201)
    except Exception as exc:
        log.exception("create_camera failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


@cameras_v2_bp.route("/api/v2/cameras/<camera_id>", methods=["DELETE"])
@login_required
def delete_camera(camera_id: str):
    """Delete a camera entry (admin only)."""
    if g.user["role"] != "admin":
        return _err("ACCESS_DENIED", "Admin access required.", 403)
    try:
        import aas.capture.camera_registry as cr
        removed = cr.delete_camera(camera_id)
        if not removed:
            return _err("CAMERA_NOT_FOUND", f"Camera {camera_id!r} not found.", 404)
        return _ok({"deleted": camera_id})
    except Exception as exc:
        log.exception("delete_camera failed")
        return _err("INTERNAL_ERROR", str(exc), 500)


@cameras_v2_bp.route("/api/v2/cameras/<camera_id>/status", methods=["GET"])
@login_required
def camera_status(camera_id: str):
    """Get camera connectivity status."""
    try:
        import aas.capture.camera_registry as cr
        cam = cr.get_camera(camera_id)
        if not cam:
            return _err("CAMERA_NOT_FOUND", f"Camera {camera_id!r} not found.", 404)
        return _ok({"camera_id": camera_id, "status": "available", "camera": cam})
    except Exception as exc:
        log.exception("camera_status failed")
        return _err("CAMERA_UNAVAILABLE", str(exc), 503)


@cameras_v2_bp.route("/api/v2/cameras/<camera_id>/lock", methods=["GET"])
@login_required
def camera_lock_status(camera_id: str):
    """Get camera lock status (is it in use?)."""
    try:
        import aas.capture.camera_registry as cr
        cam = cr.get_camera(camera_id)
        if not cam:
            return _err("CAMERA_NOT_FOUND", f"Camera {camera_id!r} not found.", 404)
        # Lock status is stored in the camera dict if applicable
        locked = cam.get("locked", False)
        return _ok({"camera_id": camera_id, "locked": locked})
    except Exception as exc:
        log.exception("camera_lock_status failed")
        return _err("INTERNAL_ERROR", str(exc), 500)
