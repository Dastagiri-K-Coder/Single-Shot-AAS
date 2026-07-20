# -*- coding: utf-8 -*-
"""
enroll.py — Student enrollment module for Single Shot AAS.

Captures a student's face from 3 angles (front, left, right) via webcam,
generates 128-D face encodings for each angle, and saves them as a single
.pkl file.

v2 changes:
  - .pkl now stores a dict: {"name": str, "gender": str, "encodings": [...]}
    instead of a bare list. Allows Boys/Girls count in attendance summary.
  - enroll_student_3angles accepts gender parameter
  - All functions accept gender (default 'M')

Gender values: 'M' = Male, 'F' = Female, 'O' = Other

Functions:
    enroll_student_3angles(name, gender)      → guided 3-angle webcam capture
    encoding_of_enrolled_person(name, image)  → encode a single image file
    batch_enroll_from_folder(folder)          → bulk enroll from a photos folder
"""

import os
import pickle

import cv2
import face_recognition

from aas.core.config import PHOTO_FOLDER, ENCODINGS_FOLDER, WEBCAM_INDEX
from aas.attendance import spreadsheet

# Angles for the 3-shot enrollment workflow
_ANGLES = [
    ("FRONT",  "Look straight at the camera"),
    ("LEFT",   "Slowly turn your head to the LEFT"),
    ("RIGHT",  "Slowly turn your head to the RIGHT"),
]


def _save_encoding(name: str, encodings: list, gender: str = "M") -> str:
    """
    Save face encodings to a .pkl file as a structured dict.

    Format: {"name": str, "gender": str, "encodings": [128-D arrays]}

    Args:
        name      : Student name (used as filename).
        encodings : List of 128-D numpy arrays.
        gender    : 'M' | 'F' | 'O'

    Returns:
        Path to saved .pkl file.
    """
    os.makedirs(ENCODINGS_FOLDER, exist_ok=True)
    pkl_path = os.path.join(ENCODINGS_FOLDER, f"{name}.pkl")
    payload = {
        "name":      name,
        "gender":    gender.upper(),
        "encodings": encodings,
    }
    with open(pkl_path, 'wb') as fp:
        pickle.dump(payload, fp)
    return pkl_path


def encoding_of_enrolled_person(name: str, image_path: str, gender: str = "M") -> bool:
    """
    Generate and save a face encoding from a single image file.
    Appends to existing encodings if the student already has a .pkl.

    Args:
        name       : Student name.
        image_path : Path to the student's photo (JPG/PNG).
        gender     : 'M' | 'F' | 'O' (default 'M')

    Returns:
        True if encoding succeeded, False if no face found.
    """
    img = face_recognition.load_image_file(image_path)
    locations = face_recognition.face_locations(img)

    if not locations:
        print(f"  [WARN] No face detected in: {image_path}")
        return False

    new_enc = face_recognition.face_encodings(img, locations)[0]

    # Load existing encodings (if any) and append
    pkl_path = os.path.join(ENCODINGS_FOLDER, f"{name}.pkl")
    existing_encodings = []
    existing_gender = gender
    if os.path.exists(pkl_path):
        with open(pkl_path, 'rb') as fp:
            payload = pickle.load(fp)
        # Support both new dict format and legacy bare-list format
        if isinstance(payload, dict):
            existing_encodings = payload.get("encodings", [])
            existing_gender    = payload.get("gender", gender)
        elif isinstance(payload, list):
            existing_encodings = payload  # legacy upgrade
        else:
            existing_encodings = [payload]

    existing_encodings.append(new_enc)
    _save_encoding(name, existing_encodings, gender=existing_gender)
    print(f"  ✓ Encoding saved for '{name}' ({len(existing_encodings)} angle(s), gender={existing_gender})")
    return True


def enroll_student_3angles(name: str, gender: str = "M") -> None:
    """
    Guided 3-angle face enrollment via webcam.

    Args:
        name:   Student's full name.
        gender: 'M' | 'F' | 'O' (default 'M')
    """
    os.makedirs(PHOTO_FOLDER, exist_ok=True)
    os.makedirs(ENCODINGS_FOLDER, exist_ok=True)

    cap = cv2.VideoCapture(WEBCAM_INDEX)    # No CAP_DSHOW — cross-platform
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open webcam (index {WEBCAM_INDEX}). "
                           "Check WEBCAM_INDEX in .env")

    collected_encodings = []
    print(f"\n{'='*50}")
    print(f"  Enrolling: {name}")
    print(f"  You will capture {len(_ANGLES)} angles.")
    print(f"  Press SPACE to capture | R to retry | Q to quit")
    print(f"{'='*50}\n")

    for angle_tag, instruction in _ANGLES:
        captured = False
        while not captured:
            ret, frame = cap.read()
            if not ret:
                print("  [ERROR] Cannot read from webcam.")
                break

            # Overlay instruction on the live preview
            display = frame.copy()
            cv2.putText(display, f"Angle: {angle_tag}", (10, 35),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 100), 2)
            cv2.putText(display, instruction, (10, 70),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
            cv2.putText(display, "SPACE=Capture  R=Retry  Q=Quit", (10, frame.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

            cv2.imshow(f"Enrolling: {name}", display)
            key = cv2.waitKey(1) & 0xFF

            if key == ord(' '):     # SPACE → capture
                img_path = os.path.join(PHOTO_FOLDER, f"{name}_{angle_tag.lower()}.jpg")
                cv2.imwrite(img_path, frame)

                # Verify a face exists in the captured frame
                rgb = frame[:, :, ::-1]
                locations = face_recognition.face_locations(rgb)
                if not locations:
                    print(f"  [!] No face detected for {angle_tag}. Press R to retry.")
                    continue

                enc = face_recognition.face_encodings(rgb, locations)[0]
                collected_encodings.append(enc)
                print(f"  ✓ {angle_tag} captured & encoded.")
                captured = True

            elif key == ord('r'):   # R → retry current angle
                print(f"  Retrying {angle_tag} ...")

            elif key == ord('q'):   # Q → quit early
                print("  Enrollment aborted by user.")
                cap.release()
                cv2.destroyAllWindows()
                return

    cap.release()
    cv2.destroyAllWindows()

    if not collected_encodings:
        print(f"  [ERROR] No encodings collected for '{name}'. Enrollment failed.")
        return

    # Save all collected encodings to one .pkl (with gender)
    pkl_path = _save_encoding(name, collected_encodings, gender=gender)
    print(f"\n  ✓ Saved {len(collected_encodings)} encoding(s) → {pkl_path}")

    # Register in Google Sheet + send PIN email
    email = input(f"  Enter email address for {name}: ").strip()
    spreadsheet.enroll_person_to_sheet(name, email, gender=gender)
    print(f"  ✓ {name} fully enrolled!\n")


def batch_enroll_from_folder(folder_path: str = None) -> None:
    """
    Enroll multiple students from a folder of photos.
    Each image filename (without extension) becomes the student's name.

    Example:
        known face photos/
            john_doe.jpg        → enrolled as 'john_doe'
            jane_smith.png      → enrolled as 'jane_smith'

    This is a fallback for situations where webcam enrollment isn't practical.
    For production, use enroll_student_3angles() for better accuracy.

    Args:
        folder_path: Folder containing student photos. Defaults to PHOTO_FOLDER.
    """
    folder_path = folder_path or PHOTO_FOLDER
    if not os.path.isdir(folder_path):
        raise FileNotFoundError(f"Photo folder not found: {folder_path}")

    images = [f for f in os.listdir(folder_path)
              if f.lower().endswith(('.jpg', '.jpeg', '.png'))]

    if not images:
        print(f"  [WARN] No images found in {folder_path}")
        return

    print(f"Batch enrolling {len(images)} image(s) from: {folder_path}\n")
    for filename in sorted(images):
        name = os.path.splitext(filename)[0]           # strip extension
        img_path = os.path.join(folder_path, filename)
        print(f"  Processing: {filename} → name='{name}'")
        encoding_of_enrolled_person(name, img_path)

    print(f"\n✓ Batch enrolment complete.")