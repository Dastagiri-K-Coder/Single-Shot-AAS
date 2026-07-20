# =============================================================================
#  tests/unit/test_spreadsheet.py — Tests for spreadsheet.py
# =============================================================================

import os
import sys
import datetime
from unittest.mock import MagicMock, patch, call
import pytest

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "face recognition source code")
sys.path.insert(0, os.path.abspath(SRC_DIR))

import spreadsheet


class TestTodayString:
    """Tests for spreadsheet._today_string()"""

    def test_returns_string(self):
        result = spreadsheet._today_string()
        assert isinstance(result, str)

    def test_format_no_leading_zeros(self):
        """Must not have leading zeros — Sheet format is M/D/YYYY not MM/DD/YYYY."""
        with patch("spreadsheet.datetime") as mock_dt:
            mock_dt.date.today.return_value = datetime.date(2026, 7, 4)
            mock_dt.date.today.return_value.strftime = lambda fmt: datetime.date(2026, 7, 4).strftime(fmt)
            result = spreadsheet._today_string()
        # Result should not start with "07"
        assert not result.startswith("07"), f"Leading zero found: {result}"

    def test_returns_slash_separated(self):
        result = spreadsheet._today_string()
        parts = result.split("/")
        assert len(parts) == 3  # M / D / YYYY


class TestMarkAllAbsent:
    """Tests for spreadsheet.mark_all_absent()"""

    def test_calls_batch_update(self, mock_gspread):
        """Should call batch_update once with all student rows."""
        mock_gspread.col_values.return_value = ["Name", "Alice", "Bob", "Charlie"]
        mock_gspread.row_values.return_value = ["Name", "Email", "PIN", "7/14/2026"]

        # Inject the today header
        with patch("spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.mark_all_absent()

        mock_gspread.batch_update.assert_called_once()
        call_args = mock_gspread.batch_update.call_args[0][0]
        assert len(call_args) == 3  # 3 students (Alice, Bob, Charlie)
        for item in call_args:
            assert item["values"] == [["absent"]]

    def test_no_update_when_no_students(self, mock_gspread):
        """Empty student list should not call batch_update."""
        mock_gspread.col_values.return_value = ["Name"]  # header only
        mock_gspread.row_values.return_value = ["Name", "Email", "PIN", "7/14/2026"]

        with patch("spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.mark_all_absent()

        mock_gspread.batch_update.assert_not_called()


class TestWriteToSheet:
    """Tests for spreadsheet.write_to_sheet()"""

    def test_marks_present_when_on_time(self, mock_gspread, mock_smtp):
        """Student arriving before MAX_IN_TIME should be marked 'present'."""
        mock_gspread.cell.return_value = MagicMock(value="absent")

        with patch("spreadsheet._today_string", return_value="7/14/2026"), \
             patch("spreadsheet.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.strftime.return_value = "10:00:00"
            spreadsheet.write_to_sheet("Alice")

        mock_gspread.update_cell.assert_called_once_with(2, 4, "present")

    def test_marks_late_when_after_cutoff(self, mock_gspread, mock_smtp):
        """Student arriving after MAX_IN_TIME should be marked 'late'."""
        mock_gspread.cell.return_value = MagicMock(value="absent")

        with patch("spreadsheet._today_string", return_value="7/14/2026"), \
             patch("spreadsheet.datetime") as mock_dt:
            mock_dt.datetime.now.return_value.strftime.return_value = "18:00:00"
            spreadsheet.write_to_sheet("Alice")

        mock_gspread.update_cell.assert_called_once_with(2, 4, "late")

    def test_skip_if_already_present(self, mock_gspread):
        """Should not update cell if student is already marked 'present'."""
        mock_gspread.cell.return_value = MagicMock(value="present")

        with patch("spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.write_to_sheet("Alice")

        mock_gspread.update_cell.assert_not_called()

    def test_warns_if_student_not_in_sheet(self, mock_gspread, capsys):
        """Missing student should print a warning and not crash."""
        import gspread
        mock_gspread.find.side_effect = gspread.exceptions.CellNotFound("not found")

        with patch("spreadsheet._today_string", return_value="7/14/2026"):
            spreadsheet.write_to_sheet("UnknownPerson")

        captured = capsys.readouterr()
        assert "not found" in captured.out.lower() or "warn" in captured.out.lower()
        mock_gspread.update_cell.assert_not_called()


class TestEnrollPersonToSheet:
    """Tests for spreadsheet.enroll_person_to_sheet()"""

    def test_adds_new_student_row(self, mock_gspread, mock_smtp):
        """Should add student name, email, and PIN to the next empty row."""
        import gspread
        mock_gspread.find.side_effect = gspread.exceptions.CellNotFound("not found")
        mock_gspread.col_values.return_value = ["Name", "Alice"]  # 2 rows

        spreadsheet.enroll_person_to_sheet("Bob", "bob@example.com")

        # Should write at row 3 (next after 2 existing rows)
        calls = mock_gspread.update_cell.call_args_list
        assert any(c == call(3, 1, "Bob") for c in calls)
        assert any(c == call(3, 2, "bob@example.com") for c in calls)

    def test_skips_if_already_enrolled(self, mock_gspread, capsys):
        """If student name already exists in sheet, should skip silently."""
        # find() succeeds = student exists
        mock_gspread.find.side_effect = None
        mock_gspread.find.return_value = MagicMock(row=2)

        spreadsheet.enroll_person_to_sheet("Alice", "alice@example.com")

        mock_gspread.update_cell.assert_not_called()
