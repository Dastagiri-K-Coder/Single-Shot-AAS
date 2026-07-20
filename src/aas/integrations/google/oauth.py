# -*- coding: utf-8 -*-
"""
oauth.py — Google OAuth2 authentication for Single Shot AAS.

Handles user-level OAuth2 flow so the system accesses Google Drive
and Sheets under the logged-in teacher/admin's Google account.

Usage:
    creds = get_credentials()   # Returns valid Credentials object
    is_auth = is_authenticated() # True if valid token exists
    revoke_token()              # Clear stored token (logout)
"""

import os
import json

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from aas.core.config import OAUTH_CREDS_PATH, TOKEN_PATH

# Scopes requested from the user
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# OAuth2 redirect URI (must match GCP Console configuration)
REDIRECT_URI = "http://localhost:5000/auth/google/callback"


def get_credentials() -> Credentials:
    """
    Return valid Google OAuth2 credentials.
    - Loads from token.json if it exists and is valid.
    - Refreshes automatically if expired.
    - Raises FileNotFoundError if no token and no oauth_credentials.json.
    """
    creds = None

    if os.path.exists(TOKEN_PATH):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        except Exception:
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception:
            pass  # Fall through to re-auth

    raise RuntimeError(
        "No valid Google credentials found. "
        "Please log in via the web dashboard at /auth/google"
    )


def is_authenticated() -> bool:
    """Check if a valid (or refreshable) token exists."""
    try:
        get_credentials()
        return True
    except Exception:
        return False


def get_user_info() -> dict:
    """Return cached user info (email, name) from token.json."""
    if not os.path.exists(TOKEN_PATH):
        return {}
    try:
        with open(TOKEN_PATH, "r") as f:
            data = json.load(f)
        return {
            "email": data.get("_email", ""),
            "name":  data.get("_name", ""),
        }
    except Exception:
        return {}


def create_oauth_flow() -> Flow:
    """
    Create a Google OAuth2 Flow object for the web redirect dance.
    Requires oauth_credentials.json to exist (downloaded from GCP Console).
    """
    if not os.path.exists(OAUTH_CREDS_PATH):
        raise FileNotFoundError(
            f"\n\n  ❌  oauth_credentials.json not found at:\n"
            f"     {OAUTH_CREDS_PATH}\n\n"
            "  How to fix:\n"
            "  1. Go to console.cloud.google.com\n"
            "  2. APIs & Services → Credentials → Create Credentials\n"
            "     → OAuth 2.0 Client ID → Web Application\n"
            "  3. Add Authorized redirect URI: http://localhost:5000/auth/google/callback\n"
            "  4. Download JSON → save as 'oauth_credentials.json' inside:\n"
            f"     face recognition source code/\n"
        )
    flow = Flow.from_client_secrets_file(
        OAUTH_CREDS_PATH,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return flow


def save_credentials_from_callback(code: str, user_email: str = "", user_name: str = "") -> Credentials:
    """
    Exchange authorization code for tokens and save to token.json.
    Called by the /auth/google/callback Flask route.
    """
    flow = create_oauth_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials
    _save_token(creds, email=user_email, name=user_name)
    return creds


def revoke_token() -> None:
    """Delete the stored token (logout the current user)."""
    if os.path.exists(TOKEN_PATH):
        os.remove(TOKEN_PATH)


def _save_token(creds: Credentials, email: str = "", name: str = "") -> None:
    """Persist credentials to token.json."""
    data = json.loads(creds.to_json())
    # Embed user info so we can retrieve it without an extra API call
    if email:
        data["_email"] = email
    if name:
        data["_name"] = name
    with open(TOKEN_PATH, "w") as f:
        json.dump(data, f, indent=2)
