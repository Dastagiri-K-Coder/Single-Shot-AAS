# -*- coding: utf-8 -*-
"""
detectors.py — Multi-scale face detection engine and landmark alignment for Single Shot AAS.

Wraps detection models with unified output format, projecting bounding boxes
and landmarks to original image resolution to evaluate against international
identification standards (IEC 62676-4 and ISO/IEC 19794-5).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import os
import cv2
import face_recognition
import numpy as np

from aas.recognition.metrics import compute_ipd_from_landmarks


@dataclass
class FaceDetection:
    """Represents a detected face with both scaled and native-resolution metrics."""
    bbox_scaled: tuple[int, int, int, int]  # (top, right, bottom, left)
    bbox_raw: tuple[int, int, int, int]     # (top, right, bottom, left) in original image
    width_raw: int
    height_raw: int
    ipd_raw: float
    landmarks_scaled: dict[str, Any] | list[Any] | None
    landmarks_raw: dict[str, Any] | list[Any] | None
    is_standard_res: bool
    status: str = "valid"  # "valid" | "low_resolution" | "low_ipd"


class BaseFaceDetector:
    """Abstract interface for face detectors."""

    def detect(
        self,
        rgb_scaled: np.ndarray,
        scale_factor: float,
        min_face_size: int = 80,
        min_ipd: int = 30,
    ) -> list[FaceDetection]:
        raise NotImplementedError


class DlibFaceDetector(BaseFaceDetector):
    """
    Standard dlib face detector (HOG or CNN) via face_recognition library.
    Extracts 68-point landmarks to measure exact eye-to-eye pixel distance (IPD).
    """

    def __init__(self, model: str = "hog"):
        self.model = model.lower() if model.lower() in ("hog", "cnn") else "hog"

    def detect(
        self,
        rgb_scaled: np.ndarray,
        scale_factor: float,
        min_face_size: int = 80,
        min_ipd: int = 30,
    ) -> list[FaceDetection]:
        locations = face_recognition.face_locations(rgb_scaled, model=self.model)
        if not locations:
            return []

        # Extract 68-point facial landmarks for alignment and IPD
        landmarks_list = face_recognition.face_landmarks(rgb_scaled, locations)

        inv_scale = 1.0 / scale_factor if scale_factor > 0 else 1.0
        results: list[FaceDetection] = []

        for idx, loc in enumerate(locations):
            top, right, bottom, left = loc
            raw_top = int(round(top * inv_scale))
            raw_right = int(round(right * inv_scale))
            raw_bottom = int(round(bottom * inv_scale))
            raw_left = int(round(left * inv_scale))

            raw_w = max(0, raw_right - raw_left)
            raw_h = max(0, raw_bottom - raw_top)

            # Map landmarks to raw coordinates
            lm_scaled = landmarks_list[idx] if idx < len(landmarks_list) else None
            lm_raw = None
            raw_ipd = 0.0

            if lm_scaled:
                lm_raw = {}
                for feature, pts in lm_scaled.items():
                    lm_raw[feature] = [
                        (int(round(pt[0] * inv_scale)), int(round(pt[1] * inv_scale)))
                        for pt in pts
                    ]
                raw_ipd = compute_ipd_from_landmarks(lm_raw)

            # Check standards compliance:
            # Face crop >= min_face_size (80px) and IPD >= min_ipd (30px)
            is_standard = True
            status = "valid"

            if raw_w < min_face_size or raw_h < min_face_size:
                is_standard = False
                status = "low_resolution"
            elif raw_ipd > 0 and raw_ipd < min_ipd:
                is_standard = False
                status = "low_ipd"

            results.append(
                FaceDetection(
                    bbox_scaled=(top, right, bottom, left),
                    bbox_raw=(raw_top, raw_right, raw_bottom, raw_left),
                    width_raw=raw_w,
                    height_raw=raw_h,
                    ipd_raw=raw_ipd,
                    landmarks_scaled=lm_scaled,
                    landmarks_raw=lm_raw,
                    is_standard_res=is_standard,
                    status=status,
                )
            )

        return results


class YuNetFaceDetector(BaseFaceDetector):
    """
    OpenCV built-in YuNet FaceDetectorYN (multi-scale anchor/FPN based).
    Fast, highly accurate on small and dense faces down to 10x10 px.
    Falls back to DlibFaceDetector if model file is not present.
    """

    def __init__(self, model_path: str | None = None, score_threshold: float = 0.6):
        self.model_path = model_path
        self.score_threshold = score_threshold
        self.fallback = DlibFaceDetector(model="hog")
        self._detector = None

        if model_path and os.path.exists(model_path):
            try:
                self._detector = cv2.FaceDetectorYN.create(
                    model=model_path,
                    config="",
                    input_size=(320, 320),
                    score_threshold=score_threshold,
                    nms_threshold=0.3,
                    top_k=5000,
                )
            except Exception as e:
                print(f"  [WARN] Failed to initialize YuNet detector ({e}); falling back to dlib.")
                self._detector = None

    def detect(
        self,
        rgb_scaled: np.ndarray,
        scale_factor: float,
        min_face_size: int = 80,
        min_ipd: int = 30,
    ) -> list[FaceDetection]:
        if self._detector is None:
            return self.fallback.detect(rgb_scaled, scale_factor, min_face_size, min_ipd)

        h, w = rgb_scaled.shape[:2]
        self._detector.setInputSize((w, h))

        # YuNet expects BGR format
        bgr_scaled = rgb_scaled[:, :, ::-1]
        _, faces = self._detector.detect(bgr_scaled)

        if faces is None or len(faces) == 0:
            return []

        inv_scale = 1.0 / scale_factor if scale_factor > 0 else 1.0
        results: list[FaceDetection] = []

        for face in faces:
            # face: [x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score]
            x, y, fw, fh = int(face[0]), int(face[1]), int(face[2]), int(face[3])
            # Expand YuNet bbox by 10% to approximate dlib's detection margins
            pad_w = int(fw * 0.10)
            pad_h = int(fh * 0.10)
            top = max(0, y - pad_h)
            left = max(0, x - pad_w)
            bottom = min(h, y + fh + pad_h)
            right = min(w, x + fw + pad_w)

            raw_top = int(round(top * inv_scale))
            raw_right = int(round(right * inv_scale))
            raw_bottom = int(round(bottom * inv_scale))
            raw_left = int(round(left * inv_scale))
            raw_w = max(0, raw_right - raw_left)
            raw_h = max(0, raw_bottom - raw_top)

            # 5 landmarks: right_eye (re), left_eye (le)
            re_x, re_y = face[4] * inv_scale, face[5] * inv_scale
            le_x, le_y = face[6] * inv_scale, face[7] * inv_scale
            raw_ipd = round(float(np.hypot(re_x - le_x, re_y - le_y)), 2)

            is_standard = (raw_w >= min_face_size and raw_h >= min_face_size)
            status = "valid"
            if not is_standard:
                status = "low_resolution"
            elif raw_ipd > 0 and raw_ipd < min_ipd:
                is_standard = False
                status = "low_ipd"

            results.append(
                FaceDetection(
                    bbox_scaled=(top, right, bottom, left),
                    bbox_raw=(raw_top, raw_right, raw_bottom, raw_left),
                    width_raw=raw_w,
                    height_raw=raw_h,
                    ipd_raw=raw_ipd,
                    landmarks_scaled=None,
                    landmarks_raw=None,
                    is_standard_res=is_standard,
                    status=status,
                )
            )

        return results


def get_detector(model_name: str = "hog") -> BaseFaceDetector:
    """
    Factory function to retrieve the configured face detector.

    Supports:
        - "hog"   : CPU-fast dlib HOG detector
        - "cnn"   : dlib CUDA MMOD detector
        - "yunet" : OpenCV YuNet FPN detector (falls back to HOG if weights missing)
    """
    m = model_name.lower()
    if m == "yunet":
        # Check standard model directory
        weights = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "face_detection_yunet_2023mar.onnx"
        )
        return YuNetFaceDetector(model_path=weights)
    return DlibFaceDetector(model=m)
