# -*- coding: utf-8 -*-
"""
roles.py — Role resolution, faculty-camera mapping, and period detection.

Single Shot AAS v2.0:
    - Every login produces a role: 'admin' or 'faculty'
    - Faculty see only their assigned section(s)
    - The timetable drives auto-detection of the current period

Functions:
    get_user_role(email)           → 'admin' | 'faculty'  (legacy Google OAuth path)
    get_role_from_user_id(user_id) → 'admin' | 'faculty'  (local login path)
    get_faculty_cameras(email)     → list[dict] of assigned camera entries
    get_faculty_cameras_by_id(user_id) → list[dict]
    get_current_period(camera_id)  → period dict | None
    get_full_schedule(camera_id)   → list[dict]
    save_schedule(camera_id, schedule) → None
"""

import os
import json
import datetime

from aas.core.config import CONFIG_DIR, INSTITUTION_JSON_PATH

TIMETABLE_JSON_PATH = os.path.join(CONFIG_DIR, "timetable.json")
FACULTY_REGISTRY_PATH = os.path.join(CONFIG_DIR, "faculty_registry.json")


# ── Role Resolution ───────────────────────────────────────────────────────────

def get_user_role(email: str) -> str:
    """Return 'admin' or 'faculty' for a Google account email.

    Used in the legacy Google OAuth path. Checks institution.json admin_emails[].

    Args:
        email: Google account email of the logged-in user.

    Returns:
        'admin' if email is in admin_emails, 'faculty' otherwise.
    """
    if not email:
        return "faculty"
    try:
        with open(INSTITUTION_JSON_PATH) as f:
            inst = json.load(f)
        admin_email = inst.get("contact_email", "")
        admin_emails = inst.get("admin_emails", [admin_email] if admin_email else [])
        if email.lower() in [a.lower() for a in admin_emails]:
            return "admin"
    except Exception:
        pass
    return "faculty"


def get_role_from_user_id(user_id: str) -> str:
    """Return 'admin' or 'faculty' for a local login user_id.

    Reads directly from SQLite users table via auth module.
    Falls back to 'faculty' on any error.

    Args:
        user_id: Local login ID (e.g. 'FAC-001', 'ADM-001').

    Returns:
        'admin' or 'faculty'.
    """
    try:
        from aas.core.auth import db_get_user
        user = db_get_user(user_id)
        if user:
            return user.get("role", "faculty")
    except Exception:
        pass
    return "faculty"


# ── Faculty → Camera Mapping ──────────────────────────────────────────────────

def get_faculty_cameras(email: str) -> list[dict]:
    """Return cameras assigned to a faculty member (matched by email).

    Args:
        email: Faculty's email address (from Google OAuth or user record).

    Returns:
        List of camera dicts from cameras.json where assigned_faculty_email
        matches (case-insensitive). Returns all cameras for admin.
    """
    from aas.capture.camera_registry import load_cameras
    all_cameras = load_cameras()
    if not email:
        return all_cameras
    return [
        c for c in all_cameras
        if c.get("assigned_faculty_email", "").lower() == email.lower()
    ]


def get_faculty_cameras_by_id(user_id: str) -> list[dict]:
    """Return cameras assigned to a faculty member (matched by user_id).

    Reads the user's assigned_cameras list from SQLite, then maps to
    full camera dicts from cameras.json.

    Args:
        user_id: Local login ID (e.g. 'FAC-001').

    Returns:
        List of camera dicts, or all cameras if user is admin.
    """
    import json as _json
    try:
        from aas.core.auth import db_get_user
        from aas.capture.camera_registry import load_cameras, get_camera

        user = db_get_user(user_id)
        if not user:
            return []

        if user.get("role") == "admin":
            return load_cameras()

        assigned = _json.loads(user.get("assigned_cameras", "[]"))
        cameras = []
        for cam_id in assigned:
            cam = get_camera(cam_id)
            if cam:
                cameras.append(cam)
        return cameras
    except Exception as e:
        print(f"  [Roles] get_faculty_cameras_by_id error: {e}")
        return []


# ── Period Detection ──────────────────────────────────────────────────────────

def get_current_period(camera_id: str) -> dict | None:
    """Return the currently active period for a section based on system time.

    Reads config/timetable.json. Compares current HH:MM against each period's
    start_time and end_time (inclusive). Returns the first match.

    Args:
        camera_id: Camera/section identifier (e.g. 'cam-001').

    Returns:
        Period dict: {period, start_time, end_time, subject, subject_abbr,
                      faculty_email, faculty_name}
        None if no period is currently active (break, before first, after last).
    """
    try:
        with open(TIMETABLE_JSON_PATH) as f:
            timetable = json.load(f)
        schedule = timetable.get(camera_id, {}).get("schedule", [])
        if not schedule:
            return None

        now = datetime.datetime.now().strftime("%H:%M")
        for period in schedule:
            start = period.get("start_time", "")
            end = period.get("end_time", "")
            if start and end and start <= now <= end:
                return period
    except Exception as e:
        print(f"  [Roles] get_current_period error for '{camera_id}': {e}")
    return None


def get_full_schedule(camera_id: str) -> list[dict]:
    """Return the full period schedule for a camera/section.

    Args:
        camera_id: Camera identifier.

    Returns:
        List of period dicts, ordered by period number. Empty list if not found.
    """
    try:
        with open(TIMETABLE_JSON_PATH) as f:
            timetable = json.load(f)
        return timetable.get(camera_id, {}).get("schedule", [])
    except Exception as e:
        print(f"  [Roles] get_full_schedule error for '{camera_id}': {e}")
        return []


def save_schedule(camera_id: str, schedule: list[dict]) -> None:
    """Persist a new or updated schedule for a camera/section.

    Validates each period entry before writing. Existing entries for
    other cameras are preserved.

    Args:
        camera_id: Camera identifier.
        schedule:  List of period dicts. Each must have:
                   period (int), start_time (HH:MM), end_time (HH:MM), subject (str).

    Raises:
        ValueError: If any period entry is missing required fields.
    """
    required = {"period", "start_time", "end_time", "subject"}
    for i, p in enumerate(schedule):
        missing = required - set(p.keys())
        if missing:
            raise ValueError(
                f"save_schedule: period[{i}] missing fields: {missing}"
            )

    # Load existing timetable (preserve other cameras)
    timetable = {}
    if os.path.exists(TIMETABLE_JSON_PATH):
        try:
            with open(TIMETABLE_JSON_PATH) as f:
                timetable = json.load(f)
        except Exception:
            pass

    # Ensure section_display is preserved if it exists
    section_entry = timetable.get(camera_id, {})
    section_entry["schedule"] = schedule
    timetable[camera_id] = section_entry

    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(TIMETABLE_JSON_PATH, "w") as f:
        json.dump(timetable, f, indent=2)
    print(f"  ✓ [Roles] Timetable saved for '{camera_id}': {len(schedule)} periods.")


# ── Utility ───────────────────────────────────────────────────────────────────

def get_next_faculty_id() -> str:
    """Return the next auto-numbered faculty ID (e.g. 'FAC-005').

    Reads existing user IDs from the database and finds the highest FAC-NNN.

    Returns:
        String like 'FAC-001', 'FAC-002', etc.
    """
    try:
        from aas.core.auth import get_all_users
        users = get_all_users()
        fac_ids = [
            int(u["user_id"].split("-")[1])
            for u in users
            if u["user_id"].startswith("FAC-") and u["user_id"][4:].isdigit()
        ]
        next_num = max(fac_ids, default=0) + 1
        return f"FAC-{next_num:03d}"
    except Exception:
        return "FAC-001"
