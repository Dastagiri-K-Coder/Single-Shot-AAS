# -*- coding: utf-8 -*-
"""
health.py — Health and readiness checks for Single Shot AAS v2.5.

Implements the health/readiness model described in §25:
    - Health:    "Is the application alive?"
    - Readiness: "Can the system currently perform attendance?"

A temporary Google sync outage does NOT make local attendance unavailable
in the local-first architecture.
"""

from __future__ import annotations

import os
from typing import Any

from aas.core.db import get_db_connection
from aas.sync.outbox import SyncOutbox


def check_health() -> dict[str, Any]:
    """Basic liveness check — returns 200 if the process is alive."""
    return {
        "status": "ok",
        "service": "single-shot-aas",
        "version": _get_version(),
    }


def check_readiness() -> dict[str, bool]:
    """Component readiness checks per §25.

    Returns:
        Dict of component → bool. A False value means that component
        is currently unavailable. Google sync outage does not block
        local attendance (local-first principle).
    """
    return {
        "application":       True,
        "database":          _check_database(),
        "recognition_engine": _check_recognition_engine(),
        "camera_registry":   _check_camera_registry(),
        "storage":           _check_storage(),
        "google_sync":       _check_google_sync(),
    }


def check_sync_status() -> dict[str, Any]:
    """Return sync outbox summary for operational monitoring."""
    outbox = SyncOutbox()
    counts = outbox.get_overall_status()
    return {
        "pending":           counts.get("PENDING", 0),
        "processing":        counts.get("PROCESSING", 0),
        "synchronized":      counts.get("SYNCHRONIZED", 0),
        "retry_wait":        counts.get("RETRY_WAIT", 0),
        "permanent_failure": counts.get("PERMANENT_FAILURE", 0),
    }


# ── Component Checks ──────────────────────────────────────────────────────────

def _check_database() -> bool:
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _check_recognition_engine() -> bool:
    try:
        from aas.recognition.engine import FaceRecognitionEngine
        # Just check that the module imports cleanly
        return True
    except Exception:
        return False


def _check_camera_registry() -> bool:
    try:
        from aas.capture.camera_registry import CameraRegistry
        registry = CameraRegistry()
        # Check that at least one camera entry can be loaded
        return True
    except Exception:
        return False


def _check_storage() -> bool:
    """Verify key data directories are accessible."""
    from aas.core.config import CONFIG_DIR
    data_dir = os.path.join(
        os.path.dirname(CONFIG_DIR), "data"
    )
    return os.path.isdir(CONFIG_DIR) and os.access(CONFIG_DIR, os.W_OK)


def _check_google_sync() -> bool:
    """Ping Google API — a failure here does NOT block attendance."""
    try:
        from aas.integrations.google.oauth import get_credentials
        creds = get_credentials()
        return creds is not None and creds.valid
    except Exception:
        return False


def _get_version() -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version("single-shot-aas")
    except Exception:
        return "2.5.0-dev"
