# =============================================================================
#  tests/unit/test_spreadsheet.py — Tests for spreadsheet.py
# =============================================================================

import os
import datetime
from unittest.mock import MagicMock, patch, call, ANY
import pytest

from aas.attendance import spreadsheet


class TestTodayString:
    """Tests for spreadsheet._today_string()"""

    def test_returns_string(self):
        result = spreadsheet._today_string()
        assert isinstance(result, str)

    def test_format_no_leading_zeros(self):
        """Must not have leading zeros — Sheet format is M/D/YYYY not MM/DD/YYYY."""
        with patch("aas.attendance.spreadsheet.datetime") as mock_dt:
            mock_dt.date.today.return_value = MagicMock(month=7, day=4, year=2026)
            result = spreadsheet._today_string()
        assert result == "7/4/2026"

    def test_returns_slash_separated(self):
        result = spreadsheet._today_string()
        parts = result.split("/")
        assert len(parts) == 3  # M / D / YYYY


class TestMarkAllAbsent:
    """Tests for spreadsheet.mark_all_absent()"""

    def test_calls_batch_update(self, mock_gspread):
        """Should call batch_update once with all student rows."""
        mock_gspread.col_values.return_value = ["Name", "Alice", "Bob", "Charlie"]
        mock_gspread.row_values.return_value = ["Name", "Email", "Gender", "PIN", "7/14/2026"]

        # Inject the today header
        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.mark_all_absent()

        mock_gspread.batch_update.assert_called_once()
        call_args = mock_gspread.batch_update.call_args[0][0]
        assert len(call_args) == 3  # 3 students (Alice, Bob, Charlie)
        for item in call_args:
            assert item["values"] == [["absent"]]

    def test_no_update_when_no_students(self, mock_gspread):
        """Empty student list should not call batch_update."""
        mock_gspread.col_values.return_value = ["Name"]  # header only
        mock_gspread.row_values.return_value = ["Name", "Email", "Gender", "PIN", "7/14/2026"]

        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.mark_all_absent()

        mock_gspread.batch_update.assert_not_called()


class TestWriteToSheet:
    """Tests for spreadsheet.write_to_sheet()"""

    def test_marks_present_when_on_time(self, mock_gspread, mock_smtp):
        """Student arriving before MAX_IN_TIME should be marked 'present'."""
        mock_gspread.cell.side_effect = lambda r, c: MagicMock(value="absent" if c != 1 else "Alice")
        mock_gspread.find.return_value = MagicMock(row=2)
        mock_gspread.row_values.return_value = ["Name", "Email", "Gender", "PIN", "7/14/2026"]

        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"), \
             patch("aas.attendance.spreadsheet.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.strftime.return_value = "10:00:00"
            spreadsheet.write_to_sheet("Alice")

        mock_gspread.update_cell.assert_called_once_with(2, 5, "present")

    def test_marks_late_when_after_cutoff(self, mock_gspread, mock_smtp):
        """Student arriving after MAX_IN_TIME should be marked 'late'."""
        mock_gspread.cell.side_effect = lambda r, c: MagicMock(value="absent" if c != 1 else "Alice")
        mock_gspread.find.return_value = MagicMock(row=2)
        mock_gspread.row_values.return_value = ["Name", "Email", "Gender", "PIN", "7/14/2026"]

        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"), \
             patch("aas.attendance.spreadsheet.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.strftime.return_value = "18:00:00"
            spreadsheet.write_to_sheet("Alice")

        mock_gspread.update_cell.assert_called_once_with(2, 5, "late")

    def test_skip_if_already_present(self, mock_gspread):
        """Should not update cell if student is already marked 'present'."""
        mock_gspread.cell.side_effect = lambda r, c: MagicMock(value="present" if c != 1 else "Alice")
        mock_gspread.find.return_value = MagicMock(row=2)
        mock_gspread.row_values.return_value = ["Name", "Email", "Gender", "PIN", "7/14/2026"]

        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.write_to_sheet("Alice")

        mock_gspread.update_cell.assert_not_called()

    def test_warns_if_student_not_in_sheet(self, mock_gspread, capsys):
        """Missing student should print a warning and not crash."""
        mock_gspread.find.return_value = None

        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.write_to_sheet("UnknownPerson")

        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "warn" in captured.out.lower()
        mock_gspread.update_cell.assert_not_called()


class TestEnrollPersonToSheet:
    """Tests for spreadsheet.enroll_person_to_sheet()"""

    def test_adds_new_student_row(self, mock_gspread, mock_smtp):
        """Should add student name, email, and PIN to the next empty row via atomic update."""
        mock_gspread.find.return_value = None
        mock_gspread.col_values.return_value = ["Name", "Alice"]  # 2 rows

        spreadsheet.enroll_person_to_sheet("Bob", "bob@example.com")

        # Should write atomically at row 3 (next after 2 existing rows)
        mock_gspread.update.assert_called_once()
        args, kwargs = mock_gspread.update.call_args
        values = kwargs.get("values") or args[0]
        range_name = kwargs.get("range_name") or args[1]
        assert range_name == "A3:D3"
        assert values[0][0] == "Bob"
        assert values[0][1] == "bob@example.com"
        assert values[0][2] == "M"

    def test_skips_if_already_enrolled(self, mock_gspread, capsys):
        """If student name already exists in sheet, should skip silently."""
        mock_cell = MagicMock(row=2)
        mock_gspread.find.return_value = mock_cell
        mock_gspread.cell.return_value = MagicMock(value="Alice")

        spreadsheet.enroll_person_to_sheet("Alice", "alice@example.com")

        mock_gspread.update.assert_not_called()


class TestWriteBatchToSheet:
    """Tests for spreadsheet.write_batch_to_sheet()"""

    def test_batch_write_updates_all_students(self, mock_gspread, mock_smtp):
        mock_gspread.row_values.return_value = ["Name", "Email", "Gender", "PIN", "7/14/2026"]
        mock_gspread.col_values.side_effect = lambda col: {
            1: ["Name", "Alice", "Bob"],
            2: ["Email", "alice@example.com", "bob@example.com"],
            5: ["7/14/2026", "absent", "absent"],
        }.get(col, [])

        with patch("aas.attendance.spreadsheet._today_string", return_value="7/14/2026"), \
             patch("aas.attendance.spreadsheet.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.strftime.return_value = "10:00:00"
            res = spreadsheet.write_batch_to_sheet(["Alice", "Bob"])

        assert res == ["Alice", "Bob"]
        mock_gspread.batch_update.assert_called_once()
