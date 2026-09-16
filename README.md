# 🎓 Single Shot AAS — AI Attendance System

> **Automatic classroom attendance using a single photo and face recognition.**
> One shot → all faces detected → Google Sheets updated → students emailed.
> Built with Python · Flask · face_recognition · Google Sheets & Drive API · Vosk.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-yellow.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.x-black.svg)](https://flask.palletsprojects.com)

---

## ✨ Features

| Feature | Description |
|---|---|
| 📷 **Single-Shot Recognition** | Detect all faces in one classroom photo simultaneously |
| 🎥 **IP & USB Camera** | RTSP ceiling mount, USB webcam, or faculty phone upload |
| 🧠 **3-Angle Enrollment** | Front / Left / Right per student for robust recognition |
| 🏫 **Multi-Section Support** | Each classroom section has its own camera + Google Sheet |
| 📊 **Google Sheets Sync** | Auto-marks present / absent / late with date columns |
| ☁️ **Google Drive Backup** | Captured images and institution config stored on Drive |
| 📧 **Email Notifications** | Attendance report sent to each student via Gmail |
| 🌐 **Web Dashboard** | Full SPA: setup wizard, enrollment, live log, reports |
| 🔊 **Voice Trigger** | Say "take attendance" → camera fires (offline, Vosk) |
| 🖥️ **Headless Pi Mode** | Runs 24/7 on Raspberry Pi 4 without a monitor |
| 🔐 **Google OAuth2** | Faculty login via Google account — no passwords stored |
| 🐳 **Docker Ready** | Multi-stage Dockerfile for reproducible deployment |

---

## 🗂️ Repository Map

```
├── docs/                               ← Architecture & research documentation
│   ├── Single_Shot_2AS_Technical_Paper.md ← Comprehensive architectural whitepaper
│   └── Pixels Required for AI Facial Recognition (1).md ← IEC/ISO standards specifications
│
├── src/                                ← Python package root (PYTHONPATH=src)
│   └── aas/                            ← Top-level package
│       ├── core/
│       │   ├── config.py               ← All env vars, paths, constants
│       │   ├── retry.py                ← Exponential backoff retry for transient API errors
│       │   └── safe_pickle.py          ← Restricted unpickler blocking arbitrary code execution
│       │
│       ├── recognition/
│       │   ├── __init__.py             ← Public exports (engine, detectors, metrics)
│       │   ├── engine.py               ← Recognition pipeline + quality gating + 3-state annotations
│       │   ├── detectors.py            ← Multi-scale detector (OpenCV YuNet + dlib fallback)
│       │   └── metrics.py              ← Sharpness, IPD, and adaptive scale calculators
│       │
│       ├── enrollment/
│       │   └── enroll.py               ← CLI 3-angle enrollment flow & quality validator
│       │
│       ├── capture/
│       │   ├── capture.py              ← RTSP / webcam image capture (thread-locked)
│       │   └── camera_registry.py      ← cameras.json CRUD (thread-safe per-section cameras)
│       │
│       ├── attendance/
│       │   └── spreadsheet.py          ← Google Sheets atomic batch read/write
│       │
│       ├── integrations/
│       │   └── google/
│       │       ├── oauth.py            ← Google OAuth2 token flow & CSRF state validation
│       │       └── drive_manager.py    ← Sanitized Drive folder + Sheets creation
│       │
│       ├── notifications/
│       │   ├── emailing.py             ← Gmail SMTP attendance emails
│       │   └── tts.py                  ← pyttsx3 / espeak TTS announcement
│       │
│       ├── voice/
│       │   └── voice_trigger.py        ← Vosk offline trigger with cooldown guard
│       │
│       └── web/                        ← Flask web application
│           ├── app.py                  ← Flask app (batch attendance, secure tokens, stream auth)
│           ├── static/
│           │   └── style.css           ← Dashboard styles
│           └── templates/
│               ├── splash.html
│               ├── login.html
│               ├── index.html          ← Main SPA dashboard
│               └── setup/
│                   ├── step1.html
│                   ├── step2.html
│                   ├── step3.html
│                   └── complete.html
│
├── tests/
│   ├── conftest.py                     ← Shared pytest fixtures
│   ├── unit/                           ← 100+ unit tests
│   │   ├── test_config.py
│   │   ├── test_recognition.py
│   │   ├── test_recognition_gender.py
│   │   ├── test_recognition_standards.py ← IEC/ISO standards tests
│   │   ├── test_safe_pickle.py         ← Pickle exploit defense tests
│   │   ├── test_spreadsheet.py         ← Atomic batch update tests
│   │   ├── test_camera_registry.py
│   │   ├── test_drive_manager.py
│   │   ├── test_oauth.py
│   │   ├── test_emailing.py
│   │   └── test_tts.py
│   └── integration/
│       └── test_web_routes.py          ← Flask route integration tests
│
├── main.py                             ← CLI entry point (--web / --voice / --enroll)
├── config/
│   ├── cameras.json                    ← Camera registry (gitignored after setup)
│   └── institution.json               ← Institution config (gitignored after setup)
├── data/                               ← Runtime data (gitignored)
│   ├── known_face_photos/
│   ├── known_face_encodings/
│   └── captured/
├── android/
│   └── Attendance_app.aia             ← MIT App Inventor companion app
├── .env.example                        ← Template — copy to .env and fill in secrets
├── pyproject.toml                      ← Ruff, Black, isort, pytest config
├── requirements.txt                    ← Runtime dependencies
├── requirements-dev.txt               ← Dev/test dependencies
├── Dockerfile                          ← Multi-stage Docker build
├── docker-compose.yml
├── attendance.service                  ← systemd service for Raspberry Pi
├── setup.sh                            ← One-command setup script
├── Makefile                            ← dev / test / lint shortcuts
└── .github/workflows/ci.yml           ← GitHub Actions CI
```

---

## ⚙️ Functional Flow

```
Faculty opens http://<host>:5000
        │
        ▼
  [Splash] → [Google OAuth2 Login]
        │
        ├─ New user ──→ [Setup Wizard]
        │                   Step 1: Institution name / city / state
        │                   Step 2: Create sections → Drive folders + Google Sheets
        │                   Step 3: Assign RTSP / webcam URLs to each camera
        │                   Complete ✓
        │
        └─ Returning user ──→ [Dashboard]
                │
                ├── [Enroll Student]
                │       Webcam: capture Front → Left → Right angles
                │       Upload: 1-3 photos drag-and-drop
                │       Result: .pkl encoding saved + row added to Google Sheet
                │
                ├── [Take Attendance]
                │       Select camera → POST /take-attendance
                │       │
                │       ├─ capture.py: capture_single_shot(camera_id)
                │       │       RTSP → cv2.VideoCapture → save JPEG to data/captured/
                │       │
                │       ├─ engine.py: run_recognition(image_path)
                │       │       Load known encodings from data/known_face_encodings/
                │       │       face_recognition.face_locations() → encode → compare
                │       │       Returns {present: [...], boys_count, girls_count, ...}
                │       │
                │       ├─ spreadsheet.py: mark_all_absent() → write_to_sheet(name)
                │       │       Marks all absent first, then writes "present"/"late"
                │       │       per recognized student in today's date column
                │       │
                │       ├─ tts.py: announce_attendance(boys, girls, total)
                │       │       Non-blocking thread → pyttsx3 / espeak speaks result
                │       │
                │       └─ engine.py: annotate_image()
                │               Draws bounding boxes + names → saves annotated JPEG
                │
                ├── [Voice Mode]  python main.py --voice
                │       Vosk offline model listens on microphone
                │       Phrase match → triggers same attendance pipeline above
                │
                └── [Reports / Settings]
                        View today's attendance, download, adjust tolerances
```

---

## 🖥️ Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Computer | Any Python 3.10 machine | Raspberry Pi 4 (4 GB RAM) |
| Camera | USB webcam | RTSP IP camera (ceiling-mounted) |
| Storage | 4 GB free | 16 GB SD card (Pi) |
| OS | Ubuntu / Debian / macOS | Raspberry Pi OS 64-bit |

---

## ⚡ Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/Dastagiri-K-Coder/Single-Shot-AAS.git
cd "Single-Shot-AAS"
```

### 2. Create and activate virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note**: `dlib` and `face_recognition` take 10–20 min to compile on first install.
> Use the Docker image to skip this.

### 4. Copy environment template

```bash
cp .env.example .env
```

Edit `.env` with your values (see [Environment Variables](#-environment-variables)).

### 5. Start the web dashboard

```bash
PYTHONPATH=src python main.py --web
```

Open **http://localhost:5000** → complete the setup wizard → enroll students → take attendance.

---

## 🔑 Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
# ── Google OAuth2 ──────────────────────────────────────────────
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
OAUTH_REDIRECT_URI=http://localhost:5000/auth/google/callback

# ── Camera ─────────────────────────────────────────────────────
IP_CAMERA_URL=                        # Leave blank for webcam
WEBCAM_INDEX=0

# ── Recognition Tuning ─────────────────────────────────────────
RECOGNITION_TOLERANCE=0.55            # 0.3 strict → 0.7 lenient
RECOGNITION_SCALE=0.25                # 0.1 fast → 1.0 accurate
FACE_DETECTION_MODEL=hog              # "hog" (fast) or "cnn" (GPU)

# ── Attendance Rules ───────────────────────────────────────────
MAX_IN_TIME=16:00:00                  # Students after this = "late"

# ── Email Notifications ────────────────────────────────────────
GMAIL_SENDER=yourname@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

# ── Voice Trigger ──────────────────────────────────────────────
VOICE_TRIGGER_PHRASE=take attendance

# ── Web Server ─────────────────────────────────────────────────
WEB_HOST=0.0.0.0
WEB_PORT=5000
FLASK_SECRET_KEY=change-me-to-a-random-string
```

---

## ☁️ Google Cloud Setup

> Skip if you only want local face recognition without Sheets sync.

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → **New Project**
2. Enable: **Google Sheets API**, **Google Drive API**, **Google OAuth2 API**
3. **APIs & Services → Credentials → Create OAuth 2.0 Client ID** (Web Application)
4. Add `http://localhost:5000/auth/google/callback` to Authorized redirect URIs
5. Download the client JSON → copy `client_id` and `client_secret` into `.env`

---

## 📧 Gmail App Password Setup

1. Enable **2-Step Verification** on your Gmail account
2. **myaccount.google.com** → Security → App Passwords → App name: "Attendance"
3. Copy the 16-character code → paste as `GMAIL_APP_PASSWORD` in `.env`

---

## 🐳 Docker Deployment

```bash
# Build image (first build compiles dlib — ~20 min, cached after that)
docker build -t single-shot-aas .

# Run
docker run -p 5000:5000 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config \
  single-shot-aas
```

---

## 🥧 Raspberry Pi 4 Deployment

```bash
# 1. Install pyenv + Python 3.10
curl https://pyenv.run | bash
pyenv install 3.10.20
pyenv local 3.10.20

# 2. Clone + install
git clone https://github.com/Dastagiri-K-Coder/Single-Shot-AAS.git
cd Single-Shot-AAS
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Install as systemd service (auto-start on boot)
sudo cp attendance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable attendance
sudo systemctl start attendance

# Check logs
journalctl -u attendance -f
```

Access from any device on the same WiFi: `http://<Pi-IP>:5000`

---

## 🎤 Voice Mode (Optional)

```bash
# 1. Download Vosk model
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip -d vosk-model-small-en-us

# 2. Run
PYTHONPATH=src python main.py --voice
# Say "take attendance" → camera fires → recognition runs
```

---

## 🖥️ CLI Reference

```bash
PYTHONPATH=src python main.py --web              # Web dashboard
PYTHONPATH=src python main.py                    # Take one attendance shot (CLI)
PYTHONPATH=src python main.py --enroll "Name"   # 3-angle webcam enrollment
PYTHONPATH=src python main.py --voice            # Voice trigger mode
PYTHONPATH=src python main.py --test-mic         # Test microphone
PYTHONPATH=src python main.py --preview          # Live camera preview
PYTHONPATH=src python main.py /path/to/img.jpg  # Process existing photo
```

---

## 🧪 Running Tests

```bash
pip install -r requirements-dev.txt
PYTHONPATH=src python -m pytest tests/ -v --tb=short
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| `No face detected` | Improve lighting; increase `RECOGNITION_SCALE` to 0.5 |
| `Cannot open camera` | Check `WEBCAM_INDEX` or `IP_CAMERA_URL` in `.env` |
| `ModuleNotFoundError: aas` | Set `PYTHONPATH=src` before running |
| `No face encodings loaded` | Enroll at least one student first |
| Recognition is slow | Reduce `RECOGNITION_SCALE` (0.1) or use `hog` model |
| Wrong students recognized | Lower `RECOGNITION_TOLERANCE` (try 0.45) |
| Pi crashes on camera open | Add `CAMERA_WARMUP_FRAMES=20` in `.env` |
| Email not sending | Use a 16-char Gmail App Password, not your account password |
| OAuth redirect error | Add `http://localhost:5000/auth/google/callback` to Google Console |

---

## 📐 Architecture

```
Browser (SPA — index.html)
    │  HTTP + JSON
    ▼
aas/web/app.py  (Flask — 15+ routes)
    │
    ├── /take-attendance   → capture.py → engine.py → spreadsheet.py → tts.py
    ├── /upload-photo      → engine.py  → spreadsheet.py
    ├── /api/enroll/*      → face_recognition encode → .pkl → spreadsheet
    ├── /api/cameras/*     → camera_registry.py (cameras.json CRUD)
    ├── /api/attendance/*  → spreadsheet.py (today's records)
    ├── /api/settings      → read / write .env
    ├── /api/camera/stream → MJPEG live stream (cv2)
    ├── /auth/google/*     → oauth.py (OAuth2 flow)
    └── /setup/*           → drive_manager.py (Drive + Sheets setup)

aas/core/config.py         — single source of truth for all paths + env vars
```

---

## 📄 License

**MIT License** — Copyright © 2026 **KUMMARAPALLI DASTAGIRI** ([@Dastagiri-K-Coder](https://github.com/Dastagiri-K-Coder))

Anyone may use, modify, distribute, merge, publish, or sell this software **completely free of charge**.
The only condition: **the original copyright notice must be kept** in all copies or substantial portions of the software.

See [LICENSE](LICENSE) for the full text.
