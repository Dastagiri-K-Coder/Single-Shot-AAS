"""tests/unit/test_oauth.py — Unit tests for oauth.py"""
import os
import json
import pytest
import tempfile
from unittest.mock import patch, MagicMock


@pytest.fixture
def tmp_token(tmp_path):
    """Create a temporary token.json file."""
    token_data = {
        "token": "ya29.test_access_token",
        "refresh_token": "1//test_refresh_token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client_id",
        "client_secret": "test_client_secret",
        "scopes": ["https://www.googleapis.com/auth/drive"],
        "_email": "test@college.edu",
        "_name": "Test Admin",
    }
    token_path = tmp_path / "token.json"
    token_path.write_text(json.dumps(token_data))
    return str(token_path)


def test_get_user_info(tmp_token, monkeypatch):
    """get_user_info() returns email and name from token.json."""
    monkeypatch.setattr("oauth.TOKEN_PATH", tmp_token)
    import importlib, oauth
    importlib.reload(oauth)
    monkeypatch.setattr("oauth.TOKEN_PATH", tmp_token)
    info = oauth.get_user_info()
    assert info["email"] == "test@college.edu"
    assert info["name"] == "Test Admin"


def test_get_user_info_missing_file(monkeypatch, tmp_path):
    """get_user_info() returns empty dict when token.json does not exist."""
    monkeypatch.setattr("oauth.TOKEN_PATH", str(tmp_path / "nonexistent.json"))
    import oauth
    info = oauth.get_user_info()
    assert info == {}


def test_revoke_token(tmp_token, monkeypatch):
    """revoke_token() deletes token.json."""
    monkeypatch.setattr("oauth.TOKEN_PATH", tmp_token)
    import oauth
    assert os.path.exists(tmp_token)
    oauth.revoke_token()
    assert not os.path.exists(tmp_token)


def test_create_oauth_flow_missing_creds(monkeypatch, tmp_path):
    """create_oauth_flow() raises FileNotFoundError when credentials missing."""
    monkeypatch.setattr("oauth.OAUTH_CREDS_PATH", str(tmp_path / "missing.json"))
    import oauth
    with pytest.raises(FileNotFoundError, match="oauth_credentials.json"):
        oauth.create_oauth_flow()


def test_is_authenticated_no_token(monkeypatch, tmp_path):
    """is_authenticated() returns False when no token file exists."""
    monkeypatch.setattr("oauth.TOKEN_PATH", str(tmp_path / "missing.json"))
    import oauth
    assert oauth.is_authenticated() is False
