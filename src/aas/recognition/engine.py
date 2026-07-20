# -*- coding: utf-8 -*-
"""
recognition.py — Face recognition engine for AI Attendance System.

Designed for SINGLE-SHOT classroom images (not live video).
Detects and identifies ALL faces in one photo simultaneously.

Key changes from original:
  - Accepts a still image path (not a video loop)
  - Marks ALL recognized students (not just face_names[0])
  - Handles 3-angle encodings per student (front/left/right)
  - Cross-platform (no cv2.CAP_DSHOW Windows flag)
  - Configurable tolerance via config.py
  - Image quality pre-check (brightness + minimum resolution)
  - recognized_at timestamp in result dict
  - Annotated images saved to CAPTURED_FOLDER

Functions:
    load_facial_encodings_and_names_from_memory()  → load all .pkl encodings
    run_recognition(image_path)                    → process image, return results
    annotate_image(image_path, results)            → draw boxes on image (optional)
"""

import os
import pickle
import datetime

import cv2
import face_recognition
import numpy as np

from aas.core.config import (
    ENCODINGS_FOLDER,
    CAPTURED_FOLDER,
    RECOGNITION_TOLERANCE,
    RECOGNITION_SCALE,
    FACE_DETECTION_MODEL,
)
from aas.attendance import spreadsheet

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

        with open(pkl_path, 'rb') as fp:
            payload = pickle.load(fp)

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

    Args:
        frame: BGR image array (as returned by cv2.imread).

    Returns:
        (ok: bool, message: str)
            ok=True  → image passes quality checks
            ok=False → image is too dark or too small; recognition may be poor
    """
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

    Steps:
        1. Load image from disk
        2. Resize to RECOGNITION_SCALE for speed (default 0.25 = quarter size)
        3. Detect ALL face locations in the image
        4. Generate 128-D encodings for each face
        5. Compare against known encodings (Euclidean distance)
        6. For each match: call spreadsheet.write_to_sheet(name)
        7. Return summary dict

    Args:
        image_path: Absolute or relative path to the classroom JPEG/PNG.

    Returns:
        dict with keys:
            'present'       → list of recognized student names
            'unknown_count' → number of faces that could not be identified
            'total_faces'   → total faces detected in image
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

    # ── 1b. Image quality pre-check ────────────────────────────────────────────
    quality_ok, quality_msg = _check_image_quality(frame)
    if not quality_ok:
        print(f"  [WARN] Quality check failed: {quality_msg}")
        print("  Attempting recognition anyway — results may be unreliable.")

    print(f"Processing image: {image_path}")
    print(f"  Image size: {frame.shape[1]}×{frame.shape[0]} px")

    # ── 2. Resize for faster processing ───────────────────────────────────────
    small_frame = cv2.resize(frame, (0, 0),
                             fx=RECOGNITION_SCALE,
                             fy=RECOGNITION_SCALE)

    # ── 3. Convert BGR (OpenCV) → RGB (face_recognition) ──────────────────────
    rgb_frame = small_frame[:, :, ::-1]

    # ── 4. Detect all face locations ─────────────────────────────────────────────
    face_locations = face_recognition.face_locations(rgb_frame, model=FACE_DETECTION_MODEL)
    print(f"  Detected {len(face_locations)} face(s) in image (model={FACE_DETECTION_MODEL}).")

    if not face_locations:
        print("  [WARN] No faces detected. Check image quality or lighting.")
        return {"present": [], "unknown_count": 0, "total_faces": 0}

    # ── 5. Generate encodings for all detected faces ───────────────────────────
    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

    # ── 6. Match each face against known encodings ─────────────────────────────
    present       = []
    unknown_count = 0

    for face_encoding in face_encodings:
        distances     = face_recognition.face_distance(known_face_encodings, face_encoding)
        best_idx      = int(np.argmin(distances))
        best_distance = distances[best_idx]

        # compare_faces with our configured tolerance
        matches = face_recognition.compare_faces(
            known_face_encodings,
            face_encoding,
            tolerance=RECOGNITION_TOLERANCE
        )

        if matches[best_idx]:
            name = known_face_names[best_idx]
            confidence = round((1 - best_distance) * 100, 1)  # % similarity
            print(f"    ✓ Recognized: {name} ({confidence}% confidence)")

            if name not in present:   # avoid duplicate if 2 angles match same person
                present.append(name)
                spreadsheet.write_to_sheet(name)
        else:
            unknown_count += 1
            print(f"    ? Unknown face (distance={best_distance:.3f})")

    recognized_at = datetime.datetime.now().isoformat()

    # Count boys and girls from recognized names
    boys_count  = sum(1 for n in present if known_face_genders.get(n, "M") == "M")
    girls_count = sum(1 for n in present if known_face_genders.get(n, "F") == "F")
    other_count = len(present) - boys_count - girls_count

    summary = {
        "present":        present,
        "present_genders": {n: known_face_genders.get(n, "M") for n in present},
        "boys_count":     boys_count,
        "girls_count":    girls_count,
        "other_count":    other_count,
        "unknown_count":  unknown_count,
        "total_faces":    len(face_locations),
        "recognized_at":  recognized_at,
        "quality_ok":     quality_ok,
        "quality_msg":    quality_msg,
    }
    print(f"\n  Summary → Present: {len(present)} (Boys:{boys_count} Girls:{girls_count}) "
          f"| Unknown: {unknown_count} | Total faces: {len(face_locations)}")
    return summary


def annotate_image(image_path: str, results: dict, output_path: str = None) -> str | None:
    """
    Draw bounding boxes and name labels on the classroom image.
    Saves the result to CAPTURED_FOLDER (not alongside the source image).
    Useful for debugging or faculty review.

    Args:
        image_path  : Path to the original classroom image.
        results     : Dict returned by run_recognition().
        output_path : Where to save the annotated image.
                      Defaults to CAPTURED_FOLDER/<original_stem>_annotated.jpg

    Returns:
        Path to the saved annotated image, or None if the image cannot be read.
    """
    frame = cv2.imread(image_path)
    if frame is None:
        print(f"  [WARN] annotate_image: cannot read {image_path} — skipping annotation.")
        return None

    small = cv2.resize(frame, (0, 0), fx=RECOGNITION_SCALE, fy=RECOGNITION_SCALE)
    rgb   = small[:, :, ::-1]

    locations = face_recognition.face_locations(rgb)
    encodings = face_recognition.face_encodings(rgb, locations)

    scale = max(1, int(round(1 / RECOGNITION_SCALE)))

    for (top, right, bottom, left), enc in zip(locations, encodings):
        if known_face_encodings:
            distances = face_recognition.face_distance(known_face_encodings, enc)
            best_idx  = int(np.argmin(distances))
            matches   = face_recognition.compare_faces(
                known_face_encodings, enc, tolerance=RECOGNITION_TOLERANCE
            )
            name  = known_face_names[best_idx] if matches[best_idx] else "Unknown"
        else:
            name = "Unknown"

        color = (0, 200, 0) if name != "Unknown" else (0, 0, 220)  # Green / Red

        # Scale back to original image size
        top    *= scale; right  *= scale
        bottom *= scale; left   *= scale

        # Clamp to image boundaries
        h, w = frame.shape[:2]
        top    = max(0, top);    left  = max(0, left)
        bottom = min(h, bottom); right = min(w, right)

        cv2.rectangle(frame, (left, top), (right, bottom), color, 2)
        cv2.rectangle(frame, (left, bottom - 30), (right, bottom), color, cv2.FILLED)
        cv2.putText(frame, name.replace('_', ' '), (left + 5, bottom - 8),
                    cv2.FONT_HERSHEY_DUPLEX, 0.65, (255, 255, 255), 1)

    if output_path is None:
        os.makedirs(CAPTURED_FOLDER, exist_ok=True)
        stem = os.path.splitext(os.path.basename(image_path))[0]
        output_path = os.path.join(CAPTURED_FOLDER, f"{stem}_annotated.jpg")

    cv2.imwrite(output_path, frame)
    print(f"  ✓ Annotated image saved: {output_path}")
    return output_path
