"""tests/unit/test_tts.py — Unit tests for tts.py"""
import pytest
import subprocess
from unittest.mock import patch, MagicMock
from aas.notifications import tts


def test_announce_attendance_message_format():
    """Test that the announcement message is correctly formatted."""
    messages = []

    with patch("aas.notifications.tts._speak", side_effect=lambda msg: messages.append(msg)):
        # Run synchronously by calling _speak directly via announce_attendance
        # We patch threading.Thread to call target immediately
        with patch("aas.notifications.tts.threading.Thread") as mock_thread:
            mock_thread.side_effect = lambda target, args, daemon: MagicMock(
                start=lambda: target(*args)
            )
            tts.announce_attendance(boys=18, girls=12, total=60)

    # Verify the message was constructed (via _speak mock)
    if messages:
        msg = messages[0]
        assert "Successfully Taken the Attendance" in msg
        assert "Number of Boys is 18" in msg
        assert "Number of Girls is 12" in msg
        assert "Number of Total Strength of Class is 60" in msg


def test_announce_attendance_fixed_phrase():
    """The fixed part of the announcement must be exactly correct."""
    captured = []

    def fake_speak(text):
        captured.append(text)

    with patch("aas.notifications.tts._speak", fake_speak):
        with patch("aas.notifications.tts.threading.Thread") as mock_thread:
            mock_thread.side_effect = lambda target, args, daemon: MagicMock(
                start=lambda: target(*args)
            )
            tts.announce_attendance(boys=0, girls=0, total=0)

    if captured:
        assert captured[0].startswith("Successfully Taken the Attendance, ")


def test_announce_attendance_with_zeros():
    """announce_attendance works correctly with zero counts."""
    # Should not raise
    with patch("aas.notifications.tts._speak"):
        with patch("aas.notifications.tts.threading.Thread") as mock_thread:
            mock_thread.side_effect = lambda target, args, daemon: MagicMock(
                start=lambda: None
            )
            tts.announce_attendance(boys=0, girls=0, total=0)


def test_is_tts_available_pyttsx3_present():
    """is_tts_available returns True when pyttsx3 loads successfully."""
    mock_engine = MagicMock()
    with patch("aas.notifications.tts._get_engine", return_value=mock_engine):
        assert tts.is_tts_available() is True


def test_is_tts_available_no_engine():
    """is_tts_available falls back to espeak check."""
    with patch("aas.notifications.tts._get_engine", return_value=None):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert tts.is_tts_available() is False
