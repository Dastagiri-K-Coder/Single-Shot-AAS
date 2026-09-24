# -*- coding: utf-8 -*-
"""
emailing.py — Email notification module for AI Attendance System.

Sends attendance status emails to students via Gmail SMTP.
Credentials are loaded from .env — never hardcoded in source.

Functions:
    send_email(receiver_mail, attendance)          → attendance status notification
    email_pin(email, pin)                          → send PIN to new enrollee
    send_faculty_summary(faculty_email, ...)       → post-attendance summary to faculty (v2.0)
"""

import smtplib
import ssl
import datetime
import os
from dotenv import load_dotenv
from aas.core.config import ROOT_DIR

load_dotenv(os.path.join(ROOT_DIR, '.env'))

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


def send_faculty_summary(
    faculty_email: str,
    section: str,
    subject_name: str,
    period: int,
    present_count: int,
    absent_names: list,
) -> None:
    """Send a post-attendance summary email to the faculty member.

    v2.0 addition — called in a background thread after attendance confirmation
    so it does not block the faculty's UI response.

    Args:
        faculty_email  : Faculty's email address (from camera config or user record).
        section        : Section name (e.g. 'CSE-A').
        subject_name   : Subject taken (e.g. 'DBMS').
        period         : Period number (e.g. 3).
        present_count  : Number of students marked present.
        absent_names   : List of absent student names.
    """
    if not faculty_email:
        return  # silently skip if no email configured

    today       = datetime.date.today().strftime('%d %b %Y')
    absent_list = "\n".join(f"  \u2022 {n}" for n in absent_names) if absent_names else "  (None)"
    em_subject  = f"[AAS] {section} {subject_name} P{period} \u2014 Attendance Summary"
    body = (
        f"Hello,\n\n"
        f"Attendance has been submitted for:\n"
        f"  Section : {section}\n"
        f"  Subject : {subject_name}  |  Period {period}\n"
        f"  Date    : {today}\n\n"
        f"  \u2705 Present : {present_count}\n"
        f"  \u274c Absent  : {len(absent_names)}\n\n"
        f"Absent students:\n{absent_list}\n\n"
        f"\u2014 Single Shot AAS"
    )
    _send(faculty_email, em_subject, body)