"""tests/unit/conftest.py — Stubs for heavy system-level modules not in test env."""
import sys
import types
from unittest.mock import MagicMock


def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__file__ = f"<stub:{name}>"
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def _ensure_parent(dotted):
    parts = dotted.split(".")
    for i in range(1, len(parts)):
        parent = ".".join(parts[:i])
        if parent not in sys.modules:
            _stub(parent)


def _stub_tree(dotted, **attrs):
    _ensure_parent(dotted)
    m = _stub(dotted, **attrs)
    parent = ".".join(dotted.split(".")[:-1])
    if parent and parent in sys.modules:
        setattr(sys.modules[parent], dotted.split(".")[-1], m)
    return m


# ── cv2 ──────────────────────────────────────────────────────────────────────
if "cv2" not in sys.modules:
    cv2 = _stub("cv2")
    cv2.VideoCapture          = MagicMock(return_value=MagicMock(isOpened=lambda: True, release=lambda: None))
    cv2.imencode              = MagicMock(return_value=(True, MagicMock(tobytes=lambda: b"")))
    cv2.imdecode              = MagicMock(return_value=MagicMock())
    cv2.resize                = MagicMock(return_value=MagicMock())
    cv2.cvtColor              = MagicMock(return_value=MagicMock())
    cv2.rectangle             = MagicMock()
    cv2.putText               = MagicMock()
    cv2.imwrite               = MagicMock(return_value=True)
    cv2.IMREAD_COLOR          = 1
    cv2.IMWRITE_JPEG_QUALITY  = 95
    cv2.CAP_PROP_FRAME_WIDTH  = 3
    cv2.CAP_PROP_FRAME_HEIGHT = 4
    cv2.COLOR_BGR2RGB         = 4

# ── face_recognition ─────────────────────────────────────────────────────────
if "face_recognition" not in sys.modules:
    import numpy as np
    fr = _stub("face_recognition")
    fr.load_image_file = MagicMock(return_value=np.zeros((100, 100, 3), dtype=np.uint8))
    fr.face_locations  = MagicMock(return_value=[(10, 90, 90, 10)])
    fr.face_encodings  = MagicMock(return_value=[np.zeros(128)])
    fr.compare_faces   = MagicMock(return_value=[True])
    fr.face_distance   = MagicMock(return_value=np.array([0.4]))

# ── pyttsx3 ──────────────────────────────────────────────────────────────────
if "pyttsx3" not in sys.modules:
    px = _stub("pyttsx3")
    _engine = MagicMock()
    _engine.setProperty = MagicMock()
    _engine.say         = MagicMock()
    _engine.runAndWait  = MagicMock()
    px.init = MagicMock(return_value=_engine)

# ── vosk ─────────────────────────────────────────────────────────────────────
if "vosk" not in sys.modules:
    vosk = _stub("vosk")
    vosk.Model           = MagicMock()
    vosk.KaldiRecognizer = MagicMock()
    vosk.SetLogLevel     = MagicMock()

# ── pyaudio ──────────────────────────────────────────────────────────────────
if "pyaudio" not in sys.modules:
    pa = _stub("pyaudio")
    pa.PyAudio = MagicMock(return_value=MagicMock())
    pa.paInt16 = 8

# ── gspread (full package tree) ───────────────────────────────────────────────
for _g in ["gspread", "gspread.utils", "gspread.exceptions",
           "gspread.models", "gspread.auth", "gspread.client"]:
    if _g not in sys.modules:
        _stub_tree(_g)
sys.modules["gspread"].authorize   = MagicMock()
sys.modules["gspread"].Client      = MagicMock()
sys.modules["gspread"].Worksheet   = MagicMock
sys.modules["gspread"].Spreadsheet = MagicMock

# ── google.* ─────────────────────────────────────────────────────────────────
for _pkg in [
    "google", "google.auth", "google.auth.transport",
    "google.auth.transport.requests", "google.auth.exceptions",
    "google.oauth2", "google.oauth2.credentials",
    "google.oauth2.service_account",
    "google_auth_oauthlib", "google_auth_oauthlib.flow",
    "googleapiclient", "googleapiclient.discovery",
    "googleapiclient.errors", "googleapiclient.http",
]:
    if _pkg not in sys.modules:
        _stub_tree(_pkg)

sys.modules["google_auth_oauthlib.flow"].InstalledAppFlow = MagicMock()
sys.modules["google_auth_oauthlib.flow"].Flow             = MagicMock()
sys.modules["googleapiclient.discovery"].build            = MagicMock(return_value=MagicMock())
sys.modules["google.auth.transport.requests"].Request     = MagicMock()
sys.modules["google.oauth2.credentials"].Credentials      = MagicMock()
sys.modules["googleapiclient.http"].MediaFileUpload       = MagicMock()
sys.modules["googleapiclient.http"].MediaIoBaseDownload   = MagicMock()

# ── flask / flask_session / flask_cors ───────────────────────────────────────
for _fl in ["flask", "flask_session", "flask_cors"]:
    if _fl not in sys.modules:
        m = _stub(_fl)
        m.Flask    = MagicMock()
        m.request  = MagicMock()
        m.jsonify  = MagicMock(return_value=MagicMock())
        m.redirect = MagicMock()
        m.session  = {}
        m.CORS     = MagicMock()
        m.Session  = MagicMock()

# ── dotenv ────────────────────────────────────────────────────────────────────
if "dotenv" not in sys.modules:
    denv = _stub("dotenv")
    denv.load_dotenv = MagicMock()
    denv.set_key     = MagicMock()
