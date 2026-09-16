# -*- coding: utf-8 -*-
"""
recognition.py — Face recognition engine for AI Attendance System.

Designed for SINGLE-SHOT classroom images (not live video).
Detects and identifies ALL faces in one photo simultaneously.
Upgraded to conform with international identification standards:
  - IEC 62676-4 (DORI Standard: Standard Identification requires >= 80x80 px)
  - ISO/IEC 19794-5 (IPD: Eye-to-eye distance >= 30 px)
  - Multi-scale detection (YuNet FPN & dlib HOG/CNN fallback)
  - Adaptive resolution scaling (prevents destroying back-row faces)
  - Per-face quality gating (flags sub-resolution faces before matching)

Functions:
    load_facial_encodings_and_names_from_memory()  → load all .pkl encodings
    run_recognition(image_path)                    → process image, return results
    annotate_image(image_path, results)            → draw boxes on image (optional)
"""

from __future__ import annotations

import os
import datetime
from typing import Any

import cv2
import face_recognition
import numpy as np

from aas.core.config import (
    ENCODINGS_FOLDER,
    CAPTURED_FOLDER,
    RECOGNITION_TOLERANCE,
    RECOGNITION_SCALE,
    AUTO_SCALE_DETECTION,
    MIN_FACE_SIZE,
    MIN_IPD_PIXELS,
    BLUR_THRESHOLD,
    MIN_IMAGE_WIDTH,
    RECOMMENDED_IMAGE_WIDTH,
    FACE_DETECTION_MODEL,
)
from aas.recognition.metrics import validate_classroom_frame, calculate_adaptive_scale
from aas.recognition.detectors import get_detector, FaceDetection
from aas.core.safe_pickle import safe_load as _safe_load

# ── In-memory stores (populated by load_facial_encodings_and_names_from_memory) ─
known_face_encodings: list = []
known_face_names:     list = []
known_face_genders:   dict = {}   # name → 'M' | 'F' | 'O'


def load_facial_encodings_and_names_from_memory() -> None:
    """
    Load all student face encodings from the encodings folder into memory.

    Supports two .pkl formats:
      New (v2): dict {"name": str, "gender": str, "encodings": [...]}
      Legacy  : bare list of 128-D arrays  → auto-upgraded, gender defaults to 'M'
    """
    global known_face_encodings, known_face_names, known_face_genders
    known_face_encodings.clear()
    known_face_names.clear()
    known_face_genders.clear()

    if not os.path.isdir(ENCODINGS_FOLDER):
        raise FileNotFoundError(f"Encodings folder not found: {ENCODINGS_FOLDER}")

    loaded = 0
    for filename in os.listdir(ENCODINGS_FOLDER):
        if not filename.lower().endswith('.pkl'):
            continue

        name     = filename[:-4]
        pkl_path = os.path.join(ENCODINGS_FOLDER, filename)

        payload = _safe_load(pkl_path)

        # Detect format
        if isinstance(payload, dict):
            encodings = payload.get("encodings", [])
            gender    = payload.get("gender", "M")
            name      = payload.get("name", name)
        elif isinstance(payload, list):
            encodings = payload
            gender    = "M"   # legacy default
        else:
            encodings = [payload]
            gender    = "M"

        known_face_genders[name] = gender

        for enc in (encodings if isinstance(encodings, list) else [encodings]):
            known_face_encodings.append(enc)
            known_face_names.append(name)
            loaded += 1

    print(f"✓ Loaded {loaded} encoding(s) for {len(set(known_face_names))} student(s).")


def _check_image_quality(frame: np.ndarray) -> tuple[bool, str]:
    """
    Perform basic image quality checks before running recognition.
    Preserved for backward compatibility and fast validation.

    Args:
        frame: BGR image array (as returned by cv2.imread).

    Returns:
        (ok: bool, message: str)
    """
    if frame is None or frame.size == 0:
        return False, "Empty frame"

    h, w = frame.shape[:2]
    if w < 320:
        return False, f"Image too small ({w}×{h}). Minimum width: 320 px."

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    if brightness < 40:
        return False, f"Image too dark (brightness={brightness:.1f}). Ensure good lighting."

    return True, "OK"


def run_recognition(image_path: str) -> dict:
    """
    Process a single classroom image and mark attendance for all recognized students.

    Standards-Compliant Pipeline:
        1. Load image and perform full quality / classroom resolution check.
        2. Compute adaptive scaling to avoid destroying distant back-row faces.
        3. Detect all face locations and 5/68-point landmarks via multi-scale detector.
        4. Measure face crop width and Interpupillary Distance (IPD) in native pixels.
        5. Filter out sub-standard faces (<80px or <30px IPD) to prevent false positives.
        6. Generate 128-D encodings and perform Euclidean distance comparison.
        7. Update attendance sheet for verified matches.
        8. Return comprehensive analytics dictionary.

    Args:
        image_path: Absolute or relative path to the classroom JPEG/PNG.

    Returns:
        dict with keys:
            'present'        → list of recognized student names
            'present_genders'→ dict of student name to gender
            'boys_count'     → count of present male students
            'girls_count'    → count of present female students
            'other_count'    → count of present other students
            'unknown_count'  → count of standard faces with no match
            'low_res_count'  → count of detected faces failing 80px/30px IPD standard
            'total_faces'    → total faces detected in image
            'recognized_at'  → ISO timestamp
            'quality_ok'     → boolean
            'quality_msg'    → quality validation summary
            'face_details'   → per-face bounding boxes, metrics and classification
    """
    if not known_face_encodings:
        raise RuntimeError(
            "No face encodings loaded. "
            "Call load_facial_encodings_and_names_from_memory() first."
        )

    # ── 1. Load image ──────────────────────────────────────────────────────────
    frame = cv2.imread(image_path)
    if frame is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    h_raw, w_raw = frame.shape[:2]
    print(f"Processing image: {image_path}")
    print(f"  Raw image size: {w_raw}×{h_raw} px")

    # ── 1b. Image quality check ────────────────────────────────────────────────
    # Check baseline (fast check)
    base_ok, base_msg = _check_image_quality(frame)

    # Check classroom standards
    quality_ok, quality_msg, frame_metrics = validate_classroom_frame(
        frame,
        min_width=MIN_IMAGE_WIDTH,
        recommended_width=RECOMMENDED_IMAGE_WIDTH,
        blur_threshold=BLUR_THRESHOLD,
    )

    if not base_ok:
        quality_ok = False
        quality_msg = base_msg
        print(f"  [WARN] Baseline quality check failed: {quality_msg}")
    elif not quality_ok:
        print(f"  [WARN] Classroom standard check: {quality_msg}")
    elif quality_msg != "OK":
        print(f"  [INFO] Classroom notice: {quality_msg}")

    # ── 2. Adaptive scale calculation ──────────────────────────────────────────
    scale = calculate_adaptive_scale(
        w_raw,
        h_raw,
        user_scale=RECOGNITION_SCALE,
        auto_scale=AUTO_SCALE_DETECTION,
    )
    print(f"  Working scale factor: {scale:.2f} (canvas: {int(w_raw * scale)}×{int(h_raw * scale)} px)")

    if scale < 1.0:
        small_frame = cv2.resize(frame, (0, 0), fx=scale, fy=scale)
    else:
        small_frame = frame

    rgb_frame = small_frame[:, :, ::-1]

    # ── 3. Multi-scale face detection & landmark alignment ─────────────────────
    detector = get_detector(FACE_DETECTION_MODEL)
    detections = detector.detect(
        rgb_frame,
        scale_factor=scale,
        min_face_size=MIN_FACE_SIZE,
        min_ipd=MIN_IPD_PIXELS,
    )

    total_faces = len(detections)
    print(f"  Detected {total_faces} face(s) in image (model={FACE_DETECTION_MODEL}).")

    recognized_at = datetime.datetime.now().isoformat()

    if not detections:
        print("  [WARN] No faces detected. Check image quality or lighting.")
        return {
            "present":         [],
            "present_genders": {},
            "boys_count":      0,
            "girls_count":     0,
            "other_count":     0,
            "unknown_count":   0,
            "low_res_count":   0,
            "total_faces":     0,
            "recognized_at":   recognized_at,
            "quality_ok":      quality_ok,
            "quality_msg":     quality_msg,
            "face_details":    [],
        }

    # ── 4. Separate standards-compliant vs. sub-resolution faces ───────────────
    valid_detections = [d for d in detections if d.is_standard_res]
    substandard_detections = [d for d in detections if not d.is_standard_res]
    low_res_count = len(substandard_detections)

    if low_res_count > 0:
        print(f"  [WARN] {low_res_count} face(s) below standard resolution (<{MIN_FACE_SIZE}px or IPD<{MIN_IPD_PIXELS}px).")
        print("         Substandard crops bypassed from matching to prevent false identifications.")

    # ── 5. Generate 128-D encodings for standard faces ─────────────────────────
    valid_locations = [d.bbox_scaled for d in valid_detections]
    face_encodings = (
        face_recognition.face_encodings(rgb_frame, valid_locations)
        if valid_locations
        else []
    )

    # ── 6. Match each standard face against enrolled identities ────────────────
    present: list[str] = []
    unknown_count = 0
    face_details: list[dict[str, Any]] = []

    for det, face_encoding in zip(valid_detections, face_encodings):
        distances     = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_idx      = int(np.argmin(distances))
        best_distance = float(distances[best_idx])

        matches = face_recognition.compare_faces(
            known_face_encodings,
            face_encoding,
            tolerance=RECOGNITION_TOLERANCE,
        )

        if matches[best_idx]:
            name = known_face_names[best_idx]
            confidence = round((1.0 - best_distance) * 100.0, 1)
            print(f"    ✓ Recognized: {name} ({confidence}% conf, size={det.width_raw}px, IPD={det.ipd_raw}px)")

            if name not in present:
                present.append(name)

            face_details.append({
                "name": name,
                "bbox": det.bbox_raw,
                "width": det.width_raw,
                "height": det.height_raw,
                "ipd": det.ipd_raw,
                "confidence": confidence,
                "status": "recognized",
            })
        else:
            unknown_count += 1
            print(f"    ? Unknown face (dist={best_distance:.3f}, size={det.width_raw}px, IPD={det.ipd_raw}px)")
            face_details.append({
                "name": "Unknown",
                "bbox": det.bbox_raw,
                "width": det.width_raw,
                "height": det.height_raw,
                "ipd": det.ipd_raw,
                "confidence": 0.0,
                "status": "unknown",
            })

    # Record substandard faces in details for audit logging and visualization
    for det in substandard_detections:
        face_details.append({
            "name": "Low Resolution",
            "bbox": det.bbox_raw,
            "width": det.width_raw,
            "height": det.height_raw,
            "ipd": det.ipd_raw,
            "confidence": 0.0,
            "status": det.status,
        })

    # Count boys and girls from recognized names
    boys_count  = sum(1 for n in present if known_face_genders.get(n, "M") == "M")
    girls_count = sum(1 for n in present if known_face_genders.get(n, "M") == "F")
    other_count = len(present) - boys_count - girls_count

    summary = {
        "present":         present,
        "present_genders": {n: known_face_genders.get(n, "M") for n in present},
        "boys_count":      boys_count,
        "girls_count":     girls_count,
        "other_count":     other_count,
        "unknown_count":   unknown_count,
        "low_res_count":   low_res_count,
        "total_faces":     total_faces,
        "recognized_at":   recognized_at,
        "quality_ok":      quality_ok,
        "quality_msg":     quality_msg,
        "face_details":    face_details,
    }

    print(
        f"\n  Summary → Present: {len(present)} (Boys:{boys_count} Girls:{girls_count}) "
        f"| Unknown: {unknown_count} | Low-Res: {low_res_count} | Total faces: {total_faces}"
    )
    return summary


def annotate_image(image_path: str, results: dict, output_path: str = None) -> str | None:
    """
    Draw color-coded bounding boxes and resolution labels on the classroom image.

    Color Scheme:
      - 🟢 Green: Recognized Student (name + confidence + pixel size)
      - 🟡 Amber: Substandard Resolution Warning (size or IPD below standard)
      - 🔴 Red: Unknown Face (unrecognized identity)

    Args:
        image_path  : Path to the original classroom image.
        results     : Dict returned by run_recognition().
        output_path : Where to save the annotated image.

    Returns:
        Path to the saved annotated image, or None if the image cannot be read.
    """
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"  [WARN] annotate_image: cannot read {image_path} — skipping annotation.")
        return None

    h, w = frame.shape[:2]
    face_details = results.get("face_details", [])

    if face_details:
        for item in face_details:
            top, right, bottom, left = item["bbox"]
            status = item.get("status", "unknown")
            name = item.get("name", "Unknown").replace('_', ' ')
            face_w = item.get("width", right - left)
            conf = item.get("confidence", 0.0)

            # Clamp coords
            top = max(0, min(h, top))
            left = max(0, min(w, left))
            bottom = max(0, min(h, bottom))
            right = max(0, min(w, right))

            if status == "recognized":
                color = (0, 200, 0)      # Green
                label = f"{name} ({conf:.0f}% - {face_w}px)"
            elif status in ("low_resolution", "low_ipd"):
                color = (0, 165, 255)    # Amber / Orange
                label = f"Low Res ({face_w}px < {MIN_FACE_SIZE}px)"
            else:
                color = (0, 0, 220)      # Red
                label = f"Unknown ({face_w}px)"

            cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
            cv2.rectangle(frame, (left, bottom - 26), (right, bottom), color, cv2.FILLED)
            cv2.putText(
                frame,
                label,
                (left + 4, bottom - 7),
                cv2.FONT_HERSHEY_DUPLEX,
                0.55,
                (255, 255, 255),
                1,
            )
    else:
        # Fallback if no face_details present (e.g. legacy callers)
        locations = face_recognition.face_locations(frame[:, :, ::-1])
        for top, right, bottom, left in locations:
            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 220), 2)

    if output_path is None:
        os.makedirs(CAPTURED_FOLDER, exist_ok=True)
        stem = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(CAPTURED_FOLDER, f"{stem}_annotated.jpg")

    cv2.imwrite(output_path, frame)
    print(f"  ✓ Annotated image saved: {output_path}")
    return output_path
