# -*- coding: utf-8 -*-
"""
capture.py — Classroom camera capture module for Single Shot AAS.

Supports:
    Mode A: Per-camera RTSP URL from cameras.json (multi-camera setup)
    Mode B: Fixed IP Camera (IP_CAMERA_URL env var, single-camera fallback)
    Mode C: Local webcam (WEBCAM_INDEX env var, for testing)

Functions:
    get_camera_source(camera_id)  → returns RTSP URL or webcam index
    capture_single_shot(camera_id) → grab one frame, save, return path
    capture_with_preview()        → show live preview, capture on SPACE bar
"""

import cv2
import os
import datetime
import threading

from aas.core.config import (
    IP_CAMERA_URL,
    USE_WEBCAM,
    WEBCAM_INDEX,
    CAMERA_WARMUP_FRAMES,
    CAPTURED_FOLDER,
)

# Module-level lock — prevents two concurrent Flask requests from opening the
# camera at the same time, which would cause a crash or corrupted frame.
_camera_lock = threading.Lock()


def get_camera_source(camera_id: str = None):
    """
    Return the appropriate camera source.

    Priority:
        1. cameras.json entry for camera_id (multi-camera setup)
        2. IP_CAMERA_URL env var (single-camera legacy)
        3. WEBCAM_INDEX (local webcam fallback)

    Returns:
        int  → webcam index
        str  → RTSP/LAN URL
    """
    if camera_id:
        try:
            from aas.capture.camera_registry import get_camera
            cam = get_camera(camera_id)
            if cam and cam.get("rtsp_url"):
                return cam["rtsp_url"]
        except Exception as e:
            print(f"  [WARN] camera_registry lookup failed for '{camera_id}': {e}")

    if USE_WEBCAM:
        return WEBCAM_INDEX
    return IP_CAMERA_URL


def _make_save_path() -> str:
    """Generate a timestamped filename inside the captured/ folder."""
    os.makedirs(CAPTURED_FOLDER, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(CAPTURED_FOLDER, f"classroom_{ts}.jpg")


def capture_single_shot(save_path: str = None, camera_id: str = None) -> str:
    """
    Capture one frame from the configured camera (no preview window).

    Args:
        save_path  : Optional custom save path. Auto-generated if None.
        camera_id  : Camera registry ID (e.g. 'cam_abc123'). If provided,
                     overrides global IP_CAMERA_URL / WEBCAM_INDEX settings.

    Returns:
        Absolute path to the saved JPEG image.
    """
    source    = get_camera_source(camera_id=camera_id)
    save_path = save_path or _make_save_path()

    with _camera_lock:
        print(f"  Camera source: {'Webcam #' + str(source) if isinstance(source, int) else source}")
        cap = cv2.VideoCapture(source)

        if not cap.isOpened():
            raise RuntimeError(
                f"Cannot open camera: {source}\n"
                "For IP cameras: check RTSP URL in cameras.json or IP_CAMERA_URL in .env.\n"
                "For webcam: check WEBCAM_INDEX (default 0)."
            )

        # Warm up: discard the first N frames (exposure stabilisation)
        print(f"  Warming up camera ({CAMERA_WARMUP_FRAMES} frames) ...")
        for _ in range(CAMERA_WARMUP_FRAMES):
            cap.read()

        ret, frame = cap.read()
        cap.release()

    if not ret or frame is None:
        raise RuntimeError("Failed to capture frame from camera.")

    cv2.imwrite(save_path, frame)
    print(f"  ✓ Snapshot saved: {save_path}")
    print(f"    Size: {frame.shape[1]}×{frame.shape[0]} px")
    return save_path


def capture_with_preview(save_path: str = None) -> str | None:
    """
    Show a live camera preview window. Faculty presses SPACE to capture.

    Used for:
        - Manual trigger via keyboard (webcam / local setup)
        - Situations where faculty wants to verify framing before capture

    Controls:
        SPACE → capture and close
        Q     → quit without capturing

    Args:
        save_path: Optional custom save path. Auto-generated if None.

    Returns:
        Path to saved image, or None if cancelled or running headless.
    """
    # Headless guard: skip GUI on Raspberry Pi or servers without a display
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        print("  [INFO] No display detected (headless mode). "
              "Using capture_single_shot() instead of preview.")
        return capture_single_shot(save_path)

    source    = get_camera_source()
    save_path = save_path or _make_save_path()
    mode_str  = "Webcam" if isinstance(source, int) else "IP Camera"

    _camera_lock.acquire()
    try:
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera: {source}")

        print(f"\nLive preview ({mode_str}) — Press SPACE to capture | Q to quit")

        captured_path = None
        while True:
            ret, frame = cap.read()
            if not ret:
                print("  [ERROR] Lost camera feed.")
                break

            display = frame.copy()
            cv2.putText(display, f"{mode_str} — Press SPACE to capture",
                        (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 100), 2)
            cv2.putText(display, "Q = Cancel",
                        (10, display.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (100, 100, 255), 1)
            cv2.imshow("Classroom Capture", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord(' '):
                cv2.imwrite(save_path, frame)
                print(f"  ✓ Captured: {save_path}")
                captured_path = save_path
                break
            elif key == ord('q'):
                print("  Capture cancelled.")
                break

        cap.release()
        cv2.destroyAllWindows()
        return captured_path
    finally:
        _camera_lock.release()
