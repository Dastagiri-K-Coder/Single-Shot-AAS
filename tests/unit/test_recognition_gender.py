"""tests/unit/test_recognition_gender.py — Tests for gender-aware recognition loading."""
import os
import pickle
import tempfile
import numpy as np
import pytest
from unittest.mock import patch
from aas.recognition import engine as recognition


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_encoding():
    """Return a deterministic 128-D unit vector (valid face encoding shape)."""
    rng = np.random.default_rng(42)
    enc = rng.random(128).astype(np.float64)
    return enc / np.linalg.norm(enc)


def _write_pkl(folder, name, gender, num_angles=3):
    """Write a v2 dict-format .pkl file and return its path."""
    encodings = [_make_encoding() for _ in range(num_angles)]
    payload = {"name": name, "gender": gender, "encodings": encodings}
    path = os.path.join(folder, f"{name}.pkl")
    with open(path, "wb") as f:
        pickle.dump(payload, f)
    return path


def _write_legacy_pkl(folder, name, num_angles=2):
    """Write a legacy bare-list .pkl file (no gender key)."""
    encodings = [_make_encoding() for _ in range(num_angles)]
    path = os.path.join(folder, f"{name}.pkl")
    with open(path, "wb") as f:
        pickle.dump(encodings, f)
    return path


# ── Tests: load_facial_encodings_and_names_from_memory ───────────────────────

def test_load_new_format_gender(tmp_path, monkeypatch):
    """New dict pkl: gender is loaded into known_face_genders."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))
    _write_pkl(str(tmp_path), "alice", "F", num_angles=2)
    _write_pkl(str(tmp_path), "bob",   "M", num_angles=3)

    recognition.load_facial_encodings_and_names_from_memory()

    assert recognition.known_face_genders.get("alice") == "F"
    assert recognition.known_face_genders.get("bob")   == "M"


def test_load_new_format_encoding_count(tmp_path, monkeypatch):
    """New dict pkl: all angle encodings are loaded individually."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))
    _write_pkl(str(tmp_path), "carol", "F", num_angles=3)

    recognition.load_facial_encodings_and_names_from_memory()

    count = recognition.known_face_names.count("carol")
    assert count == 3, f"Expected 3 encodings for carol, got {count}"


def test_load_legacy_format_defaults_to_male(tmp_path, monkeypatch):
    """Legacy bare-list pkl: gender defaults to 'M'."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))
    _write_legacy_pkl(str(tmp_path), "dave", num_angles=2)

    recognition.load_facial_encodings_and_names_from_memory()

    assert recognition.known_face_genders.get("dave") == "M"
    assert recognition.known_face_names.count("dave") == 2


def test_load_mixed_formats(tmp_path, monkeypatch):
    """Mix of new and legacy pkl files loads correctly."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))
    _write_pkl(str(tmp_path),        "eve",  "F", num_angles=3)
    _write_legacy_pkl(str(tmp_path), "frank",     num_angles=1)

    recognition.load_facial_encodings_and_names_from_memory()

    assert recognition.known_face_genders.get("eve")   == "F"
    assert recognition.known_face_genders.get("frank") == "M"
    assert len(recognition.known_face_encodings) == 4  # 3 + 1


# ── Tests: run_recognition result dict ───────────────────────────────────────

def test_run_recognition_boys_girls_count(tmp_path, monkeypatch):
    """run_recognition result must include boys_count, girls_count, other_count."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))
    _write_pkl(str(tmp_path), "boy1",  "M", num_angles=1)
    _write_pkl(str(tmp_path), "boy2",  "M", num_angles=1)
    _write_pkl(str(tmp_path), "girl1", "F", num_angles=1)

    recognition.load_facial_encodings_and_names_from_memory()

    # Simulate a result where all three are "present"
    with patch("aas.recognition.engine.run_recognition") as mock_run:
        mock_run.return_value = {
            "present":         ["boy1", "boy2", "girl1"],
            "present_genders": {"boy1": "M", "boy2": "M", "girl1": "F"},
            "boys_count":      2,
            "girls_count":     1,
            "other_count":     0,
            "unknown_count":   0,
            "total_faces":     3,
            "quality_ok":      True,
            "quality_msg":     "",
            "recognized_at":   "2026-07-20T12:00:00",
        }
        result = recognition.run_recognition("dummy_path.jpg")

    assert result["boys_count"]  == 2
    assert result["girls_count"] == 1
    assert result["other_count"] == 0
    assert "present_genders" in result


def test_result_dict_has_required_keys(tmp_path, monkeypatch):
    """run_recognition result always has boys_count and girls_count keys."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))
    _write_pkl(str(tmp_path), "student_a", "M", num_angles=1)

    recognition.load_facial_encodings_and_names_from_memory()

    required_keys = {
        "present", "boys_count", "girls_count", "other_count",
        "unknown_count", "total_faces", "quality_ok", "recognized_at",
    }

    with patch("aas.recognition.engine.run_recognition") as mock_run:
        mock_run.return_value = {k: 0 if k != "present" else [] for k in required_keys}
        mock_run.return_value["present"]      = []
        mock_run.return_value["recognized_at"] = "2026-07-20T12:00:00"
        mock_run.return_value["quality_ok"]   = True
        result = recognition.run_recognition("dummy.jpg")

    for key in required_keys:
        assert key in result, f"Missing key in result: '{key}'"


# ── Tests: gender count calculation ──────────────────────────────────────────

def test_boys_count_all_male(tmp_path, monkeypatch):
    """All-male class: boys_count == len(present), girls_count == 0."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))

    recognition.known_face_genders = {"m1": "M", "m2": "M", "m3": "M"}

    present = ["m1", "m2", "m3"]
    boys  = sum(1 for n in present if recognition.known_face_genders.get(n) == "M")
    girls = sum(1 for n in present if recognition.known_face_genders.get(n) == "F")

    assert boys  == 3
    assert girls == 0


def test_girls_count_all_female(tmp_path, monkeypatch):
    """All-female class: girls_count == len(present), boys_count == 0."""
    monkeypatch.setattr("aas.recognition.engine.ENCODINGS_FOLDER", str(tmp_path))

    recognition.known_face_genders = {"f1": "F", "f2": "F"}

    present = ["f1", "f2"]
    boys  = sum(1 for n in present if recognition.known_face_genders.get(n) == "M")
    girls = sum(1 for n in present if recognition.known_face_genders.get(n) == "F")

    assert boys  == 0
    assert girls == 2


def test_gender_count_mixed_class():
    """Mixed class: boys and girls counted separately."""
    recognition.known_face_genders = {
        "ram":  "M", "sita": "F", "ravi": "M",
        "priya": "F", "ajay": "M",
    }
    present = ["ram", "sita", "ravi", "priya", "ajay"]
    boys  = sum(1 for n in present if recognition.known_face_genders.get(n) == "M")
    girls = sum(1 for n in present if recognition.known_face_genders.get(n) == "F")

    assert boys  == 3
    assert girls == 2
    assert boys + girls == len(present)
