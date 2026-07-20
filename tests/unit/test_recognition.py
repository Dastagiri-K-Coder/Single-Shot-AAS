# =============================================================================
#  tests/unit/test_recognition.py — Tests for recognition.py
# =============================================================================

import os
import pickle
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from aas.recognition import engine as recognition


class TestImageQualityCheck:
    """Tests for recognition._check_image_quality()"""

    def test_too_small_image_fails(self):
        """Images narrower than 320px should fail quality check."""
        frame = np.ones((240, 100, 3), dtype=np.uint8) * 128
        ok, msg = recognition._check_image_quality(frame)
        assert ok is False
        assert "320" in msg

    def test_too_dark_image_fails(self):
        """Images with mean brightness < 40 should fail quality check."""
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 10  # very dark
        ok, msg = recognition._check_image_quality(frame)
        assert ok is False
        assert "dark" in msg.lower()

    def test_good_image_passes(self):
        """Normal bright image should pass quality check."""
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 150
        ok, msg = recognition._check_image_quality(frame)
        assert ok is True
        assert msg == "OK"

    def test_minimum_width_boundary(self):
        """Exactly 320px wide should pass."""
        frame = np.ones((240, 320, 3), dtype=np.uint8) * 150
        ok, msg = recognition._check_image_quality(frame)
        assert ok is True

    def test_brightness_boundary(self):
        """Exactly brightness=40 should pass."""
        frame = np.ones((480, 640, 3), dtype=np.uint8) * 40
        ok, msg = recognition._check_image_quality(frame)
        assert ok is True


class TestLoadEncodings:
    """Tests for recognition.load_facial_encodings_and_names_from_memory()"""

    def test_loads_pkl_files(self, tmp_dirs, fake_encoding, monkeypatch):
        """Should load all .pkl files from the encodings folder."""
        pkl_path = tmp_dirs["encodings"] / "Alice.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump([fake_encoding], f)

        monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))
        recognition.load_facial_encodings_and_names_from_memory()

        assert len(recognition.known_face_names) == 1
        assert "Alice" in recognition.known_face_names

    def test_handles_multi_angle_pkl(self, tmp_dirs, fake_encoding, fake_encoding_2, monkeypatch):
        """Multi-angle .pkl (list of 3 encodings) should load 3 entries for same name."""
        pkl_path = tmp_dirs["encodings"] / "Bob.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump([fake_encoding, fake_encoding_2, fake_encoding], f)

        monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))
        recognition.load_facial_encodings_and_names_from_memory()

        assert recognition.known_face_names.count("Bob") == 3

    def test_skips_non_pkl_files(self, tmp_dirs, monkeypatch):
        """Non-.pkl files in encodings folder should be ignored."""
        (tmp_dirs["encodings"] / "notes.txt").write_text("not a pkl")
        monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))
        recognition.load_facial_encodings_and_names_from_memory()
        assert len(recognition.known_face_names) == 0

    def test_raises_if_folder_missing(self, monkeypatch):
        """Should raise FileNotFoundError if encodings folder doesn't exist."""
        monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", "/nonexistent/path")
        with pytest.raises(FileNotFoundError):
            recognition.load_facial_encodings_and_names_from_memory()

    def test_clears_previous_state_on_reload(self, tmp_dirs, fake_encoding, monkeypatch):
        """Calling load twice should not double-up the encodings."""
        pkl_path = tmp_dirs["encodings"] / "Charlie.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump([fake_encoding], f)

        monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))
        recognition.load_facial_encodings_and_names_from_memory()
        recognition.load_facial_encodings_and_names_from_memory()

        assert recognition.known_face_names.count("Charlie") == 1


class TestRunRecognition:
    """Tests for recognition.run_recognition()"""

    def test_raises_if_no_encodings_loaded(self, synthetic_image):
        """Should raise RuntimeError if called before loading encodings."""
        recognition.known_face_encodings.clear()
        recognition.known_face_names.clear()
        with pytest.raises(RuntimeError, match="No face encodings loaded"):
            recognition.run_recognition(synthetic_image)

    def test_raises_if_image_not_found(self, fake_encoding, monkeypatch):
        """Should raise FileNotFoundError for a non-existent image path."""
        recognition.known_face_encodings = [fake_encoding]
        recognition.known_face_names = ["Alice"]
        with pytest.raises(FileNotFoundError):
            recognition.run_recognition("/nonexistent/image.jpg")

    def test_returns_empty_result_on_no_faces(self, synthetic_image, fake_encoding, monkeypatch):
        """
        When face_recognition.face_locations returns empty list,
        run_recognition should return zeros without crashing.
        """
        recognition.known_face_encodings = [fake_encoding]
        recognition.known_face_names = ["Alice"]

        with patch("face_recognition.face_locations", return_value=[]):
            result = recognition.run_recognition(synthetic_image)

        assert result["present"] == []
        assert result["unknown_count"] == 0
        assert result["total_faces"] == 0

    def test_result_has_expected_keys(self, synthetic_image, fake_encoding, monkeypatch):
        """Result dict should contain all required keys."""
        recognition.known_face_encodings = [fake_encoding]
        recognition.known_face_names = ["Alice"]

        with patch("face_recognition.face_locations", return_value=[]):
            result = recognition.run_recognition(synthetic_image)

        assert "present" in result
        assert "unknown_count" in result
        assert "total_faces" in result
        assert "recognized_at" in result
