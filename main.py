# -*- coding: utf-8 -*-
"""
main.py — Entry point for the AI Attendance System.

Usage:
    python main.py                      → Capture from camera + process
    python main.py path/to/image.jpg    → Process a specific image file
    python main.py --preview            → Show live preview before capture
    python main.py --voice              → Start offline voice trigger listener
    python main.py --web                → Start Flask web dashboard (faculty UI)
    python main.py --enroll "John Doe"  → Enroll a new student (3-angle webcam)
    python main.py --test-mic           → Test microphone for voice mode

Examples:
    # Take one attendance shot right now (from webcam or IP cam):
    python main.py

    # Process a photo uploaded by faculty from their phone:
    python main.py /path/to/uploaded_classroom.jpg

    # Start the web dashboard (faculty opens http://localhost:5000):
    python main.py --web

    # Run in voice mode (say "take attendance" to trigger):
    python main.py --voice

    # Enroll a new student:
    python main.py --enroll "Priya Sharma"
"""

import sys
import os

from aas.recognition import engine as recognition
from aas.attendance import spreadsheet
from aas.capture import capture


def _load_and_mark():
    """Common setup: load encodings + mark everyone absent for today."""
    recognition.load_facial_encodings_and_names_from_memory()
    spreadsheet.mark_all_absent()


def run_once(image_path: str = None, with_preview: bool = False) -> dict:
    """
    Run one full attendance cycle:
        1. Load encodings
        2. Mark all absent
        3. Capture classroom photo (or use provided path)
        4. Recognize all faces
        5. Mark present / send emails

    Args:
        image_path   : Path to a pre-existing image. If None, captures from camera.
        with_preview : If True, show live preview before capture (keyboard mode).

    Returns:
        Recognition result dict with 'present', 'unknown_count', 'total_faces'.
    """
    _load_and_mark()

    if image_path:
        print(f"\nUsing provided image: {image_path}")
        path = image_path
    elif with_preview:
        print("\nStarting camera preview ...")
        path = capture.capture_with_preview()
        if not path:
            print("Capture cancelled. Exiting.")
            return {}
    else:
        print("\nCapturing classroom photo ...")
        path = capture.capture_single_shot()

    print("\nRunning face recognition ...")
    result = recognition.run_recognition(path)

    # Also save an annotated copy for faculty review
    if result.get("total_faces", 0) > 0:
        recognition.annotate_image(path, result)

    print(f"\n{'='*50}")
    print(f"  ATTENDANCE COMPLETE")
    print(f"{'='*50}")
    print(f"  Present     : {len(result.get('present', []))}")
    print(f"  Unknown     : {result.get('unknown_count', 0)}")
    print(f"  Total faces : {result.get('total_faces', 0)}")
    if result.get("present"):
        print(f"  Names       : {', '.join(result['present'])}")
    print(f"{'='*50}\n")

    return result


def start_voice_mode() -> None:
    """Start the offline voice trigger. Blocks indefinitely until Ctrl+C."""
    from aas.voice.voice_trigger import listen_for_trigger

    print("Initialising voice trigger mode ...")
    _load_and_mark()

    def on_voice_trigger():
        print("\n[Voice] Attendance triggered by voice command.")
        try:
            path   = capture.capture_single_shot()
            result = recognition.run_recognition(path)
            recognition.annotate_image(path, result)
            print(f"[Voice] Done. Present: {result.get('present', [])}")
        except Exception as e:
            print(f"[Voice] Error during attendance: {e}")

    listen_for_trigger(on_voice_trigger)


def start_web_mode() -> None:
    """Start the Flask web dashboard."""
    from aas.core.config import WEB_HOST, WEB_PORT
    # Load encodings once before starting the server
    recognition.load_facial_encodings_and_names_from_memory()
    print(f"\nStarting Web Dashboard at http://{WEB_HOST}:{WEB_PORT}")
    print("Open this URL in your browser or share with faculty on the same network.\n")

    from aas.web.app import create_app
    app = create_app()
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)


def enroll_student(name: str) -> None:
    """Run the interactive 3-angle enrollment for one student."""
    from aas.enrollment import enroll
    enroll.enroll_student_3angles(name)


# ── CLI Argument Parsing ───────────────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        # Default: capture from configured camera + process
        run_once()

    elif args[0] == "--voice":
        start_voice_mode()

    elif args[0] == "--web":
        start_web_mode()

    elif args[0] == "--preview":
        run_once(with_preview=True)

    elif args[0] == "--enroll":
        if len(args) < 2:
            print("Usage: python main.py --enroll \"Student Full Name\"")
            sys.exit(1)
        enroll_student(args[1])

    elif args[0] == "--test-mic":
        from aas.voice.voice_trigger import test_microphone
        test_microphone(duration_seconds=8)

    elif os.path.isfile(args[0]):
        # A file path was passed — process that image directly
        run_once(image_path=args[0])

    else:
        print(f"Unknown argument: {args[0]}")
        print(__doc__)
        sys.exit(1)