# =============================================================================
#  tests/conftest.py — Shared pytest fixtures for AI Attendance System tests
# =============================================================================

import os
import sys
import pickle
import tempfile
import shutil
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ── Add source to path ────────────────────────────────────────────────────────
SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "face recognition source code")
sys.path.insert(0, os.path.abspath(SRC_DIR))


# ── Fixtures: temp filesystem ──────────────────────────────────────────────────

@pytest.fixture()
def tmp_dirs(tmp_path):
    """Create temporary versions of all data directories."""
    dirs = {
        "encodings": tmp_path / "known_face_encodings",
        "photos": tmp_path / "known_face_photos",
        "captured": tmp_path / "captured",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    return dirs


@pytest.fixture()
def fake_encoding():
    """Return a deterministic 128-D fake face encoding."""
    rng = np.random.default_rng(seed=42)
    return rng.random(128).astype(np.float64)


@pytest.fixture()
def fake_encoding_2():
    """A second, different 128-D encoding for distinguishing two students."""
    rng = np.random.default_rng(seed=99)
    return rng.random(128).astype(np.float64)


@pytest.fixture()
def pkl_student(tmp_dirs, fake_encoding):
    """Write a .pkl encoding file for a test student 'Test_Student'."""
    pkl_path = tmp_dirs["encodings"] / "Test_Student.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump([fake_encoding], f)
    return pkl_path


@pytest.fixture()
def synthetic_image(tmp_dirs):
    """Create a minimal valid JPEG in the captured folder for testing."""
    import cv2

    img_path = str(tmp_dirs["captured"] / "test_classroom.jpg")
    # Create a simple white 640×480 image (no real face)
    img = np.ones((480, 640, 3), dtype=np.uint8) * 200
    cv2.imwrite(img_path, img)
    return img_path


# ── Fixtures: mocked external services ────────────────────────────────────────

@pytest.fixture()
def mock_gspread(monkeypatch):
    """Patch gspread so no real Google Sheets calls are made."""
    mock_sheet = MagicMock()
    mock_sheet.row_values.return_value = ["Name", "Email", "PIN", "7/14/2026"]
    mock_sheet.col_values.return_value = ["Name", "Alice", "Bob"]
    mock_sheet.find.return_value = MagicMock(row=2)
    mock_sheet.cell.return_value = MagicMock(value="absent")

    mock_gc = MagicMock()
    mock_gc.open.return_value.sheet1 = mock_sheet

    monkeypatch.setattr("spreadsheet._gc", mock_gc)
    monkeypatch.setattr("spreadsheet.sheet", mock_sheet)
    return mock_sheet


@pytest.fixture()
def mock_smtp(monkeypatch):
    """Prevent any real email being sent during tests."""
    mock_server = MagicMock()
    monkeypatch.setattr("smtplib.SMTP_SSL", lambda *a, **kw: mock_server)
    mock_server.__enter__ = lambda s: s
    mock_server.__exit__ = MagicMock(return_value=False)
    return mock_server


@pytest.fixture()
def mock_camera(monkeypatch):
    """Patch cv2.VideoCapture to return a synthetic frame."""
    import cv2

    fake_frame = np.ones((480, 640, 3), dtype=np.uint8) * 180

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, fake_frame)
    mock_cap.release = MagicMock()

    monkeypatch.setattr("cv2.VideoCapture", lambda *a: mock_cap)
    return mock_cap


# ── Env setup ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_env_vars(monkeypatch):
    """Ensure test environment variables are set to safe defaults."""
    monkeypatch.setenv("GMAIL_SENDER", "test@example.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "test-password-placeholder")
    monkeypatch.setenv("SHEET_NAME", "TestSheet")
    monkeypatch.setenv("RECOGNITION_TOLERANCE", "0.55")
    monkeypatch.setenv("RECOGNITION_SCALE", "0.25")
    monkeypatch.setenv("MAX_IN_TIME", "16:00:00")
    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setenv("WEB_PORT", "5000")
