"""tests/unit/test_camera_registry.py — Unit tests for camera_registry.py"""
import os
import json
import pytest
from unittest.mock import patch


@pytest.fixture
def tmp_cameras_json(tmp_path):
    path = tmp_path / "cameras.json"
    path.write_text('{"cameras": []}')
    return str(path)


def test_load_cameras_empty(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    assert camera_registry.load_cameras() == []


def test_save_and_load_cameras(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    cameras = [{"id": "cam_001", "display_name": "Test Cam", "rtsp_url": "rtsp://192.168.1.10/stream"}]
    camera_registry.save_cameras(cameras)
    loaded = camera_registry.load_cameras()
    assert len(loaded) == 1
    assert loaded[0]["id"] == "cam_001"


def test_get_camera_found(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    cam = {"id": "cam_abc", "display_name": "ABC Lab", "rtsp_url": ""}
    camera_registry.save_cameras([cam])
    result = camera_registry.get_camera("cam_abc")
    assert result is not None
    assert result["display_name"] == "ABC Lab"


def test_get_camera_not_found(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    result = camera_registry.get_camera("nonexistent")
    assert result is None


def test_delete_camera(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    camera_registry.save_cameras([{"id": "cam_x", "display_name": "X"}])
    removed = camera_registry.delete_camera("cam_x")
    assert removed is True
    assert camera_registry.load_cameras() == []


def test_delete_camera_not_found(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    removed = camera_registry.delete_camera("does_not_exist")
    assert removed is False


def test_update_camera(tmp_cameras_json, monkeypatch):
    monkeypatch.setattr("camera_registry.CAMERAS_JSON_PATH", tmp_cameras_json)
    import camera_registry
    camera_registry.save_cameras([{"id": "cam_y", "sheet_id": "", "display_name": "Y"}])
    updated = camera_registry.update_camera("cam_y", sheet_id="abc123")
    assert updated["sheet_id"] == "abc123"
    reloaded = camera_registry.get_camera("cam_y")
    assert reloaded["sheet_id"] == "abc123"
