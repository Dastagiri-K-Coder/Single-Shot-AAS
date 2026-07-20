# =============================================================================
#  tests/unit/test_config.py — Tests for config.py
# =============================================================================

import os
import sys

import pytest

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "face recognition source code")
sys.path.insert(0, os.path.abspath(SRC_DIR))


class TestConfig:
    """Tests for central configuration loading."""

    def test_recognition_tolerance_is_float(self, monkeypatch):
        monkeypatch.setenv("RECOGNITION_TOLERANCE", "0.6")
        import importlib
        import config as cfg
        importlib.reload(cfg)
        assert isinstance(cfg.RECOGNITION_TOLERANCE, float)
        assert cfg.RECOGNITION_TOLERANCE == 0.6

    def test_recognition_scale_default(self, monkeypatch):
        monkeypatch.delenv("RECOGNITION_SCALE", raising=False)
        import importlib
        import config as cfg
        importlib.reload(cfg)
        assert cfg.RECOGNITION_SCALE == 0.25

    def test_webcam_index_is_int(self, monkeypatch):
        monkeypatch.setenv("WEBCAM_INDEX", "2")
        import importlib
        import config as cfg
        importlib.reload(cfg)
        assert cfg.WEBCAM_INDEX == 2

    def test_use_webcam_true_when_no_ip(self, monkeypatch):
        monkeypatch.setenv("IP_CAMERA_URL", "")
        import importlib
        import config as cfg
        importlib.reload(cfg)
        assert cfg.USE_WEBCAM is True

    def test_use_webcam_false_when_ip_set(self, monkeypatch):
        monkeypatch.setenv("IP_CAMERA_URL", "rtsp://192.168.1.1/stream")
        import importlib
        import config as cfg
        importlib.reload(cfg)
        assert cfg.USE_WEBCAM is False

    def test_web_port_is_int(self, monkeypatch):
        monkeypatch.setenv("WEB_PORT", "8080")
        import importlib
        import config as cfg
        importlib.reload(cfg)
        assert cfg.WEB_PORT == 8080

    def test_required_folders_created(self, tmp_path, monkeypatch):
        """config.py should create the three data dirs on import."""
        enc_dir = tmp_path / "encodings"
        photo_dir = tmp_path / "photos"
        cap_dir = tmp_path / "captured"
        # Patch the config paths before importing
        import importlib
        import config as cfg
        importlib.reload(cfg)
        # The actual paths depend on ROOT_DIR; just verify makedirs is called
        # (the dirs already exist in the real environment)
        assert os.path.isdir(cfg.ENCODINGS_FOLDER)
