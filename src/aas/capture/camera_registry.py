# -*- coding: utf-8 -*-
"""
camera_registry.py — Camera registry for Single Shot AAS.

Manages the cameras.json file that maps each classroom camera to its
assigned Google Sheet, Drive folder, and section-specific encodings folder.

Functions:
    load_cameras()              → List all registered cameras
    get_camera(cam_id)          → Get one camera dict by ID
    add_camera(...)             → Register a new camera
    update_camera(cam_id, ...)  → Update camera fields (e.g. sheet_id)
    delete_camera(cam_id)       → Remove a camera
    save_cameras(cameras_list)  → Persist to cameras.json
    get_cameras_json_path()     → Absolute path to cameras.json

New in v2.0:
    capture_mode           : "rtsp" | "webcam" | "mobile_upload" (default: mobile_upload)
    assigned_faculty_email : email of faculty assigned to this camera/section
    faculty_name           : display name of assigned faculty
"""

import os
import json
import uuid
import threading
from aas.core.config import CAMERAS_JSON_PATH

_registry_lock = threading.RLock()


# ── Default template for a new camera entry ───────────────────────────────────

def _default_camera(
    display_name: str,
    rtsp_url: str,
    sheet_name: str,
    section_code: str = "",
    year_start: int = 2024,
    year_end: int = 2027,
    section: str = "A",
) -> dict:
    cam_id = f"cam_{uuid.uuid4().hex[:6]}"
    return {
        "id":                  cam_id,
        "display_name":        display_name,
        "rtsp_url":            rtsp_url,
        "sheet_id":            "",          # filled after Drive setup
        "sheet_name":          sheet_name,
        "drive_folder_id":     "",          # filled after Drive setup
        "encodings_subfolder": cam_id,      # known face encodings/<cam_id>/
        "voice_trigger_phrase": "take attendance",
        "section_code":        section_code,
        "year_start":          year_start,
        "year_end":            year_end,
        "section":             section,
        "serial":              1,           # updated on creation
        # v2.0 fields
        "capture_mode":           "mobile_upload",  # "rtsp" | "webcam" | "mobile_upload"
        "assigned_faculty_email": "",
        "faculty_name":           "",
    }


# ── Read ──────────────────────────────────────────────────────────────────────

def load_cameras() -> list[dict]:
    """Load all cameras from cameras.json. Returns empty list if file missing.

    Backward-compatible: v1 entries without v2 fields receive safe defaults.
    """
    _V2_DEFAULTS = {
        "capture_mode":           "mobile_upload",
        "assigned_faculty_email": "",
        "faculty_name":           "",
    }
    with _registry_lock:
        if not os.path.exists(CAMERAS_JSON_PATH):
            return []
        try:
            with open(CAMERAS_JSON_PATH, "r") as f:
                data = json.load(f)
            cameras = data.get("cameras", [])
            # Inject missing v2 fields into legacy entries (non-destructive)
            for cam in cameras:
                for key, default in _V2_DEFAULTS.items():
                    if key not in cam:
                        cam[key] = default
            return cameras
        except Exception as e:
            print(f"  [CameraRegistry] Error loading cameras.json: {e}")
            return []


def get_camera(cam_id: str) -> dict | None:
    """Return the camera dict for the given ID, or None if not found."""
    for cam in load_cameras():
        if cam["id"] == cam_id:
            return cam
    return None


def get_cameras_json_path() -> str:
    return CAMERAS_JSON_PATH


# ── Write ─────────────────────────────────────────────────────────────────────

def save_cameras(cameras: list[dict]) -> None:
    """Persist the full cameras list to cameras.json."""
    with _registry_lock:
        os.makedirs(os.path.dirname(CAMERAS_JSON_PATH), exist_ok=True)
        with open(CAMERAS_JSON_PATH, "w") as f:
            json.dump({"cameras": cameras}, f, indent=2)


def add_camera(
    display_name: str,
    rtsp_url: str,
    section_code: str,
    year_start: int,
    year_end: int,
    section: str,
) -> dict:
    """
    Register a new camera. Auto-assigns serial number and generates camera ID.
    Returns the new camera dict.
    """
    from aas.integrations.google.drive_manager import format_sheet_name

    with _registry_lock:
        cameras = load_cameras()
        serial = len(cameras) + 1
        sheet_name = format_sheet_name(serial, section_code, year_start, year_end, section)
        cam = _default_camera(
            display_name=display_name,
            rtsp_url=rtsp_url,
            sheet_name=sheet_name,
            section_code=section_code,
            year_start=year_start,
            year_end=year_end,
            section=section,
        )
        cam["serial"] = serial

        # Create per-camera encodings subfolder
        from aas.core.config import ENCODINGS_FOLDER
        enc_path = os.path.join(ENCODINGS_FOLDER, cam["encodings_subfolder"])
        os.makedirs(enc_path, exist_ok=True)

        cameras.append(cam)
        save_cameras(cameras)
        print(f"  ✓ Registered camera '{display_name}' → sheet: '{sheet_name}'")
        return cam


def update_camera(cam_id: str, **fields) -> dict | None:
    """
    Update one or more fields on a camera entry.
    Example: update_camera("cam_abc123", sheet_id="1BxiMVs...", drive_folder_id="xyz")
    Returns updated camera dict, or None if not found.
    """
    with _registry_lock:
        cameras = load_cameras()
        for cam in cameras:
            if cam["id"] == cam_id:
                cam.update(fields)
                save_cameras(cameras)
                return cam
        print(f"  [CameraRegistry] Camera '{cam_id}' not found.")
        return None


def delete_camera(cam_id: str) -> bool:
    """Remove a camera from the registry. Returns True if removed."""
    with _registry_lock:
        cameras = load_cameras()
        updated = [c for c in cameras if c["id"] != cam_id]
        if len(updated) == len(cameras):
            return False
        save_cameras(updated)
        return True


def get_encodings_path(cam_id: str) -> str | None:
    """Return the absolute encodings folder path for a camera ID."""
    from aas.core.config import ENCODINGS_FOLDER
    cam = get_camera(cam_id)
    if not cam:
        return None
    return os.path.join(ENCODINGS_FOLDER, cam["encodings_subfolder"])
