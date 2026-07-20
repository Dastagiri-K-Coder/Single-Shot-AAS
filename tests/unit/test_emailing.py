# =============================================================================
#  tests/unit/test_emailing.py — Tests for emailing.py
# =============================================================================

import os
import smtplib
from unittest.mock import MagicMock, patch

import pytest

from aas.notifications import emailing


class TestSendEmail:
    """Tests for emailing.send_email()"""

    def test_sends_email_when_credentials_set(self, monkeypatch, mock_smtp):
        monkeypatch.setattr(emailing, "SENDER", "from@example.com")
        monkeypatch.setattr(emailing, "PASSWORD", "app-password-here")

        emailing.send_email("student@example.com", "present")

        mock_smtp.__enter__.return_value.sendmail.assert_called_once()

    def test_skips_send_when_no_credentials(self, monkeypatch, capsys):
        """Should print a skip notice and not attempt SMTP connection."""
        monkeypatch.setattr(emailing, "SENDER", None)
        monkeypatch.setattr(emailing, "PASSWORD", None)

        emailing.send_email("student@example.com", "absent")

        captured = capsys.readouterr()
        assert "skip" in captured.out.lower() or "not configured" in captured.out.lower()

    def test_email_body_contains_status(self, monkeypatch, mock_smtp):
        monkeypatch.setattr(emailing, "SENDER", "from@example.com")
        monkeypatch.setattr(emailing, "PASSWORD", "pwd")

        emailing.send_email("student@example.com", "late")

        sent_msg = mock_smtp.__enter__.return_value.sendmail.call_args[0][2]
        assert "LATE" in sent_msg

    def test_smtp_exception_does_not_crash(self, monkeypatch, capsys):
        """SMTP errors should be caught and printed, not propagated."""
        monkeypatch.setattr(emailing, "SENDER", "from@example.com")
        monkeypatch.setattr(emailing, "PASSWORD", "pwd")

        with patch("smtplib.SMTP_SSL", side_effect=smtplib.SMTPException("connection refused")):
            # Should NOT raise
            emailing.send_email("student@example.com", "present")

        captured = capsys.readouterr()
        assert "warn" in captured.out.lower() or "could not" in captured.out.lower()


class TestEmailPin:
    """Tests for emailing.email_pin()"""

    def test_pin_in_email_body(self, monkeypatch, mock_smtp):
        monkeypatch.setattr(emailing, "SENDER", "from@example.com")
        monkeypatch.setattr(emailing, "PASSWORD", "pwd")

        emailing.email_pin("newstudent@example.com", 4827)

        sent_msg = mock_smtp.__enter__.return_value.sendmail.call_args[0][2]
        assert "4827" in sent_msg

    def test_pin_subject_contains_pin_keyword(self, monkeypatch, mock_smtp):
        monkeypatch.setattr(emailing, "SENDER", "from@example.com")
        monkeypatch.setattr(emailing, "PASSWORD", "pwd")

        emailing.email_pin("newstudent@example.com", 1234)

        sent_msg = mock_smtp.__enter__.return_value.sendmail.call_args[0][2]
        assert "PIN" in sent_msg
