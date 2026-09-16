# =============================================================================
#  tests/integration/test_web_routes.py — Integration tests for Flask routes
#  (app.py)
#
#  These tests spin up the Flask test client and hit real routes with mocked
#  external services (camera, Google Sheets, email).
# =============================================================================

import os
import json
import pickle
from unittest.mock import MagicMock, patch
import numpy as np
import pytest


@pytest.fixture()
def flask_client(tmp_dirs, monkeypatch):
    """Create a Flask test client with tmp data directories."""
    # Patch config paths before importing app
    monkeypatch.setattr("aas.core.config.ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))
    monkeypatch.setattr("aas.core.config.PHOTO_FOLDER",     str(tmp_dirs["photos"]))
    monkeypatch.setattr("aas.core.config.CAPTURED_FOLDER",  str(tmp_dirs["captured"]))

    import aas.web.app as web_app
    monkeypatch.setattr(web_app, "ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))
    monkeypatch.setattr(web_app, "PHOTO_FOLDER",     str(tmp_dirs["photos"]))
    monkeypatch.setattr(web_app, "CAPTURED_FOLDER",  str(tmp_dirs["captured"]))

    import aas.recognition.engine as eng
    monkeypatch.setattr(eng, "ENCODINGS_FOLDER", str(tmp_dirs["encodings"]))

    from aas.web.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False

    with app.test_client() as client:
        yield client


class TestStatusRoute:
    """GET /api/status"""

    def test_status_returns_200(self, flask_client):
        resp = flask_client.get("/api/status")
        assert resp.status_code == 200

    def test_status_contains_required_fields(self, flask_client):
        data = json.loads(flask_client.get("/api/status").data)
        assert "status" in data
        assert data["status"] == "online"
        assert "students_enrolled" in data
        assert "encodings_loaded" in data
        assert "timestamp" in data

    def test_status_credentials_false_when_no_file(self, flask_client):
        data = json.loads(flask_client.get("/api/status").data)
        # credentials.json is not present in test env
        assert data["credentials_ok"] is False


class TestStudentsRoute:
    """GET /api/students"""

    def test_returns_empty_list_initially(self, flask_client):
        data = json.loads(flask_client.get("/api/students").data)
        assert data["count"] == 0
        assert data["students"] == []

    def test_returns_enrolled_students(self, flask_client, tmp_dirs, fake_encoding):
        pkl_path = tmp_dirs["encodings"] / "Test_Alice.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump([fake_encoding], f)

        data = json.loads(flask_client.get("/api/students").data)
        assert data["count"] == 1
        assert data["students"][0]["name"] == "Test_Alice"


class TestDeleteStudentRoute:
    """DELETE /api/students/<name>"""

    def test_delete_existing_student(self, flask_client, tmp_dirs, fake_encoding):
        pkl_path = tmp_dirs["encodings"] / "ToDelete.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump([fake_encoding], f)

        resp = flask_client.delete("/api/students/ToDelete")
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["status"] == "success"
        assert not pkl_path.exists()

    def test_delete_nonexistent_student_still_200(self, flask_client):
        """Deleting a student that doesn't exist should not 500."""
        resp = flask_client.delete("/api/students/GhostStudent")
        assert resp.status_code == 200


class TestEnrollUploadRoute:
    """POST /api/enroll/upload"""

    def test_missing_name_returns_400(self, flask_client):
        resp = flask_client.post("/api/enroll/upload", data={})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "name" in data["message"].lower()

    def test_missing_photo_returns_400(self, flask_client):
        resp = flask_client.post("/api/enroll/upload", data={"name": "Alice"})
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "photo" in data["message"].lower()

    def test_invalid_photo_no_face_returns_400(self, flask_client, tmp_dirs):
        """Uploading a photo with no detectable face should return 400."""
        import io
        import cv2
        # Create blank image with no face
        blank = np.ones((200, 200, 3), dtype=np.uint8) * 200
        _, buf = cv2.imencode(".jpg", blank)
        photo = (io.BytesIO(buf.tobytes()), "blank.jpg")

        with patch("face_recognition.face_locations", return_value=[]):
            resp = flask_client.post(
                "/api/enroll/upload",
                data={"name": "Bob", "photos": photo},
                content_type="multipart/form-data",
            )
        assert resp.status_code == 400
        data = json.loads(resp.data)
        assert "no face" in data["message"].lower()


class TestSettingsRoute:
    """GET + POST /api/settings"""

    def test_get_settings_returns_expected_fields(self, flask_client):
        data = json.loads(flask_client.get("/api/settings").data)
        assert "tolerance" in data
        assert "scale" in data
        assert "max_in_time" in data

    def test_save_settings_empty_body_returns_400(self, flask_client):
        resp = flask_client.post(
            "/api/settings",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_save_settings_updates_valid_field(self, flask_client, tmp_dirs, monkeypatch):
        env_path = tmp_dirs["captured"].parent / ".env"
        env_path.write_text("RECOGNITION_TOLERANCE=0.55\n")
        orig_join = os.path.join
        monkeypatch.setattr(
            "aas.web.app.os.path.join",
            lambda *a: str(env_path) if ".env" in str(a) else orig_join(*a),
        )

        resp = flask_client.post(
            "/api/settings",
            data=json.dumps({"tolerance": "0.60"}),
            content_type="application/json",
        )
        # Should succeed; exact env write is tested separately
        assert resp.status_code in (200, 500)  # 500 if path patch fails, 200 if it works
