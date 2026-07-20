# -*- coding: utf-8 -*-
"""
emailing.py — Email notification module for AI Attendance System.

Sends attendance status emails to students via Gmail SMTP.
Credentials are loaded from .env — never hardcoded in source.

Functions:
    send_email(receiver_mail, attendance)  → attendance status notification
    email_pin(email, pin)                  → send PIN to new enrollee
"""

import smtplib
import ssl
import datetime
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# ── Credentials from environment (NEVER hardcode) ─────────────────────────────
SENDER   = os.getenv("GMAIL_SENDER")
PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

_SMTP_SERVER = "smtp.gmail.com"
_SMTP_PORT   = 465


def _send(receiver_mail: str, subject: str, body: str) -> None:
    """Internal helper — opens SMTP connection and sends one email.
    Fails silently with a warning so the rest of the pipeline keeps running.
    """
    if not SENDER or not PASSWORD:
        print("  [EMAIL SKIP] GMAIL_SENDER / GMAIL_APP_PASSWORD not configured in .env")
        return
    try:
        message = f"Subject: {subject}\n\n{body}"
        ctx = ssl.create_default_context()
        print(f"  → Sending email to {receiver_mail} ...")
        with smtplib.SMTP_SSL(_SMTP_SERVER, _SMTP_PORT, context=ctx) as server:
            server.login(SENDER, PASSWORD)
            server.sendmail(SENDER, receiver_mail, message)
        print(f"  ✓ Email sent to {receiver_mail}")
    except Exception as e:
        print(f"  [EMAIL WARN] Could not send email to {receiver_mail}: {e}")
        print("  → To fix: use a Gmail App Password (myaccount.google.com → Security → App passwords)")


def send_email(receiver_mail: str, attendance: str) -> None:
    """
    Send an attendance status notification to a student.

    Args:
        receiver_mail : Student's email address.
        attendance    : One of 'present', 'absent', or 'late'.
    """
    today   = datetime.date.today().strftime('%B %d, %Y')
    subject = f"Attendance Update — {today}"
    body    = (
        f"Hello,\n\n"
        f"Your attendance for {today} has been marked: {attendance.upper()}.\n\n"
        f"If you believe this is incorrect, please contact your faculty.\n\n"
        f"— AI Attendance System"
    )
    _send(receiver_mail, subject, body)


def email_pin(email: str, pin: int) -> None:
    """
    Send a one-time PIN to a newly enrolled student for the Android app.

    Args:
        email : Student's email address.
        pin   : 4-digit integer PIN.
    """
    today   = datetime.date.today().strftime('%B %d, %Y')
    subject = "Your Attendance App PIN"
    body    = (
        f"Hello,\n\n"
        f"You have been enrolled in the AI Attendance System on {today}.\n\n"
        f"Your PIN is: {pin}\n\n"
        f"Keep this PIN confidential.\n\n"
        f"— AI Attendance System"
    )
    _send(email, subject, body)