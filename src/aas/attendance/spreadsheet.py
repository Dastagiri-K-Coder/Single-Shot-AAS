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


def _today_period_string(subject: str = '', period: int = 0) -> str:
    """Return a column header string for a subject+period attendance event.

    v2.0: Each subject-period gets its own column instead of one per day.

    Examples:
        subject='DBMS', period=3  → '9/17 DBMS P3'
        subject='',     period=0  → '9/17/2026'   (backward-compatible legacy format)

    Args:
        subject : Subject name (e.g. 'DBMS', 'Mathematics'). Empty for legacy.
        period  : Period number (1-based). 0 for legacy.

    Returns:
        Column header string.
    """
    now = datetime.date.today()
    if subject and period:
        return f"{now.month}/{now.day} {subject} P{period}"
    return f"{now.month}/{now.day}/{now.year}"  # legacy fallback



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


# ══════════════════════════════════════════════════════════════════════════════
# WEEKLY SHEET CONSTANTS — matches Sample Structure of Attendance Sheet.xlsx
# ══════════════════════════════════════════════════════════════════════════════
#
# Column layout (49 columns total):
#   A        = S.No.          (col 1)
#   B        = Name           (col 2)
#   C        = Roll Number    (col 3)
#   D–AM     = Attendance     (cols 4–39, 6 subjects × 6 days = 36 cols)
#   AN–AS    = Subject-wise cumulative totals (cols 40–45, 6 cols)
#   AT       = Total Attended (col 46)
#   AU       = Total Conducted (col 47)
#   AV       = Attendance %   (col 48)
#   AW       = Eligibility    (col 49)
#
# Attendance cell values: 1 = Present, 0 = Absent, '' = not yet recorded
# Row layout:
#   Row 1 = Title
#   Row 2 = Metadata (class, section, semester, faculty, room)
#   Row 3 = Week info (duration, curriculum, marking guide, rule)
#   Row 4 = Summary stat headers
#   Row 5 = Summary stat values (live formulas)
#   Row 6 = Empty separator
#   Row 7 = Day group headers (Day 1 Mon-DD/MM, … Day 6)
#   Row 8 = Subject names row
#   Row 9+ = Student data rows
# ══════════════════════════════════════════════════════════════════════════════

DAYS_SHORT      = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
SUBJECTS_PER_DAY = 6                                 # periods/subjects per day
_STUDENT_COLS   = 3                                  # A, B, C
_ATTEND_COLS    = SUBJECTS_PER_DAY * len(DAYS_SHORT) # 36
_CUM_COLS       = SUBJECTS_PER_DAY                   # 6 subject-cumulative cols
_SUMMARY_COLS   = 4                                  # Attended, Conducted, %, Eligibility
_TOTAL_COLS     = _STUDENT_COLS + _ATTEND_COLS + _CUM_COLS + _SUMMARY_COLS  # 49

# 1-based column indices (for formula construction)
_ATTEND_START  = _STUDENT_COLS + 1                   # col 4  (D)
_ATTEND_END    = _STUDENT_COLS + _ATTEND_COLS         # col 39 (AM)
_CUM_START     = _ATTEND_END + 1                     # col 40 (AN)
_CUM_END       = _CUM_START + _CUM_COLS - 1          # col 45 (AS)
_ATTENDED_COL  = _CUM_END + 1                        # col 46 (AT)
_CONDUCTED_COL = _ATTENDED_COL + 1                   # col 47 (AU)
_PCT_COL       = _CONDUCTED_COL + 1                  # col 48 (AV)
_ELIGIBLE_COL  = _PCT_COL + 1                        # col 49 (AW)

# Header rows (1-based)
_HEADER_ROWS   = 8
_DATA_START_ROW = _HEADER_ROWS + 1                   # 9


def _col_letter(col_1based: int) -> str:
    """Convert 1-based column number to A1-notation letter(s)."""
    result = ''
    n = col_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _attend_col(day_idx: int, subj_idx: int) -> int:
    """Return 1-based column for attendance[day_idx][subj_idx].
    day_idx : 0=Mon … 5=Sat
    subj_idx: 0-5 (period/subject slot within day)
    """
    return _ATTEND_START + day_idx * SUBJECTS_PER_DAY + subj_idx


def _week_dates(iso_week: int, year: int) -> list[datetime.date]:
    """Return Mon–Sat date list for the given ISO week/year."""
    jan4 = datetime.date(year, 1, 4)
    monday = jan4 - datetime.timedelta(days=jan4.weekday()) + datetime.timedelta(weeks=iso_week - 1)
    return [monday + datetime.timedelta(days=i) for i in range(6)]


def _get_or_create_weekly_sheet(
    gc: gspread.Client,
    spreadsheet_id: str,
    week_label: str,
) -> tuple['gspread.Spreadsheet', gspread.Worksheet]:
    spreadsheet = gc.open_by_key(spreadsheet_id)
    try:
        ws = spreadsheet.worksheet(week_label)
        return spreadsheet, ws
    except gspread.exceptions.WorksheetNotFound:
        pass
    spreadsheet.add_worksheet(title=week_label, rows=300, cols=_TOTAL_COLS + 2)
    ws = spreadsheet.worksheet(week_label)
    print(f"  ✓ Created weekly sheet tab '{week_label}'")
    return spreadsheet, ws


def create_weekly_sheet(
    gc: gspread.Client,
    spreadsheet_id: str,
    section: str,
    week_label: str,
    students: list[dict],
    timetable: dict | None = None,
    metadata: dict | None = None,
) -> str:
    """Build a 49-column weekly attendance sheet matching the sample structure.

    Column layout:
        A–C   : S.No, Name, Roll Number
        D–AM  : Attendance (6 subjects × 6 days = 36 cols)   value=1/0
        AN–AS : Subject-wise cumulative totals (6 cols)
        AT    : Total Attended
        AU    : Total Conducted (=36)
        AV    : Attendance %
        AW    : Eligibility (Eligible / Shortage)

    Row layout:
        1  : Title
        2  : Metadata (Class, Section, Semester, Faculty, Room)
        3  : Week info (duration, curriculum, marking guide, rule)
        4  : Summary stat headers
        5  : Summary stat values (live formulas)
        6  : Empty separator
        7  : Day group headers with actual dates
        8  : Subject names per slot
        9+ : Student rows

    Args:
        gc             : authenticated gspread Client
        spreadsheet_id : Google Spreadsheet ID (from cameras.json sheet_id)
        section        : e.g. 'CSE-A'
        week_label     : e.g. 'Week 39 2026'
        students       : list of {name, roll_number}
        timetable      : dict mapping day_short → [subj0, subj1, …, subj5]
                         If None, uses generic P1..P6 labels
        metadata       : dict with optional keys: class_name, semester,
                         academic_year, faculty, room, department

    Returns:
        Worksheet tab name (== week_label)
    """
    spreadsheet, ws = _get_or_create_weekly_sheet(gc, spreadsheet_id, week_label)
    meta = metadata or {}

    # ── Calculate week dates ──────────────────────────────────────────────
    # Parse week_label "Week 39 2026"
    try:
        parts    = week_label.split()
        iso_week = int(parts[1])
        year     = int(parts[2])
    except Exception:
        iso_week = datetime.date.today().isocalendar()[1]
        year     = datetime.date.today().year

    dates = _week_dates(iso_week, year)  # [Mon, Tue, Wed, Thu, Fri, Sat]
    mon_str = dates[0].strftime('%d/%m/%Y')
    sat_str = dates[5].strftime('%d/%m/%Y')

    n_students = len(students)
    last_data_row = _DATA_START_ROW + n_students - 1
    last_col_letter = _col_letter(_TOTAL_COLS)  # AW

    # Short-hand helpers
    def CL(c): return _col_letter(c)  # 1-based col → letter
    attended_cl  = CL(_ATTENDED_COL)
    conducted_cl = CL(_CONDUCTED_COL)
    pct_cl       = CL(_PCT_COL)
    attend_start_cl = CL(_ATTEND_START)   # D
    attend_end_cl   = CL(_ATTEND_END)     # AM
    cum_start_cl    = CL(_CUM_START)      # AN

    # ── Default subjects list ──────────────────────────────────────────────
    default_subjects = ['Maths', 'PHY', 'CHE', 'CSE', 'ENG', 'EVS']

    def _day_subjects(day_short: str) -> list[str]:
        if timetable and day_short in timetable:
            subjs = timetable[day_short]
            return (subjs + [''] * SUBJECTS_PER_DAY)[:SUBJECTS_PER_DAY]
        return default_subjects

    # Assume subjects are consistent across days for cumulative labelling
    subject_labels = _day_subjects('Mon')

    all_data: list[list] = []

    # ── ROW 1: Title ──────────────────────────────────────────────────────
    dept = meta.get('department', 'Computer Science & Engineering')
    row1 = [f"WEEKLY ATTENDANCE REGISTER — DEPARTMENT OF {dept.upper()}"]
    row1 += [''] * (_TOTAL_COLS - 1)
    all_data.append(row1)

    # ── ROW 2: Metadata ───────────────────────────────────────────────────
    row2 = [
        'Class & Degree:', '',  '', meta.get('class_name', 'B.Tech'), '', '', '', '', '',
        'Section:', '', '', section, '', '', '', '',
        'Semester:', '', '', meta.get('semester', ''), '', '', '',
        'Academic Year:', '', '', meta.get('academic_year', f"{year}–{year+1}"), '', '', '', '',
        'Faculty:', '', '', meta.get('faculty', ''), '', '', '', '',
        'Room / Lab:', '', '', meta.get('room', ''), '', '', '', '',
    ]
    row2 = (row2 + [''] * _TOTAL_COLS)[:_TOTAL_COLS]
    all_data.append(row2)

    # ── ROW 3: Week info ──────────────────────────────────────────────────
    row3 = [
        'Week Duration:', '', '', f"{mon_str} – {sat_str}", '', '', '', '', '',
        'Working Days:', '', '', '6 Days (Mon - Sat)', '', '', '', '',
        'Curriculum:', '', '', f"{SUBJECTS_PER_DAY} Subjects ({_ATTEND_COLS} Periods/Wk)", '', '', '',
        'Marking Guide:', '', '', '1 / P = Present, 0 / A = Absent', '', '', '', '',
        'Attendance Rule:', '', '', 'Min 75.0% for Exam Eligibility', '', '', '', '',
        'Register Status:', '', '', 'Active & Verified', '', '', '', '',
    ]
    row3 = (row3 + [''] * _TOTAL_COLS)[:_TOTAL_COLS]
    all_data.append(row3)

    # ── ROW 4: Summary stat headers ───────────────────────────────────────
    # Span across 5 groups of columns
    row4 = ['TOTAL STUDENTS'] + [''] * 9 + \
           ['TOTAL SESSIONS'] + [''] * 9 + \
           ['CLASS AVERAGE'] + [''] * 9 + \
           ['ELIGIBLE STUDENTS (≥75%)'] + [''] * 9 + \
           ['ATTENDANCE SHORTAGE (<75%)'] + [''] * (_TOTAL_COLS - 41)
    row4 = (row4 + [''] * _TOTAL_COLS)[:_TOTAL_COLS]
    all_data.append(row4)

    # ── ROW 5: Summary values (live formulas) ─────────────────────────────
    # These reference the student data range (rows 9 → last_data_row)
    if n_students > 0:
        total_students_f  = str(n_students)
        total_sessions_f  = str(_ATTEND_COLS)
        class_avg_f       = (f"=IFERROR(AVERAGE({pct_cl}{_DATA_START_ROW}"
                             f":{pct_cl}{last_data_row}),0)")
        eligible_f        = (f"=COUNTIF({pct_cl}{_DATA_START_ROW}"
                             f":{pct_cl}{last_data_row},\">=\"&0.75)")
        shortage_f        = (f"=COUNTIF({pct_cl}{_DATA_START_ROW}"
                             f":{pct_cl}{last_data_row},\"<\"&0.75)")
    else:
        total_students_f = '0'
        total_sessions_f = str(_ATTEND_COLS)
        class_avg_f = eligible_f = shortage_f = '0'

    row5 = [total_students_f] + [''] * 9 + \
           [total_sessions_f] + [''] * 9 + \
           [class_avg_f] + [''] * 9 + \
           [eligible_f] + [''] * 9 + \
           [shortage_f] + [''] * (_TOTAL_COLS - 41)
    row5 = (row5 + [''] * _TOTAL_COLS)[:_TOTAL_COLS]
    all_data.append(row5)

    # ── ROW 6: Empty separator ────────────────────────────────────────────
    all_data.append([''] * _TOTAL_COLS)

    # ── ROW 7: Day group headers with dates ───────────────────────────────
    row7: list = ['S.No.', 'Name of Student', 'Roll Number']
    for d_idx, (day, date) in enumerate(zip(DAYS_SHORT, dates)):
        label = f"Day {d_idx+1} ({day} - {date.strftime('%d/%m')})"
        row7 += [label] + [''] * (SUBJECTS_PER_DAY - 1)
    row7 += [f"CUMULATIVE ATTENDANCE (SUBJECT-WISE)"] + [''] * (_CUM_COLS - 1)
    row7 += ['OVERALL ATTENDANCE SUMMARY'] + [''] * (_SUMMARY_COLS - 1)
    all_data.append(row7)

    # ── ROW 8: Subject names ──────────────────────────────────────────────
    row8: list = ['', '', '']
    for day_short in DAYS_SHORT:
        row8 += _day_subjects(day_short)
    row8 += subject_labels  # cumulative col headers = same subject labels
    row8 += ['Attended', 'Conducted', 'Attendance %', 'Eligibility']
    all_data.append(row8)

    # ── ROWS 9+: Student data ─────────────────────────────────────────────
    for s_idx, student in enumerate(students):
        row_num = _DATA_START_ROW + s_idx

        # Per-subject cumulative formulas: sum the same subject slot across all 6 days
        cum_formulas = []
        for subj_i in range(SUBJECTS_PER_DAY):
            cols_for_subject = [CL(_attend_col(d, subj_i)) for d in range(len(DAYS_SHORT))]
            refs = '+'.join(f"{c}{row_num}" for c in cols_for_subject)
            cum_formulas.append(f"={refs}")

        attended_f  = f"=SUM({attend_start_cl}{row_num}:{attend_end_cl}{row_num})"
        conducted_f = str(_ATTEND_COLS)
        pct_f       = f"=IF({conducted_cl}{row_num}>0,{attended_cl}{row_num}/{conducted_cl}{row_num},0)"
        eligible_f  = f"=IF({pct_cl}{row_num}>=0.75,\"Eligible\",\"Shortage\")"

        student_row = [
            s_idx + 1,
            student.get('name', ''),
            student.get('roll_number', ''),
        ] + [''] * _ATTEND_COLS + cum_formulas + [
            attended_f,
            conducted_f,
            pct_f,
            eligible_f,
        ]
        all_data.append(student_row)

    # ── Batch write all rows ──────────────────────────────────────────────
    update_range = f"A1:{last_col_letter}{len(all_data)}"
    ws.update(values=all_data, range_name=update_range)
    print(f"  ✓ Weekly sheet '{week_label}': {n_students} students, "
          f"{_TOTAL_COLS} cols, rows 1-{len(all_data)}")

    return week_label


# ══════════════════════════════════════════════════════════════════════════════
# write_attendance_event — write 1/0 into correct day×subject column
# ══════════════════════════════════════════════════════════════════════════════

def write_attendance_event(
    gc: gspread.Client,
    spreadsheet_id: str,
    sheet_tab_name: str,
    students: list[dict],
    present_names: set[str],
    day_of_week: int,
    period_num: int,
) -> None:
    """Write attendance values (1=present, 0=absent) into the correct column.

    Uses the same 49-column layout as create_weekly_sheet().
    Attendance value: 1 (present) or 0 (absent). Empty = not yet recorded.

    Args:
        students       : list of {name, roll_number, row_index}
                         row_index = 1-based sheet row (9 = first student)
        present_names  : set of student names marked present (exact match)
        day_of_week    : 0=Mon … 5=Sat
        period_num     : 1-6 (maps to subject slot index 0-5 within the day)
    """
    spreadsheet = gc.open_by_key(spreadsheet_id)
    try:
        ws = spreadsheet.worksheet(sheet_tab_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"  [WARN] Tab '{sheet_tab_name}' not found — call create_weekly_sheet first.")
        return

    subj_idx   = max(0, min(period_num - 1, SUBJECTS_PER_DAY - 1))  # 0-based
    col_1based = _attend_col(day_of_week, subj_idx)
    col_letter = _col_letter(col_1based)

    updates: list[dict] = []
    for student in students:
        name    = student.get('name', '')
        row_idx = student.get('row_index', 0)
        if not row_idx:
            continue
        value = 1 if name in present_names else 0
        updates.append({"range": f"{col_letter}{row_idx}", "values": [[value]]})

    if updates:
        ws.batch_update(updates)
        p_count = sum(1 for u in updates if u["values"][0][0] == 1)
        a_count = len(updates) - p_count
        print(f"  ✓ write_attendance_event: {p_count} present / {a_count} absent "
              f"[Day {day_of_week} P{period_num} → col {col_letter}]")


# ══════════════════════════════════════════════════════════════════════════════
# get_student_summary / get_section_summary — reads 1/0 values
# ══════════════════════════════════════════════════════════════════════════════

def get_student_summary(
    gc: gspread.Client,
    spreadsheet_id: str,
    student_name: str,
    eligibility_threshold: float = 0.75,
) -> dict:
    """Aggregate attendance for one student across all weekly tabs.

    Reads columns AT (attended) and AU (conducted) directly from the sheet
    (where possible) or counts 1s in the attendance block.

    Returns:
        {name, total_classes, attended, percentage, eligible}
    """
    spreadsheet   = gc.open_by_key(spreadsheet_id)
    total_classes = 0
    attended      = 0

    for ws in spreadsheet.worksheets():
        if not ws.title.lower().startswith('week '):
            continue
        names_col = ws.col_values(2)  # Column B

        # Find student row (case-insensitive, underscore-tolerant)
        row_idx = None
        target  = student_name.replace('_', ' ').lower()
        for i, n in enumerate(names_col):
            if n and n.replace('_', ' ').lower() == target:
                row_idx = i + 1
                break
        if not row_idx:
            continue

        row_vals = ws.row_values(row_idx)
        # Read attendance block (cols 4–39, 0-based indices 3–38)
        for col_0 in range(_ATTEND_START - 1, _ATTEND_END):
            val = row_vals[col_0] if col_0 < len(row_vals) else ''
            try:
                v = float(val)
                if v in (0, 1):
                    total_classes += 1
                    attended += int(v)
            except (ValueError, TypeError):
                pass

    pct = attended / total_classes if total_classes else 0.0
    return {
        'name':          student_name,
        'total_classes': total_classes,
        'attended':      attended,
        'percentage':    round(pct * 100, 1),
        'eligible':      pct >= eligibility_threshold,
    }


def get_section_summary(
    gc: gspread.Client,
    spreadsheet_id: str,
    eligibility_threshold: float = 0.75,
) -> list[dict]:
    """Return aggregated attendance for all students across all weekly tabs.

    Returns:
        Sorted list of {name, roll_number, total_classes, attended, percentage, eligible}
    """
    spreadsheet   = gc.open_by_key(spreadsheet_id)
    student_index: dict[str, dict] = {}

    for ws in spreadsheet.worksheets():
        if not ws.title.lower().startswith('week '):
            continue

        names_col = ws.col_values(2)[_DATA_START_ROW - 1:]   # skip header rows
        rolls_col = ws.col_values(3)[_DATA_START_ROW - 1:]

        for i, name in enumerate(names_col):
            if not name:
                continue
            key = name.replace('_', ' ').lower()
            if key not in student_index:
                student_index[key] = {
                    'name':        name,
                    'roll_number': rolls_col[i] if i < len(rolls_col) else '',
                    'attended':    0,
                    'total':       0,
                }
            sheet_row = _DATA_START_ROW + i
            row_vals  = ws.row_values(sheet_row)
            for col_0 in range(_ATTEND_START - 1, _ATTEND_END):
                val = row_vals[col_0] if col_0 < len(row_vals) else ''
                try:
                    v = float(val)
                    if v in (0, 1):
                        student_index[key]['total'] += 1
                        student_index[key]['attended'] += int(v)
                except (ValueError, TypeError):
                    pass

    result = []
    for stu in student_index.values():
        total    = stu['total']
        attended = stu['attended']
        pct      = attended / total if total else 0.0
        result.append({
            'name':          stu['name'],
            'roll_number':   stu['roll_number'],
            'total_classes': total,
            'attended':      attended,
            'percentage':    round(pct * 100, 1),
            'eligible':      pct >= eligibility_threshold,
        })

    return sorted(result, key=lambda x: x['name'])

