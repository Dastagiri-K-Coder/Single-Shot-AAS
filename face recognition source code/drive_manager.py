# -*- coding: utf-8 -*-
"""
drive_manager.py — Google Drive & Sheets structure management for Single Shot AAS.

Handles:
  - Creating/finding the "Single Shot AAS" root folder in user's Drive
  - Creating section subfolders and named spreadsheets inside them
  - Spreadsheet naming convention: "Single Shot AAS -X xxxx Y(XXXX-XXXX) S(X)"
  - Uploading institution config and enrollment photos to Drive
  - Checking if a user is new (no root folder) or returning

Functions:
    format_sheet_name(...)              → Generate canonical sheet name
    ensure_root_folder(service)         → Find/create root Drive folder
    ensure_section_folder(...)          → Find/create section subfolder
    create_section_spreadsheet(...)     → Create Sheets spreadsheet in folder
    check_drive_setup_exists(service)   → True if root folder found
    upload_file_to_folder(...)          → Upload a local file to Drive folder
    get_all_sections(service, root_id)  → List all section subfolders
"""

import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials

DRIVE_ROOT_NAME = "Single Shot AAS"


# ── Naming Convention ──────────────────────────────────────────────────────────

def format_sheet_name(
    serial: int,
    section_code: str,
    year_start: int,
    year_end: int,
    section: str,
) -> str:
    """
    Generate canonical spreadsheet name per Working.txt spec.

    Format: "Single Shot AAS -X xxxx Y(XXXX-XXXX) S(X)"
    Example: "Single Shot AAS -1 CSE Y(2024-2027) S(A)"

    Args:
        serial       : Spreadsheet serial number (1, 2, 3, ...)
        section_code : Department/branch code (e.g., "CSE", "MECH", "ECE")
        year_start   : Batch admission year (e.g., 2024)
        year_end     : Batch graduation year (e.g., 2027)
        section      : Section identifier (e.g., "A", "B", "1", "2")
    """
    return f"Single Shot AAS -{serial} {section_code} Y({year_start}-{year_end}) S({section})"


# ── Drive Service Builder ──────────────────────────────────────────────────────

def _build_drive(creds: Credentials):
    """Return authenticated Drive v3 service."""
    return build("drive", "v3", credentials=creds)


def _build_sheets(creds: Credentials):
    """Return authenticated Sheets v4 service."""
    return build("sheets", "v4", credentials=creds)


# ── Folder Operations ─────────────────────────────────────────────────────────

def _find_folder(service, name: str, parent_id: str = None) -> str | None:
    """
    Search Drive for a folder with the given name.
    Returns folder ID if found, else None.
    """
    query = (
        f"name = '{name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=5,
    ).execute()

    files = result.get("files", [])
    return files[0]["id"] if files else None


def _create_folder(service, name: str, parent_id: str = None) -> str:
    """Create a Drive folder. Returns the new folder ID."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=metadata,
        fields="id",
    ).execute()
    return folder["id"]


def ensure_root_folder(creds: Credentials) -> str:
    """
    Find or create the "Single Shot AAS" root folder in the user's Drive.
    Returns the folder ID.
    """
    service = _build_drive(creds)
    folder_id = _find_folder(service, DRIVE_ROOT_NAME)
    if not folder_id:
        folder_id = _create_folder(service, DRIVE_ROOT_NAME)
        print(f"  ✓ Created Drive root folder: '{DRIVE_ROOT_NAME}' ({folder_id})")
    else:
        print(f"  ✓ Found existing Drive root folder: '{DRIVE_ROOT_NAME}' ({folder_id})")
    return folder_id


def ensure_section_folder(creds: Credentials, root_folder_id: str, section_name: str) -> str:
    """
    Find or create a section subfolder under the root folder.
    The subfolder name matches the spreadsheet name.
    Returns the subfolder ID.
    """
    service = _build_drive(creds)
    folder_id = _find_folder(service, section_name, parent_id=root_folder_id)
    if not folder_id:
        folder_id = _create_folder(service, section_name, parent_id=root_folder_id)
        print(f"  ✓ Created section folder: '{section_name}' ({folder_id})")
    else:
        print(f"  ✓ Found section folder: '{section_name}' ({folder_id})")
    return folder_id


# ── Spreadsheet Operations ────────────────────────────────────────────────────

def _find_spreadsheet(drive_service, name: str, parent_id: str) -> str | None:
    """Search for a spreadsheet by name inside a folder. Returns sheet ID or None."""
    query = (
        f"name = '{name}' "
        f"and mimeType = 'application/vnd.google-apps.spreadsheet' "
        f"and '{parent_id}' in parents "
        f"and trashed = false"
    )
    result = drive_service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        pageSize=5,
    ).execute()
    files = result.get("files", [])
    return files[0]["id"] if files else None


def create_section_spreadsheet(
    creds: Credentials,
    sheet_name: str,
    section_folder_id: str,
) -> str:
    """
    Create a Google Spreadsheet inside the section subfolder.
    Initialises it with the standard attendance header row.
    Returns the spreadsheet ID.
    """
    drive_service  = _build_drive(creds)
    sheets_service = _build_sheets(creds)

    # Check if already exists
    existing_id = _find_spreadsheet(drive_service, sheet_name, section_folder_id)
    if existing_id:
        print(f"  ✓ Found existing spreadsheet: '{sheet_name}' ({existing_id})")
        return existing_id

    # Create spreadsheet via Sheets API (starts in user's root)
    sheet_body = {
        "properties": {"title": sheet_name},
        "sheets": [{"properties": {"title": "Attendance"}}],
    }
    spreadsheet = sheets_service.spreadsheets().create(
        body=sheet_body,
        fields="spreadsheetId",
    ).execute()
    sheet_id = spreadsheet["spreadsheetId"]

    # Move it into the section folder
    file = drive_service.files().get(
        fileId=sheet_id, fields="parents"
    ).execute()
    previous_parents = ",".join(file.get("parents", []))
    drive_service.files().update(
        fileId=sheet_id,
        addParents=section_folder_id,
        removeParents=previous_parents,
        fields="id, parents",
    ).execute()

    # Write header row: Name | Email | Gender | PIN | [dates start at col 5]
    header = [["Name", "Email", "Gender", "PIN"]]
    sheets_service.spreadsheets().values().update(
        spreadsheetId=sheet_id,
        range="Attendance!A1:D1",
        valueInputOption="RAW",
        body={"values": header},
    ).execute()

    print(f"  ✓ Created spreadsheet: '{sheet_name}' ({sheet_id})")
    return sheet_id


# ── File Upload ───────────────────────────────────────────────────────────────

def upload_file_to_folder(
    creds: Credentials,
    local_path: str,
    folder_id: str,
    mime_type: str = "application/octet-stream",
    drive_filename: str = None,
) -> str:
    """
    Upload a local file to a Drive folder.
    Returns the uploaded file's Drive ID.
    """
    service = _build_drive(creds)
    drive_filename = drive_filename or os.path.basename(local_path)

    # Check if a file with same name already exists → update it
    query = (
        f"name = '{drive_filename}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )
    result = service.files().list(
        q=query, fields="files(id)", pageSize=1
    ).execute()
    existing = result.get("files", [])

    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=False)

    if existing:
        file_id = existing[0]["id"]
        service.files().update(
            fileId=file_id,
            media_body=media,
        ).execute()
        print(f"  ✓ Updated '{drive_filename}' in Drive ({file_id})")
    else:
        metadata = {"name": drive_filename, "parents": [folder_id]}
        file = service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
        ).execute()
        file_id = file["id"]
        print(f"  ✓ Uploaded '{drive_filename}' to Drive ({file_id})")

    return file_id


# ── Setup Check ───────────────────────────────────────────────────────────────

def check_drive_setup_exists(creds: Credentials) -> bool:
    """
    Return True if the 'Single Shot AAS' root folder exists in the user's Drive.
    Used to determine whether to show Setup Wizard (new user) or Dashboard (returning).
    """
    try:
        service = _build_drive(creds)
        folder_id = _find_folder(service, DRIVE_ROOT_NAME)
        return folder_id is not None
    except Exception as e:
        print(f"  [WARN] Drive check failed: {e}")
        return False


def get_all_sections(creds: Credentials, root_folder_id: str) -> list[dict]:
    """
    List all section subfolders under the root Drive folder.
    Returns list of {"name": str, "folder_id": str} dicts.
    """
    service = _build_drive(creds)
    query = (
        f"'{root_folder_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    result = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)",
        orderBy="name",
    ).execute()
    return [{"name": f["name"], "folder_id": f["id"]} for f in result.get("files", [])]
