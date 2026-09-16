# -*- coding: utf-8 -*-
"""Face recognition engine, detectors, and quality metrics."""

from aas.recognition.engine import (
    run_recognition,
    annotate_image,
    load_facial_encodings_and_names_from_memory,
)
from aas.recognition.detectors import get_detector, FaceDetection
from aas.recognition.metrics import (
    compute_sharpness,
    compute_ipd_from_landmarks,
    validate_classroom_frame,
)

__all__ = [
    "run_recognition",
    "annotate_image",
    "load_facial_encodings_and_names_from_memory",
    "get_detector",
    "FaceDetection",
    "compute_sharpness",
    "compute_ipd_from_landmarks",
    "validate_classroom_frame",
]
