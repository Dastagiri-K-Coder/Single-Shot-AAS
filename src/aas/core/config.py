# -*- coding: utf-8 -*-
"""
config.py - Central configuration for Single Shot AAS.

All paths, environment variables, and tunable constants live here.
Never hardcode paths or secrets in other modules - import from here instead.

New in v2:
    - OAUTH_CREDS_PATH    : oauth_credentials.json (GCP OAuth2 client)
    - TOKEN_PATH          : token.json (stored user OAuth token)
    - CAMERAS_JSON_PATH   : cameras.json (multi-camera registry)
    - INSTITUTION_JSON_PATH: institution.json (org details + Drive root ID)

Usage:
    from aas.core.config import PHOTO_FOLDER, ENCODINGS_FOLDER, RECOGNITION_TOLERANCE
"""

import os
from dotenv import load_dotenv

# -- Directory Layout ----------------------------------------------------------
# CORE_DIR  = src/aas/core/           (this file's directory)
# SRC_DIR   = src/                    (src package root)
# ROOT_DIR  = repo root               (Single Shot AAS/)
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR  = os.path.dirname(os.path.dirname(CORE_DIR))   # src/
ROOT_DIR = os.path.dirname(SRC_DIR)                      # repo root

# Load .env from repo root (preferred) or alongside this file as fallback
_env_root = os.path.join(ROOT_DIR, '.env')
_env_core = os.path.join(CORE_DIR, '.env')
load_dotenv(_env_root if os.path.exists(_env_root) else _env_core)

# BASE_DIR kept for any legacy references (points to core/ where credentials live)
BASE_DIR = CORE_DIR

# -- Data Folders --------------------------------------------------------------
# All runtime data lives under data/ at the repo root (no spaces in names)
DATA_DIR         = os.path.join(ROOT_DIR, "data")
PHOTO_FOLDER     = os.path.join(DATA_DIR, "known_face_photos")
ENCODINGS_FOLDER = os.path.join(DATA_DIR, "known_face_encodings")
CAPTURED_FOLDER  = os.path.join(DATA_DIR, "captured")

# -- Config Files --------------------------------------------------------------
CONFIG_DIR             = os.path.join(ROOT_DIR, "config")
CAMERAS_JSON_PATH      = os.path.join(CONFIG_DIR, "cameras.json")
INSTITUTION_JSON_PATH  = os.path.join(CONFIG_DIR, "institution.json")

# -- Google Cloud / OAuth ------------------------------------------------------
# Credentials live alongside config.py (src/aas/core/) - never committed to git
CREDS_FILE       = os.path.join(CORE_DIR, "credentials.json")
SHEET_NAME       = os.getenv("SHEET_NAME", "Face recognition")

# OAuth2 client credentials (downloaded from GCP Console -> OAuth 2.0 Client ID)
OAUTH_CREDS_PATH = os.path.join(CORE_DIR, "oauth_credentials.json")

# Stored user token (auto-created after first OAuth login)
TOKEN_PATH       = os.path.join(CORE_DIR, "token.json")

# Web app folder reference
WEB_APP_FOLDER   = os.path.join(os.path.dirname(CORE_DIR), "web")

# -- Camera Settings -----------------------------------------------------------
# Set IP_CAMERA_URL in .env for a fixed classroom IP/RTSP camera.
# Leave blank to fall back to the local webcam (index 0).
#
# Example RTSP URLs:
#   rtsp://admin:password@192.168.1.50:554/stream
#   rtsp://192.168.1.50/h264Preview_01_main
IP_CAMERA_URL        = os.getenv("IP_CAMERA_URL", "").strip()
USE_WEBCAM           = not bool(IP_CAMERA_URL)      # True if no IP camera configured
WEBCAM_INDEX         = int(os.getenv("WEBCAM_INDEX", "0"))
CAMERA_WARMUP_FRAMES = 5                            # frames to discard before capture

# -- Recognition Tuning --------------------------------------------------------
# Lower = stricter matching (fewer false positives, more unknowns)
# Higher = looser matching (more matches, risk of wrong IDs)
# Default 0.55 is slightly stricter than dlib's default 0.6
RECOGNITION_TOLERANCE = float(os.getenv("RECOGNITION_TOLERANCE", "0.55"))

# Fraction to resize image before recognition (0.25 = quarter size = 4x faster)
# Increase to 0.5 for better accuracy on very small/distant faces
RECOGNITION_SCALE     = float(os.getenv("RECOGNITION_SCALE", "0.25"))

# Face detection model: "hog" (fast, CPU-only) or "cnn" (accurate, needs GPU/dlib-cuda)
# Raspberry Pi 4 -> always use "hog"
# Laptop / desktop with GPU -> can use "cnn" for better accuracy
FACE_DETECTION_MODEL  = os.getenv("FACE_DETECTION_MODEL", "hog").lower()

# -- Attendance Rules ----------------------------------------------------------
# Students arriving AFTER this time are marked 'late' instead of 'present'
MAX_IN_TIME = os.getenv("MAX_IN_TIME", "16:00:00")

# -- Voice Trigger -------------------------------------------------------------
VOICE_TRIGGER_PHRASE = os.getenv("VOICE_TRIGGER_PHRASE", "take attendance").lower()
VOSK_MODEL_PATH      = os.path.join(ROOT_DIR, "vosk-model-small-en-us")

# -- Web Dashboard -------------------------------------------------------------
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "5000"))

# -- Ensure required folders exist ---------------------------------------------
for _folder in [PHOTO_FOLDER, ENCODINGS_FOLDER, CAPTURED_FOLDER, CONFIG_DIR]:
    os.makedirs(_folder, exist_ok=True)
