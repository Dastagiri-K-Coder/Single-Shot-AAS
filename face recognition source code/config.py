# -*- coding: utf-8 -*-
"""
config.py — Central configuration for Single Shot AAS.

All paths, environment variables, and tunable constants live here.
Never hardcode paths or secrets in other modules — import from here instead.

New in v2:
    - OAUTH_CREDS_PATH    : oauth_credentials.json (GCP OAuth2 client)
    - TOKEN_PATH          : token.json (stored user OAuth token)
    - CAMERAS_JSON_PATH   : cameras.json (multi-camera registry)
    - INSTITUTION_JSON_PATH: institution.json (org details + Drive root ID)

Usage:
    from config import PHOTO_FOLDER, ENCODINGS_FOLDER, RECOGNITION_TOLERANCE
"""

import os
from dotenv import load_dotenv

# Load .env file (must be in the same directory as this file, or project root)
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ── Directory Paths ────────────────────────────────────────────────────────────
# BASE_DIR  = the "face recognition source code" folder (where this file lives)
# ROOT_DIR  = one level up (the Kalyan-Koppula repo root)
BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR          = os.path.dirname(BASE_DIR)

PHOTO_FOLDER      = os.path.join(ROOT_DIR, "known face photos")
ENCODINGS_FOLDER  = os.path.join(ROOT_DIR, "known face encodings")
CAPTURED_FOLDER   = os.path.join(ROOT_DIR, "captured")
WEB_APP_FOLDER    = os.path.join(BASE_DIR, "web_app")

# ── Google Cloud / OAuth ──────────────────────────────────────────────────────
# Legacy service account (kept for backward compat; new installs use OAuth2)
CREDS_FILE             = os.path.join(BASE_DIR, "credentials.json")
SHEET_NAME             = os.getenv("SHEET_NAME", "Face recognition")

# OAuth2 client credentials (downloaded from GCP Console → OAuth 2.0 Client ID)
OAUTH_CREDS_PATH       = os.path.join(BASE_DIR, "oauth_credentials.json")

# Stored user token (auto-created after first OAuth login)
TOKEN_PATH             = os.path.join(BASE_DIR, "token.json")

# ── Multi-Camera Registry ─────────────────────────────────────────────────────
# cameras.json: maps camera_id → {rtsp_url, sheet_id, sheet_name, folder_id, ...}
CAMERAS_JSON_PATH      = os.path.join(ROOT_DIR, "cameras.json")

# ── Institution Config ────────────────────────────────────────────────────────
# institution.json: org name, address, Drive root folder ID, next serial number
INSTITUTION_JSON_PATH  = os.path.join(ROOT_DIR, "institution.json")

# ── Camera Settings ────────────────────────────────────────────────────────────
# Set IP_CAMERA_URL in .env for a fixed classroom IP/RTSP camera.
# Leave blank to fall back to the local webcam (index 0).
#
# Example RTSP URLs:
#   rtsp://admin:password@192.168.1.50:554/stream
#   rtsp://192.168.1.50/h264Preview_01_main
IP_CAMERA_URL     = os.getenv("IP_CAMERA_URL", "").strip()
USE_WEBCAM        = not bool(IP_CAMERA_URL)      # True if no IP camera configured
WEBCAM_INDEX      = int(os.getenv("WEBCAM_INDEX", "0"))
CAMERA_WARMUP_FRAMES = 5                         # frames to discard before capture

# ── Recognition Tuning ─────────────────────────────────────────────────────────
# Lower = stricter matching (fewer false positives, more unknowns)
# Higher = looser matching (more matches, risk of wrong IDs)
# Default 0.55 is slightly stricter than dlib's default 0.6
RECOGNITION_TOLERANCE = float(os.getenv("RECOGNITION_TOLERANCE", "0.55"))

# Fraction to resize image before recognition (0.25 = quarter size = 4x faster)
# Increase to 0.5 for better accuracy on very small/distant faces
RECOGNITION_SCALE     = float(os.getenv("RECOGNITION_SCALE", "0.25"))

# Face detection model: "hog" (fast, CPU-only) or "cnn" (accurate, needs GPU/dlib-cuda)
# Raspberry Pi 4 → always use "hog"
# Laptop / desktop with GPU → can use "cnn" for better accuracy
FACE_DETECTION_MODEL  = os.getenv("FACE_DETECTION_MODEL", "hog").lower()

# ── Attendance Rules ───────────────────────────────────────────────────────────
# Students arriving AFTER this time are marked 'late' instead of 'present'
MAX_IN_TIME           = os.getenv("MAX_IN_TIME", "16:00:00")

# ── Voice Trigger ──────────────────────────────────────────────────────────────
VOICE_TRIGGER_PHRASE  = os.getenv("VOICE_TRIGGER_PHRASE", "take attendance").lower()
VOSK_MODEL_PATH       = os.path.join(ROOT_DIR, "vosk-model-small-en-us")

# ── Web Dashboard ──────────────────────────────────────────────────────────────
WEB_HOST              = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT              = int(os.getenv("WEB_PORT", "5000"))

# ── Ensure required folders exist ─────────────────────────────────────────────
for _folder in [PHOTO_FOLDER, ENCODINGS_FOLDER, CAPTURED_FOLDER]:
    os.makedirs(_folder, exist_ok=True)
