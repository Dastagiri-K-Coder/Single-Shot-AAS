# -*- coding: utf-8 -*-
"""
spreadsheet.py — Google Sheets integration for Single Shot AAS.

v2 changes:
  - Uses Google OAuth2 credentials (via oauth.py) instead of service account
  - SpreadsheetManager class routes by sheet_id (multi-camera, multi-sheet)
  - enroll_person_to_sheet() now accepts gender; header has 4 cols: Name, Email, Gender, PIN
  - Date columns start at col 5 (was col 4)
  - Legacy single-sheet module-level functions preserved for backward compat
  - Batch updates for attendance marking (Issue #3)
  - Exponential backoff retry on transient Google API errors (Issue #6)
  - Locale-safe date formatting without platform specifiers (Issue #8)
  - Exact match lookup in sheet to prevent substring false matches (Issue #12)
  - Atomic batch write for enrollment (Issue #18)

Expected Sheet Structure:
    Col 1: Name
    Col 2: Email
    Col 3: Gender  (M / F / O)
    Col 4: PIN
    Col 5+: Dates  (e.g. "7/13/2026", ...)
"""

import datetime
import random
import os
import re

import gspread
import gspread.utils
from google.oauth2.credentials import Credentials

from aas.core.config import CREDS_FILE, SHEET_NAME, MAX_IN_TIME
from aas.core.retry import retry_on_api_error
from aas.notifications import emailing as em

# gspread v6 compatibility for CellNotFound
CellNotFound = getattr(gspread.exceptions, 'CellNotFound', type('CellNotFound', (Exception,), {}))

# ── Google Auth Scopes ─────────────────────────────────────────────────────────
_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Lazy connection (legacy single-sheet) ─────────────────────────────────────
_gc    = None
sheet  = None

# Date column index (1-based): col 5 now that Gender is col 3, PIN is col 4
_DATE_COL_OFFSET = 5   # dates start here


def _get_gspread_client(creds: Credentials = None) -> gspread.Client:
    """Return an authenticated gspread client. Uses OAuth creds if provided."""
    if creds:
        return gspread.authorize(creds)
    # Legacy: service account fallback
    from google.oauth2.service_account import Credentials as SACredentials
    sa_creds = SACredentials.from_service_account_file(CREDS_FILE, scopes=_SCOPES)
    return gspread.authorize(sa_creds)


def _get_sheet():
    """Legacy: lazily initialise the single-sheet Google Sheets connection."""
    global _gc, sheet
    if sheet is not None:
        return sheet
    if not os.path.exists(CREDS_FILE):
        raise FileNotFoundError(
            f"\n\n  ❌  credentials.json not found at:\n"
            f"     {CREDS_FILE}\n\n"
            "  How to fix:\n"
            "  Option A (New): Log in via web dashboard → /auth/google\n"
            "  Option B (Legacy): Add a GCP service account credentials.json\n"
        )
    from google.oauth2.service_account import Credentials as SACredentials
    _creds = SACredentials.from_service_account_file(CREDS_FILE, scopes=_SCOPES)
    _gc    = gspread.authorize(_creds)
    sheet  = _gc.open(SHEET_NAME).sheet1
    return sheet


def _today_string() -> str:
    """Return today's date as locale-safe 'M/D/YYYY' format: e.g. '7/13/2026'."""
    now = datetime.date.today()
    return f"{now.month}/{now.day}/{now.year}"


# ══════════════════════════════════════════════════════════════════════════════
# SpreadsheetManager — multi-sheet, per-camera routing
# ══════════════════════════════════════════════════════════════════════════════

class SpreadsheetManager:
    """
    Manages read/write operations across multiple Google Sheets,
    one per classroom camera/section.

    Usage:
        mgr = SpreadsheetManager(creds)
        mgr.mark_all_absent(sheet_id)
        mgr.write_to_sheet(sheet_id, "John Doe")
        mgr.write_batch_to_sheet(sheet_id, ["John Doe", "Jane Doe"])
    """

    def __init__(self, creds: Credentials = None):
        """
        Args:
            creds: OAuth2 Credentials object. If None, falls back to service account.
        """
        self._gc = _get_gspread_client(creds)
        self._sheet_cache: dict[str, gspread.Worksheet] = {}

    def _get_worksheet(self, sheet_id: str) -> gspread.Worksheet:
        """Return (cached) worksheet for a given sheet ID."""
        if sheet_id not in self._sheet_cache:
            spreadsheet = self._gc.open_by_key(sheet_id)
            # Always use first sheet tab named "Attendance" or sheet1
            try:
                ws = spreadsheet.worksheet("Attendance")
            except gspread.exceptions.WorksheetNotFound:
                ws = spreadsheet.sheet1
            self._sheet_cache[sheet_id] = ws
        return self._sheet_cache[sheet_id]

    @retry_on_api_error()
    def _ensure_date_column(self, ws: gspread.Worksheet) -> int:
        """Ensure today's date column exists. Returns 1-based column index."""
        today  = _today_string()
        header = ws.row_values(1)
        if today in header:
            return header.index(today) + 1
        next_col = len(header) + 1
        ws.update_cell(1, next_col, today)
        print(f"  ✓ Created date column [{today}] at col {next_col}")
        return next_col

    @retry_on_api_error()
    def mark_all_absent(self, sheet_id: str) -> None:
        """Mark every enrolled student absent for today (batch update)."""
        ws       = self._get_worksheet(sheet_id)
        date_col = self._ensure_date_column(ws)
        names    = ws.col_values(1)  # col 1 = Name (includes header)
        updates  = []
        for row_idx in range(2, len(names) + 1):
            cell_addr = gspread.utils.rowcol_to_a1(row_idx, date_col)
            updates.append({"range": cell_addr, "values": [["absent"]]})
        if updates:
            ws.batch_update(updates)
            print(f"  ✓ Marked {len(updates)} student(s) absent in sheet {sheet_id[:8]}...")

    @retry_on_api_error()
    def write_to_sheet(self, sheet_id: str, name: str) -> None:
        """Mark a student present or late. Skips if already present (exact match)."""
        ws       = self._get_worksheet(sheet_id)
        time_now = datetime.datetime.now().strftime('%H:%M:%S')
        try:
            name_cell = ws.find(name, in_column=1, case_sensitive=True)
        except CellNotFound:
            name_cell = None

        if name_cell:
            cell_val = ws.cell(name_cell.row, 1).value
            if cell_val != name:
                name_cell = None

        if not name_cell:
            print(f"  [WARN] '{name}' not found in sheet {sheet_id[:8]}...")
            return

        date_col = self._ensure_date_column(ws)
        current  = ws.cell(name_cell.row, date_col).value
        if current == 'present':
            print(f"  [SKIP] {name} already present.")
            return
        status = 'present' if time_now <= MAX_IN_TIME else 'late'
        ws.update_cell(name_cell.row, date_col, status)
        print(f"  ✓ {name} → {status}")
        email = ws.cell(name_cell.row, 2).value
        if email:
            em.send_email(email, status)

    @retry_on_api_error()
    def write_batch_to_sheet(self, sheet_id: str, names: list[str]) -> list[str]:
        """
        Mark multiple students present/late in a single batch API call.
        Returns list of successfully marked student names.
        """
        if not names:
            return []
        ws = self._get_worksheet(sheet_id)
        date_col = self._ensure_date_column(ws)
        time_now = datetime.datetime.now().strftime('%H:%M:%S')
        status = 'present' if time_now <= MAX_IN_TIME else 'late'

        all_names = ws.col_values(1)
        name_to_row = {n: i + 1 for i, n in enumerate(all_names)}
        current_date_col = ws.col_values(date_col)
        all_emails = ws.col_values(2)

        marked = []
        updates = []
        emails_to_notify = []

        for name in names:
            row = name_to_row.get(name)
            if not row or row == 1:
                print(f"  [WARN] '{name}' not found in sheet {sheet_id[:8]}...")
                continue
            cur_status = current_date_col[row - 1] if row - 1 < len(current_date_col) else ""
            if cur_status == 'present':
                print(f"  [SKIP] {name} already present.")
                continue
            cell_addr = gspread.utils.rowcol_to_a1(row, date_col)
            updates.append({"range": cell_addr, "values": [[status]]})
            marked.append(name)
            print(f"  ✓ {name} → {status}")
            if row - 1 < len(all_emails) and all_emails[row - 1]:
                emails_to_notify.append((all_emails[row - 1], status))

        if updates:
            ws.batch_update(updates)

        for email, st in emails_to_notify:
            try:
                em.send_email(email, st)
            except Exception as ex:
                print(f"  [WARN] Failed to send email to {email}: {ex}")

        return marked

    @retry_on_api_error()
    def enroll_person_to_sheet(
        self,
        sheet_id: str,
        name: str,
        email: str,
        gender: str = "M",
    ) -> None:
        """Add a student to a sheet and send PIN email using an atomic row write."""
        ws = self._get_worksheet(sheet_id)
        try:
            existing = ws.find(name, in_column=1, case_sensitive=True)
            if existing and ws.cell(existing.row, 1).value == name:
                print(f"  [INFO] '{name}' already enrolled.")
                return
        except CellNotFound:
            pass
        nrows = len(ws.col_values(1))
        row   = nrows + 1
        pin   = random.randint(1000, 9999)
        range_str = f"A{row}:D{row}"
        ws.update(values=[[name, email, gender.upper(), pin]], range_name=range_str)
        print(f"  ✓ Enrolled '{name}' (gender={gender}) at row {row}")
        em.email_pin(email, pin)

    @retry_on_api_error()
    def get_today_records(self, sheet_id: str) -> list[dict]:
        """Return today's attendance records: [{name, status, gender}]."""
        ws     = self._get_worksheet(sheet_id)
        today  = _today_string()
        header = ws.row_values(1)
        if today not in header:
            return []
        date_col = header.index(today) + 1
        names    = ws.col_values(1)[1:]
        genders  = ws.col_values(3)[1:]
        statuses = ws.col_values(date_col)[1:]
        records  = []
        for i, n in enumerate(names):
            records.append({
                "name":   n,
                "gender": genders[i] if i < len(genders) else "",
                "status": statuses[i] if i < len(statuses) else "absent",
            })
        return records

    @retry_on_api_error()
    def get_class_total(self, sheet_id: str) -> int:
        """Return total enrolled students in this sheet."""
        ws = self._get_worksheet(sheet_id)
        return max(0, len(ws.col_values(1)) - 1)  # -1 for header


# ══════════════════════════════════════════════════════════════════════════════
# Legacy single-sheet API (backward compatibility)
# ══════════════════════════════════════════════════════════════════════════════

@retry_on_api_error()
def ensure_date_column() -> int:
    s      = _get_sheet()
    today  = _today_string()
    header = s.row_values(1)
    if today in header:
        return header.index(today) + 1
    next_col = len(header) + 1
    s.update_cell(1, next_col, today)
    print(f"  ✓ Created date column [{today}] at column {next_col}")
    return next_col


@retry_on_api_error()
def mark_all_absent() -> None:
    s         = _get_sheet()
    date_col  = ensure_date_column()
    all_names = s.col_values(1)
    updates   = []
    for row_idx in range(2, len(all_names) + 1):
        cell_addr = gspread.utils.rowcol_to_a1(row_idx, date_col)
        updates.append({"range": cell_addr, "values": [["absent"]]})
    if updates:
        s.batch_update(updates)
        print(f"  ✓ Marked {len(updates)} student(s) as absent.")


@retry_on_api_error()
def write_to_sheet(name: str) -> None:
    s        = _get_sheet()
    time_now = datetime.datetime.now().strftime('%H:%M:%S')
    try:
        name_cell = s.find(name, in_column=1, case_sensitive=True)
    except CellNotFound:
        name_cell = None

    if name_cell:
        cell_val = s.cell(name_cell.row, 1).value
        if cell_val != name:
            name_cell = None

    if not name_cell:
        print(f"  [WARN] '{name}' not found in sheet.")
        return

    date_col = ensure_date_column()
    current  = s.cell(name_cell.row, date_col).value
    if current == 'present':
        return
    if current == 'absent':
        status = 'present' if time_now <= MAX_IN_TIME else 'late'
        s.update_cell(name_cell.row, date_col, status)
        print(f"  ✓ {name} → {status}")
        email = s.cell(name_cell.row, 2).value
        if email:
            em.send_email(email, status)


@retry_on_api_error()
def write_batch_to_sheet(names: list[str]) -> list[str]:
    """Legacy: Mark multiple students present/late in single-sheet mode."""
    if not names:
        return []
    s = _get_sheet()
    date_col = ensure_date_column()
    time_now = datetime.datetime.now().strftime('%H:%M:%S')
    status = 'present' if time_now <= MAX_IN_TIME else 'late'

    all_names = s.col_values(1)
    name_to_row = {n: i + 1 for i, n in enumerate(all_names)}
    current_date_col = s.col_values(date_col)
    all_emails = s.col_values(2)

    marked = []
    updates = []
    emails_to_notify = []

    for name in names:
        row = name_to_row.get(name)
        if not row or row == 1:
            print(f"  [WARN] '{name}' not found in sheet.")
            continue
        cur_status = current_date_col[row - 1] if row - 1 < len(current_date_col) else ""
        if cur_status == 'present':
            continue
        cell_addr = gspread.utils.rowcol_to_a1(row, date_col)
        updates.append({"range": cell_addr, "values": [[status]]})
        marked.append(name)
        print(f"  ✓ {name} → {status}")
        if row - 1 < len(all_emails) and all_emails[row - 1]:
            emails_to_notify.append((all_emails[row - 1], status))

    if updates:
        s.batch_update(updates)

    for email, st in emails_to_notify:
        try:
            em.send_email(email, st)
        except Exception as ex:
            print(f"  [WARN] Failed to send email to {email}: {ex}")

    return marked


@retry_on_api_error()
def enroll_person_to_sheet(name: str, email: str, gender: str = "M") -> None:
    s = _get_sheet()
    try:
        existing = s.find(name, in_column=1, case_sensitive=True)
        if existing and s.cell(existing.row, 1).value == name:
            print(f"  [INFO] '{name}' is already enrolled.")
            return
    except CellNotFound:
        pass
    nrows = len(s.col_values(1))
    row   = nrows + 1
    pin   = random.randint(1000, 9999)
    range_str = f"A{row}:D{row}"
    s.update(values=[[name, email, gender.upper(), pin]], range_name=range_str)
    print(f"  ✓ Enrolled '{name}' in sheet at row {row}")
    em.email_pin(email, pin)