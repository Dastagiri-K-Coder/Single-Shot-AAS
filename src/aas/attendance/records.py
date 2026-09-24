# -*- coding: utf-8 -*-
"""
records.py — Attendance record domain objects for Single Shot AAS v2.5.

Implements the attendance_records table entity defined in §14.2.
Each record represents a single student's attendance decision within
one attendance session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Status / Source Constants ─────────────────────────────────────────────────

class RecordStatus:
    PRESENT = "PRESENT"
    ABSENT  = "ABSENT"


class RecordSource:
    AUTO_RECOGNITION = "AUTO_RECOGNITION"
    MANUAL_L1        = "MANUAL_L1"
    INDIVIDUAL_L2    = "INDIVIDUAL_L2"
    BULK_L3          = "BULK_L3"
    SYSTEM           = "SYSTEM"


# ── Domain Object ─────────────────────────────────────────────────────────────

@dataclass
class AttendanceRecord:
    """Single student attendance decision within a session (§14.2)."""
    session_id:       str
    student_name:     str
    status:           str         # PRESENT | ABSENT
    source:           str         # AUTO_RECOGNITION | MANUAL_L1 | INDIVIDUAL_L2 | BULK_L3 | SYSTEM

    id:               Optional[int]   = None
    student_email:    str             = ""
    confidence:       float           = 0.0
    detection_status: str             = "valid"   # valid | low_resolution | low_ipd
    face_width:       int             = 0
    face_height:      int             = 0
    ipd:              int             = 0
    modified_by:      Optional[str]   = None
    created_at:       Optional[str]   = None
    updated_at:       Optional[str]   = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = _utcnow()
        if self.updated_at is None:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "student_name": self.student_name,
            "student_email": self.student_email,
            "status": self.status,
            "source": self.source,
            "confidence": self.confidence,
            "detection_status": self.detection_status,
            "face_width": self.face_width,
            "face_height": self.face_height,
            "ipd": self.ipd,
            "modified_by": self.modified_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def is_auto_recognized(self) -> bool:
        return self.source == RecordSource.AUTO_RECOGNITION

    def is_manually_set(self) -> bool:
        return self.source in (
            RecordSource.MANUAL_L1,
            RecordSource.INDIVIDUAL_L2,
            RecordSource.BULK_L3,
        )


# ── Builder Helpers ───────────────────────────────────────────────────────────

def record_from_recognition_result(
    *,
    session_id: str,
    student_name: str,
    student_email: str = "",
    confidence: float = 0.0,
    detection_status: str = "valid",
    face_width: int = 0,
    face_height: int = 0,
    ipd: int = 0,
) -> AttendanceRecord:
    """Build a PRESENT record from a CV recognition result."""
    return AttendanceRecord(
        session_id=session_id,
        student_name=student_name,
        student_email=student_email,
        status=RecordStatus.PRESENT,
        source=RecordSource.AUTO_RECOGNITION,
        confidence=confidence,
        detection_status=detection_status,
        face_width=face_width,
        face_height=face_height,
        ipd=ipd,
    )


def record_from_manual_toggle(
    *,
    session_id: str,
    student_name: str,
    student_email: str = "",
    new_status: str,
    modified_by: str,
) -> AttendanceRecord:
    """Build a record from L1 manual toggle."""
    return AttendanceRecord(
        session_id=session_id,
        student_name=student_name,
        student_email=student_email,
        status=new_status,
        source=RecordSource.MANUAL_L1,
        modified_by=modified_by,
    )


def record_from_individual_retake(
    *,
    session_id: str,
    student_name: str,
    student_email: str = "",
    confidence: float = 0.0,
    detection_status: str = "valid",
    face_width: int = 0,
    face_height: int = 0,
    ipd: int = 0,
    modified_by: str = "",
) -> AttendanceRecord:
    """Build a PRESENT record from L2 individual close-up retake."""
    return AttendanceRecord(
        session_id=session_id,
        student_name=student_name,
        student_email=student_email,
        status=RecordStatus.PRESENT,
        source=RecordSource.INDIVIDUAL_L2,
        confidence=confidence,
        detection_status=detection_status,
        face_width=face_width,
        face_height=face_height,
        ipd=ipd,
        modified_by=modified_by,
    )


def records_from_bulk_add(
    *,
    session_id: str,
    students: list[dict[str, str]],
    modified_by: str,
) -> list[AttendanceRecord]:
    """Build PRESENT records from L3 bulk manual addition.

    Args:
        students: List of {"name": ..., "email": ...} dicts.
        modified_by: User who performed the bulk add.
    """
    return [
        AttendanceRecord(
            session_id=session_id,
            student_name=s["name"],
            student_email=s.get("email", ""),
            status=RecordStatus.PRESENT,
            source=RecordSource.BULK_L3,
            modified_by=modified_by,
        )
        for s in students
    ]
