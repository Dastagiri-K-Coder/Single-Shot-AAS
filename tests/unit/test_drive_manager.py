"""tests/unit/test_drive_manager.py — Unit tests for drive_manager.py"""
import pytest
from unittest.mock import MagicMock, patch
from aas.integrations.google import drive_manager


def test_format_sheet_name_basic():
    result = drive_manager.format_sheet_name(1, "CSE", 2024, 2027, "A")
    assert result == "Single Shot AAS -1 CSE Y(2024-2027) S(A)"


def test_format_sheet_name_serial_increment():
    assert drive_manager.format_sheet_name(2, "MECH", 2023, 2026, "B") == "Single Shot AAS -2 MECH Y(2023-2026) S(B)"


def test_format_sheet_name_numeric_section():
    assert drive_manager.format_sheet_name(3, "ECE", 2025, 2028, "1") == "Single Shot AAS -3 ECE Y(2025-2028) S(1)"


@patch("aas.integrations.google.drive_manager._build_drive")
def test_ensure_root_folder_finds_existing(mock_build_drive):
    """ensure_root_folder returns existing folder ID without creating one."""
    mock_service = MagicMock()
    mock_build_drive.return_value = mock_service
    mock_service.files().list().execute.return_value = {
        "files": [{"id": "existing_folder_id", "name": "Single Shot AAS"}]
    }
    result = drive_manager.ensure_root_folder(MagicMock())
    assert result == "existing_folder_id"


@patch("aas.integrations.google.drive_manager._build_drive")
def test_ensure_root_folder_creates_if_missing(mock_build_drive):
    """ensure_root_folder creates folder when not found."""
    mock_service = MagicMock()
    mock_build_drive.return_value = mock_service
    # First call (list): no existing folder
    mock_service.files().list().execute.return_value = {"files": []}
    # Second call (create): returns new ID
    mock_service.files().create().execute.return_value = {"id": "new_folder_id"}
    result = drive_manager.ensure_root_folder(MagicMock())
    assert result == "new_folder_id"


@patch("aas.integrations.google.drive_manager._build_drive")
def test_check_drive_setup_exists_true(mock_build_drive):
    mock_service = MagicMock()
    mock_build_drive.return_value = mock_service
    mock_service.files().list().execute.return_value = {
        "files": [{"id": "root_id", "name": "Single Shot AAS"}]
    }
    assert drive_manager.check_drive_setup_exists(MagicMock()) is True


@patch("aas.integrations.google.drive_manager._build_drive")
def test_check_drive_setup_exists_false(mock_build_drive):
    mock_service = MagicMock()
    mock_build_drive.return_value = mock_service
    mock_service.files().list().execute.return_value = {"files": []}
    assert drive_manager.check_drive_setup_exists(MagicMock()) is False
