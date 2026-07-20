# -*- coding: utf-8 -*-
"""
tts.py — Text-to-speech attendance announcements for Single Shot AAS.

Speaks the fixed-format attendance summary after every capture cycle:
    "Successfully Taken the Attendance, Number of Boys is X,
     Number of Girls is Y, Number of Total Strength of Class is Z"

Only X, Y, Z are variable. The rest of the phrase is FIXED per Requirement.txt.

Uses pyttsx3 (fully offline, cross-platform: Linux/Windows/macOS/Raspberry Pi).
Falls back to espeak subprocess on Linux if pyttsx3 is unavailable.

Functions:
    announce_attendance(boys, girls, total)  → Speak the attendance summary
    test_tts()                               → Speak test phrase to verify audio
    set_speech_rate(rate)                    → Adjust words-per-minute
    is_tts_available()                       → True if TTS engine is usable
"""

import threading
import subprocess
import sys


# ── Engine Initialisation ─────────────────────────────────────────────────────

_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    """Lazily initialise pyttsx3 engine (one-time setup)."""
    global _engine
    if _engine is not None:
        return _engine
    try:
        import pyttsx3
        _engine = pyttsx3.init()
        # Default settings for classroom clarity
        _engine.setProperty("rate", 145)    # words per minute
        _engine.setProperty("volume", 1.0)  # max volume
        # On Linux/Pi prefer a clearer voice if available
        voices = _engine.getProperty("voices")
        if voices:
            _engine.setProperty("voice", voices[0].id)
        return _engine
    except Exception as e:
        print(f"  [TTS] pyttsx3 not available: {e}. Will try espeak fallback.")
        return None


def is_tts_available() -> bool:
    """Return True if any TTS method is available."""
    if _get_engine() is not None:
        return True
    # Check espeak as fallback
    try:
        subprocess.run(["espeak", "--version"], capture_output=True, check=True)
        return True
    except Exception:
        return False


def set_speech_rate(rate: int = 145) -> None:
    """
    Adjust TTS speech rate (words per minute).
    Recommended range: 120 (slow/clear) – 180 (fast).
    """
    engine = _get_engine()
    if engine:
        engine.setProperty("rate", rate)


# ── Core Announcement ─────────────────────────────────────────────────────────

def _speak(text: str) -> None:
    """Internal: speak text using pyttsx3, or espeak fallback."""
    engine = _get_engine()
    if engine:
        try:
            with _engine_lock:
                engine.say(text)
                engine.runAndWait()
            return
        except Exception as e:
            print(f"  [TTS] pyttsx3 error: {e}. Trying espeak...")

    # espeak fallback (Linux / Raspberry Pi)
    try:
        subprocess.run(
            ["espeak", "-s", "145", "-a", "200", text],
            check=True,
            timeout=30,
        )
    except FileNotFoundError:
        print("  [TTS] Neither pyttsx3 nor espeak available. Install with:")
        print("        pip install pyttsx3")
        print("        sudo apt install espeak  # Raspberry Pi / Ubuntu")
    except Exception as e:
        print(f"  [TTS] espeak error: {e}")


def announce_attendance(boys: int, girls: int, total: int) -> None:
    """
    Speak the fixed attendance summary announcement.

    Fixed phrase (per Requirement.txt):
        "Successfully Taken the Attendance, Number of Boys is X,
         Number of Girls is Y, Number of Total Strength of Class is Z"

    Only X (boys), Y (girls), Z (total) are variable.

    Runs in a background daemon thread — non-blocking.

    Args:
        boys  : Count of male students marked present.
        girls : Count of female students marked present.
        total : Total students in the class (enrolled count, not just present).
    """
    message = (
        f"Successfully Taken the Attendance, "
        f"Number of Boys is {boys}, "
        f"Number of Girls is {girls}, "
        f"Number of Total Strength of Class is {total}"
    )
    print(f"  🔊 TTS: {message}")

    t = threading.Thread(target=_speak, args=(message,), daemon=True)
    t.start()


def test_tts() -> None:
    """
    Speak a short test phrase to verify audio output is working.
    Blocks until the phrase is complete.
    """
    test_msg = "Single Shot AAS is ready. Text to speech is working correctly."
    print(f"  🔊 TTS test: {test_msg}")
    _speak(test_msg)


# ── CLI test ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing TTS engine ...")
    if is_tts_available():
        test_tts()
        import time; time.sleep(0.5)
        announce_attendance(boys=18, girls=12, total=60)
    else:
        print("No TTS engine available. Install pyttsx3 or espeak.")
        sys.exit(1)
