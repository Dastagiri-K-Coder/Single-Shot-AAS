# -*- coding: utf-8 -*-
"""
sync_routes.py — v2 synchronization status API routes for Single Shot AAS v2.5.

Implements §20.5 sync endpoints:

    GET  /api/v2/sync/status
    GET  /api/v2/sync/events
    POST /api/v2/sync/events/<event_id>/retry
"""

from __future__ import annotations

import logging
import uuid

from flask import Blueprint, g, jsonify, request

from aas.core.auth import login_required
from aas.sync.outbox import SyncOutbox

log = logging.getLogger(__name__)

sync_v2_bp = Blueprint("sync_v2", __name__)
_outbox = SyncOutbox()


def _ok(data, status: int = 200):
    return jsonify({"success": True, "data": data, "error": None,
                    "request_id": str(uuid.uuid4())}), status


def _err(code: str, message: str, status: int = 400):
    return jsonify({"success": False, "data": None,
                    "error": {"code": code, "message": message},
                    "request_id": str(uuid.uuid4())}), status


@sync_v2_bp.route("/api/v2/sync/status", methods=["GET"])
@login_required
def sync_status():
    """Overall outbox health summary."""
    from aas.observability.health import check_sync_status
    from aas.sync.worker import get_sync_worker
    data = check_sync_status()
    data["worker_running"] = get_sync_worker().is_running()
    return _ok(data)


@sync_v2_bp.route("/api/v2/sync/events", methods=["GET"])
@login_required
def sync_events():
    """List recent sync outbox events (admin only)."""
    if g.user["role"] != "admin":
        return _err("ACCESS_DENIED", "Admin access required.", 403)
    limit = min(int(request.args.get("limit", 50)), 200)
    from aas.core.db import get_db_connection
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM sync_outbox ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return _ok({"events": [dict(r) for r in rows]})


@sync_v2_bp.route("/api/v2/sync/events/<event_id>/retry", methods=["POST"])
@login_required
def retry_event(event_id: str):
    """Manually reset a PERMANENT_FAILURE event to PENDING (admin only)."""
    if g.user["role"] != "admin":
        return _err("ACCESS_DENIED", "Admin access required.", 403)
    event = _outbox.get_event(event_id)
    if not event:
        return _err("SYNC_EVENT_NOT_FOUND", f"Event {event_id!r} not found.", 404)
    reset = _outbox.retry_event_manually(event_id)
    if not reset:
        return _err("SYNC_FAILED", "Event cannot be retried in its current state.", 409)
    return _ok({"event_id": event_id, "status": "PENDING"})


# ── System health routes (§20.6) ──────────────────────────────────────────────

system_v2_bp = Blueprint("system_v2", __name__)


@system_v2_bp.route("/api/v2/system/health", methods=["GET"])
def system_health():
    """Liveness check — no auth required."""
    from aas.observability.health import check_health
    return jsonify(check_health()), 200


@system_v2_bp.route("/api/v2/system/readiness", methods=["GET"])
def system_readiness():
    """Readiness check per §25 — no auth required."""
    from aas.observability.health import check_readiness
    components = check_readiness()
    # System is ready if core components (db, recognition, storage) are up
    core_ready = all([
        components["database"],
        components["recognition_engine"],
        components["storage"],
    ])
    http_status = 200 if core_ready else 503
    return jsonify({"ready": core_ready, "components": components}), http_status


@system_v2_bp.route("/api/v2/system/version", methods=["GET"])
def system_version():
    """Return application version."""
    from aas.observability.health import _get_version
    return jsonify({"version": _get_version()}), 200
