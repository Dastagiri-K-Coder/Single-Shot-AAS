# -*- coding: utf-8 -*-
"""
metrics.py — Mathematical and image metric utilities for AI Facial Recognition.

Provides functions to validate frames and crops against international standards:
  - IEC 62676-4 (DORI Standard): Classroom surveillance & identification resolution.
  - ISO/IEC 19794-5: Interpupillary Distance (IPD) requirements for identification.
  - Image sharpness (Laplacian variance) to avoid blurry encodings.
"""

from __future__ import annotations

import math
from typing import Any
import cv2
import numpy as np


def compute_sharpness(image: np.ndarray) -> float:
    """
    Calculate the sharpness of an image using the variance of the Laplacian operator.

    Higher values indicate a sharper image with distinct edges.
    Values below ~40.0 typically signify significant blurriness or motion blur.

    Args:
        image: BGR or grayscale numpy image array.

    Returns:
        float: Laplacian variance score.
    """
    if image is None or image.size == 0:
        return 0.0

    if len(image.shape) == 3 and image.shape[2] == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif len(image.shape) == 2:
        gray = image
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)

    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    variance = float(laplacian.var())
    return round(variance, 2)


def compute_ipd_from_landmarks(landmarks: dict[str, Any] | list[Any]) -> float:
    """
    Calculate the Interpupillary Distance (IPD) — the Euclidean distance between
    the centers of both eyes.

    Supports:
      1. face_recognition 68-point landmark dictionary:
         {'left_eye': [(x, y), ...], 'right_eye': [(x, y), ...]}
      2. 5-point landmark list/tuple:
         [(right_eye_x, right_eye_y), (left_eye_x, left_eye_y), ...]

    Args:
        landmarks: Landmark data structure.

    Returns:
        float: Interpupillary distance in pixels, or 0.0 if cannot be determined.
    """
    if not landmarks:
        return 0.0

    left_center = None
    right_center = None

    # Case 1: dictionary containing 'left_eye' and 'right_eye'
    if isinstance(landmarks, dict):
        if "left_eye" in landmarks and "right_eye" in landmarks:
            left_pts = np.array(landmarks["left_eye"])
            right_pts = np.array(landmarks["right_eye"])
            if len(left_pts) > 0 and len(right_pts) > 0:
                left_center = (float(left_pts[:, 0].mean()), float(left_pts[:, 1].mean()))
                right_center = (float(right_pts[:, 0].mean()), float(right_pts[:, 1].mean()))

    # Case 2: 5-point array/list (typically [right_eye, left_eye, nose, right_mouth, left_mouth])
    elif isinstance(landmarks, (list, tuple, np.ndarray)) and len(landmarks) >= 2:
        pt0 = landmarks[0]
        pt1 = landmarks[1]
        right_center = (float(pt0[0]), float(pt0[1]))
        left_center = (float(pt1[0]), float(pt1[1]))

    if left_center is None or right_center is None:
        return 0.0

    dx = right_center[0] - left_center[0]
    dy = right_center[1] - left_center[1]
    return round(math.hypot(dx, dy), 2)


def validate_classroom_frame(
    frame: np.ndarray,
    min_width: int = 1280,
    recommended_width: int = 1920,
    blur_threshold: float = 40.0,
    brightness_min: float = 40.0,
) -> tuple[bool, str, dict[str, Any]]:
    """
    Perform multi-criteria quality check on a captured classroom frame.

    Args:
        frame: BGR image array.
        min_width: Absolute minimum image width allowed.
        recommended_width: Recommended resolution for 35-60 student classroom (Full HD/4K).
        blur_threshold: Minimum acceptable Laplacian variance.
        brightness_min: Minimum mean grayscale brightness.

    Returns:
        (passed: bool, message: str, metrics: dict)
    """
    if frame is None or frame.size == 0:
        return False, "Empty or invalid frame", {}

    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    sharpness = compute_sharpness(gray)

    metrics = {
        "width": w,
        "height": h,
        "brightness": round(brightness, 1),
        "sharpness": sharpness,
        "is_recommended_classroom_res": w >= recommended_width,
    }

    if w < min_width:
        msg = f"Image resolution too low ({w}×{h} px). Minimum required: {min_width} px."
        return False, msg, metrics

    if brightness < brightness_min:
        msg = f"Image too dark (brightness={brightness:.1f} < {brightness_min}). Ensure classroom lighting."
        return False, msg, metrics

    if sharpness < blur_threshold:
        msg = f"Image blurry (sharpness={sharpness:.1f} < {blur_threshold}). Camera may be out of focus."
        return False, msg, metrics

    if w < recommended_width:
        msg = (
            f"Image resolution ({w}×{h} px) meets minimum {min_width} px, but is below "
            f"recommended {recommended_width} px for back-row students."
        )
        return True, msg, metrics

    return True, "OK", metrics


def calculate_adaptive_scale(
    width: int,
    height: int,
    user_scale: float | None = None,
    auto_scale: bool = True,
) -> float:
    """
    Calculate the optimal downscaling factor for facial detection.

    Why this matters:
      - At 1080p (1920x1080), back-row student faces are ~60-80px. Downscaling to 0.25
        reduces them to 15-20px (undetectable). Therefore, 1080p must use scale 1.0.
      - At 4K (3840x2160), scaling by 0.5 results in a 1920x1080 canvas, preserving
        faces at 60-100px while saving 75% memory/compute.

    Args:
        width: Frame width in pixels.
        height: Frame height in pixels.
        user_scale: Configured scale value (if user wants to override).
        auto_scale: Whether adaptive scaling is enabled.

    Returns:
        float: Scale factor between 0.1 and 1.0.
    """
    if not auto_scale and user_scale is not None and user_scale > 0:
        return float(min(1.0, max(0.1, user_scale)))

    # If width is 4K or above (>= 3840px)
    if width >= 3840:
        return 0.5
    # If width is 2K / 1440p (>= 2560px)
    elif width >= 2560:
        return 0.75
    # If width is Full HD (1080p) or below (< 2560px)
    else:
        return 1.0
