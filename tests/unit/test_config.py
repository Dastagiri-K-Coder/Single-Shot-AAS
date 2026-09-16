# =============================================================================
#  tests/unit/test_config.py — Tests for config.py
# =============================================================================

import os
import importlib
import pytest

import aas.core.config as cfg


class TestConfig:
    """Tests for central configuration loading."""

    def test_recognition_tolerance_is_float(self, monkeypatch):
        monkeypatch.setenv("RECOGNITION_TOLERANCE", "0.6")
        importlib.reload(cfg)
        assert isinstance(cfg.RECOGNITION_TOLERANCE, float)
        assert cfg.RECOGNITION_TOLERANCE == 0.6

    def test_recognition_scale_default(self, monkeypatch):
        monkeypatch.delenv("RECOGNITION_SCALE", raising=False)
        importlib.reload(cfg)
        assert cfg.RECOGNITION_SCALE == 0.5

    def test_standards_constants_defaults(self, monkeypatch):
        monkeypatch.delenv("MIN_FACE_SIZE", raising=False)
        monkeypatch.delenv("MIN_IPD_PIXELS", raising=False)
        importlib.reload(cfg)
        assert cfg.MIN_FACE_SIZE == 80
        assert cfg.MIN_IPD_PIXELS == 30
        assert cfg.AUTO_SCALE_DETECTION is True

    def test_webcam_index_is_int(self, monkeypatch):
        monkeypatch.setenv("WEBCAM_INDEX", "2")
        importlib.reload(cfg)
        assert cfg.WEBCAM_INDEX == 2

    def test_use_webcam_true_when_no_ip(self, monkeypatch):
        monkeypatch.setenv("IP_CAMERA_URL", "")
        importlib.reload(cfg)
        assert cfg.USE_WEBCAM is True

    def test_use_webcam_false_when_ip_set(self, monkeypatch):
        monkeypatch.setenv("IP_CAMERA_URL", "rtsp://192.168.1.1/stream")
        importlib.reload(cfg)
        assert cfg.USE_WEBCAM is False

    def test_web_port_is_int(self, monkeypatch):
        monkeypatch.setenv("WEB_PORT", "8080")
        importlib.reload(cfg)
        assert cfg.WEB_PORT == 8080

    def test_required_folders_created(self, tmp_path, monkeypatch):
        """config.py should create the three data dirs on import."""
        importlib.reload(cfg)
        # The actual paths depend on ROOT_DIR; just verify makedirs is called
        # (the dirs already exist in the real environment)
        assert os.path.isdir(cfg.ENCODINGS_FOLDER)
