# -*- coding: utf-8 -*-
"""
test_recognition_standards.py — Unit tests for facial recognition standards,
metrics, adaptive scaling, and per-face resolution quality gating.
"""

from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import pytest

from aas.recognition.metrics import (
    compute_sharpness,
    compute_ipd_from_landmarks,
    validate_classroom_frame,
    calculate_adaptive_scale,
)
from aas.recognition.detectors import DlibFaceDetector, FaceDetection
from aas.recognition import engine as recognition


class TestMetrics:
    """Tests for image sharpness and IPD computation."""

    def test_sharpness_differentiates_blur(self):
        """Sharp checkerboard should have significantly higher variance than blurred."""
        # Create a high-contrast pattern
        sharp = np.zeros((200, 200, 3), dtype=np.uint8)
        sharp[::20, :] = 255
        sharp[:, ::20] = 255

        blurred = cv2.GaussianBlur(sharp, (25, 25), 0)

        score_sharp = compute_sharpness(sharp)
        score_blurred = compute_sharpness(blurred)

        assert score_sharp > score_blurred
        assert score_blurred < 50.0

    def test_ipd_from_68_point_landmarks(self):
        """Calculates distance between eye centers accurately."""
        landmarks = {
            "left_eye": [(100, 150), (104, 150), (108, 150)],    # center ~ (104, 150)
            "right_eye": [(144, 150), (148, 150), (152, 150)],   # center ~ (148, 150)
        }
        ipd = compute_ipd_from_landmarks(landmarks)
        # Expected dx = 148 - 104 = 44, dy = 0 -> IPD = 44.0
        assert ipd == pytest.approx(44.0, abs=1.0)

    def test_ipd_from_5_point_landmarks(self):
        """Calculates distance from 5-point landmark list [right_eye, left_eye, ...]."""
        pts = [(150, 100), (110, 100), (130, 120), (145, 140), (115, 140)]
        ipd = compute_ipd_from_landmarks(pts)
        assert ipd == pytest.approx(40.0, abs=0.5)

    def test_ipd_empty_or_missing_landmarks(self):
        """Returns 0.0 if landmarks are invalid or empty."""
        assert compute_ipd_from_landmarks({}) == 0.0
        assert compute_ipd_from_landmarks([]) == 0.0
        assert compute_ipd_from_landmarks(None) == 0.0


class TestClassroomFrameValidation:
    """Tests for validate_classroom_frame."""

    def test_fails_below_minimum_width(self):
        """Image below minimum width (e.g. 800px < 1280px) should fail."""
        frame = np.ones((600, 800, 3), dtype=np.uint8) * 150
        ok, msg, metrics = validate_classroom_frame(frame, min_width=1280, recommended_width=1920)
        assert ok is False
        assert "too low" in msg.lower()
        assert metrics["width"] == 800

    def test_fails_if_too_dark(self):
        """Image with brightness < 40 fails."""
        frame = np.ones((1080, 1920, 3), dtype=np.uint8) * 20
        ok, msg, metrics = validate_classroom_frame(frame, brightness_min=40.0)
        assert ok is False
        assert "dark" in msg.lower()

    def test_recommended_full_hd_passes(self):
        """Full HD (1920x1080) sharp frame passes recommended threshold."""
        frame = np.ones((1080, 1920, 3), dtype=np.uint8) * 150
        # Add high-contrast lines to avoid blur failure
        frame[::10, :] = 0
        ok, msg, metrics = validate_classroom_frame(frame, min_width=1280, recommended_width=1920, blur_threshold=1.0)
        assert ok is True
        assert metrics["is_recommended_classroom_res"] is True


class TestAdaptiveScaling:
    """Tests for calculate_adaptive_scale."""

    def test_scale_for_4k(self):
        """4K frame (3840x2160) should scale to 0.5 to keep faces visible on 1080p canvas."""
        scale = calculate_adaptive_scale(3840, 2160, auto_scale=True)
        assert scale == 0.5

    def test_scale_for_2k(self):
        """2K frame (2560x1440) scales to 0.75."""
        scale = calculate_adaptive_scale(2560, 1440, auto_scale=True)
        assert scale == 0.75

    def test_scale_for_1080p(self):
        """1080p frame (1920x1080) must remain at 1.0 to preserve 60-80px back-row faces."""
        scale = calculate_adaptive_scale(1920, 1080, auto_scale=True)
        assert scale == 1.0

    def test_manual_override_respected(self):
        """When auto_scale=False, user scale is used."""
        scale = calculate_adaptive_scale(3840, 2160, user_scale=0.33, auto_scale=False)
        assert scale == pytest.approx(0.33, abs=0.01)


class TestFaceDetectorStandardsGating:
    """Tests that detector correctly flags sub-80px and sub-30px IPD faces."""

    @patch("face_recognition.face_locations")
    @patch("face_recognition.face_landmarks")
    def test_flags_substandard_face_size(self, mock_landmarks, mock_locations):
        """Face smaller than min_face_size (80px) is marked is_standard_res = False."""
        # Scaled image: face is 40x40 at scale 1.0 -> raw size 40x40 (< 80px)
        mock_locations.return_value = [(10, 50, 50, 10)]
        mock_landmarks.return_value = [{}]

        rgb = np.zeros((200, 200, 3), dtype=np.uint8)
        detector = DlibFaceDetector(model="hog")
        results = detector.detect(rgb, scale_factor=1.0, min_face_size=80, min_ipd=30)

        assert len(results) == 1
        assert results[0].is_standard_res is False
        assert results[0].status == "low_resolution"
        assert results[0].width_raw == 40

    @patch("face_recognition.face_locations")
    @patch("face_recognition.face_landmarks")
    def test_accepts_standard_face_size(self, mock_landmarks, mock_locations):
        """Face >= 80px with IPD >= 30px is marked is_standard_res = True."""
        # 100x100 face at scale 1.0
        mock_locations.return_value = [(20, 120, 120, 20)]
        mock_landmarks.return_value = [{
            "left_eye": [(40, 50), (45, 50)],
            "right_eye": [(80, 50), (85, 50)],  # IPD = ~40px
        }]

        rgb = np.zeros((300, 300, 3), dtype=np.uint8)
        detector = DlibFaceDetector(model="hog")
        results = detector.detect(rgb, scale_factor=1.0, min_face_size=80, min_ipd=30)

        assert len(results) == 1
        assert results[0].is_standard_res is True
        assert results[0].status == "valid"
        assert results[0].width_raw == 100
        assert results[0].ipd_raw >= 30.0


class TestRunRecognitionStandardsIntegration:
    """Tests for run_recognition handling low-res faces and result dictionary contract."""

    def test_run_recognition_zero_faces_contract(self, tmp_path, monkeypatch):
        """Ensures all standard keys exist even when 0 faces are detected."""
        dummy_img = tmp_path / "classroom_empty.jpg"
        cv2.imwrite(str(dummy_img), np.ones((720, 1280, 3), dtype=np.uint8) * 128)

        recognition.known_face_encodings = [np.ones(128)]
        recognition.known_face_names = ["TestUser"]

        with patch("aas.recognition.detectors.DlibFaceDetector.detect", return_value=[]):
            res = recognition.run_recognition(str(dummy_img))

        assert res["total_faces"] == 0
        assert res["low_res_count"] == 0
        assert res["present"] == []
        assert "recognized_at" in res
        assert "quality_ok" in res
        assert "face_details" in res

    def test_bypasses_low_resolution_from_matching(self, tmp_path, monkeypatch):
        """Sub-resolution detections are counted in low_res_count and not added to present."""
        dummy_img = tmp_path / "classroom_backrow.jpg"
        cv2.imwrite(str(dummy_img), np.ones((1080, 1920, 3), dtype=np.uint8) * 128)

        recognition.known_face_encodings = [np.ones(128)]
        recognition.known_face_names = ["StudentA"]

        # 1 standard face (100px) and 1 low-res face (35px)
        det_standard = FaceDetection(
            bbox_scaled=(10, 110, 110, 10),
            bbox_raw=(10, 110, 110, 10),
            width_raw=100,
            height_raw=100,
            ipd_raw=38.0,
            landmarks_scaled=None,
            landmarks_raw=None,
            is_standard_res=True,
            status="valid",
        )
        det_low_res = FaceDetection(
            bbox_scaled=(200, 235, 235, 200),
            bbox_raw=(200, 235, 235, 200),
            width_raw=35,
            height_raw=35,
            ipd_raw=14.0,
            landmarks_scaled=None,
            landmarks_raw=None,
            is_standard_res=False,
            status="low_resolution",
        )

        with patch("aas.recognition.detectors.DlibFaceDetector.detect", return_value=[det_standard, det_low_res]), \
             patch("face_recognition.face_encodings", return_value=[np.ones(128)]), \
             patch("face_recognition.compare_faces", return_value=[True]), \
             patch("aas.attendance.spreadsheet.write_to_sheet"):

            res = recognition.run_recognition(str(dummy_img))

        assert res["total_faces"] == 2
        assert res["low_res_count"] == 1
        assert res["present"] == ["StudentA"]
        # face_details should record both for auditing/visualization
        statuses = [f["status"] for f in res["face_details"]]
        assert "recognized" in statuses
        assert "low_resolution" in statuses
