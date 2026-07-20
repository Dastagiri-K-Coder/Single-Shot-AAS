# 🎓 AI Attendance System — Single Shot 2A

> **Automatic classroom attendance using face recognition.**
> One photo → instantly marks all present students in Google Sheets and sends email notifications.

---

## ✨ Features

| Feature | Description |
|---|---|
| 📷 **Single-Shot Recognition** | Detect all faces in one classroom photo simultaneously |
| 🎥 **IP & USB Camera** | RTSP ceiling mount, laptop webcam, or phone upload |
| 🧠 **3-Angle Enrollment** | Front / Left / Right for robust recognition |
| 📊 **Google Sheets Sync** | Auto-marks present/absent/late with timestamps |
| 📧 **Email Notifications** | Sends attendance reports via Gmail |
| 🌐 **Web Dashboard** | Full SPA with enrollment wizard, live log, reports |
| 🔊 **Voice Trigger** | Say "take attendance" → camera fires (offline, Vosk) |
| 🖥️ **Headless Pi Mode** | Runs 24/7 on Raspberry Pi 4 without a monitor |

---

## 🗂️ Project Structure

```
Single Shot 2A/Kalyan-Koppula/
├── face recognition source code/
│   ├── config.py               ← All config (env vars, paths)
│   ├── capture.py              ← Camera capture (IP + webcam)
│   ├── recognition.py          ← Face recognition engine
│   ├── enroll.py               ← CLI enrollment (3-angle)
│   ├── spreadsheet.py          ← Google Sheets sync
│   ├── emailing.py             ← Email notifications
│   ├── voice_trigger.py        ← Vosk offline voice commands
│   ├── main.py                 ← CLI entry point (--web, --voice, --enroll)
│   ├── .env                    ← Your secrets (never commit this!)
│   ├── .env.example            ← Template to copy from
│   ├── credentials.json        ← Google Cloud service account (you add this)
│   └── web_app/
│       ├── app.py              ← Flask backend (15 routes)
│       ├── templates/
│       │   └── index.html      ← Full SPA frontend
│       └── static/
│           └── style.css       ← Dashboard styles
├── known face photos/          ← Auto-created: student reference photos
├── known face encodings/       ← Auto-created: .pkl face encodings
├── captured/                   ← Auto-created: captured & annotated images
├── attendance.service          ← systemd service for Pi auto-start
└── .python-version             ← Python 3.10.20 (pyenv)
```

---

## 🖥️ Hardware Requirements

| Component | Minimum | Recommended |
|---|---|---|
| Computer | Any Python 3.10 machine | Raspberry Pi 4 (4 GB RAM) |
| Camera | Laptop webcam | RTSP IP camera (ceiling-mounted) |
| Storage | 4 GB free | 16 GB SD card (Pi) |
| OS | Ubuntu / Debian / macOS | Raspberry Pi OS (64-bit) |

---

## ⚡ Quick Start (Laptop / Desktop)

### 1. Clone & enter the directory

```bash
cd "/home/giri/Projects/Single Shot 2A/Kalyan-Koppula"
```

### 2. Activate the virtual environment

```bash
source .venv/bin/activate
```

### 3. Copy environment template

```bash
cp "face recognition source code/.env.example" "face recognition source code/.env"
```

Edit `.env` with your values (see [Environment Variables](#-environment-variables) below).

### 4. Start the web dashboard

```bash
cd "face recognition source code"
python main.py --web
```

Open **http://localhost:5000** in your browser.

### 5. Enroll your first student

Either via the web dashboard → **Enroll Student** section, or CLI:

```bash
python main.py --enroll "John Doe"
# Webcam opens → capture Front, Left, Right angles
```

### 6. Take attendance

Web dashboard → **Take Attendance** → **⚡ Take Attendance Now**

---

## 🔑 Environment Variables

Edit `face recognition source code/.env`:

```env
# ── Google Sheets ──────────────────────────────────────────────
SHEET_NAME=Face recognition          # Name of your Google Sheet

# ── Camera ─────────────────────────────────────────────────────
IP_CAMERA_URL=                        # Leave blank for webcam
# IP_CAMERA_URL=rtsp://admin:pass@192.168.1.50:554/stream
WEBCAM_INDEX=0                        # 0 = default webcam

# ── Recognition Tuning ─────────────────────────────────────────
RECOGNITION_TOLERANCE=0.55            # 0.3 strict → 0.7 lenient
RECOGNITION_SCALE=0.25               # 0.1 fast → 1.0 accurate
FACE_DETECTION_MODEL=hog              # "hog" (fast) or "cnn" (GPU)

# ── Attendance Rules ───────────────────────────────────────────
MAX_IN_TIME=16:00:00                  # Students after this = "late"

# ── Email Notifications ────────────────────────────────────────
GMAIL_USER=yourname@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx

# ── Voice Trigger ──────────────────────────────────────────────
VOICE_TRIGGER_PHRASE=take attendance

# ── Web Server ─────────────────────────────────────────────────
WEB_HOST=0.0.0.0
WEB_PORT=5000
```

---

## ☁️ Google Cloud Setup (for Sheets Sync)

> **Skip this if you only want local face recognition without Sheet sync.**

### Step 1 — Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. **New Project** → give it a name (e.g. "Attendance System")
3. Enable APIs:
   - **Google Sheets API**
   - **Google Drive API**

### Step 2 — Create a Service Account

1. **IAM & Admin** → **Service Accounts** → **Create Service Account**
2. Give it a name (e.g. "attendance-bot"), click **Create and Continue**
3. **Keys** tab → **Add Key** → **JSON** → Download
4. Save the downloaded file as `credentials.json` inside `face recognition source code/`

### Step 3 — Share your Google Sheet

1. Open your Google Sheet (name must match `SHEET_NAME` in `.env`)
2. **Share** → paste the **service account email** (from `credentials.json`) → Editor

### Sheet Column Structure (auto-created)

```
Col A: Name  |  Col B: Email  |  Col C: PIN  |  Col D+: Dates (7/14/2026, ...)
```

---

## 📧 Gmail App Password Setup

1. Enable **2-Step Verification** on your Gmail account
2. Visit [myaccount.google.com](https://myaccount.google.com) → Security → App Passwords
3. App name: "Attendance System" → Generate
4. Copy the 16-character code → paste into `.env` as `GMAIL_APP_PASSWORD`

---

## 👤 Enrollment Guide

### Web Dashboard (recommended)

1. Open **http://localhost:5000** → **Enroll Student**
2. Enter student name and email
3. **Webcam tab**: Click **▶ Start Camera** → capture Front / Left / Right angles
4. Click **✅ Complete Enrollment**

### CLI (batch enrollment)

```bash
python main.py --enroll "Jane Smith"
# Webcam opens, captures 3 angles automatically
```

### Upload Photos (no webcam needed)

Dashboard → Enroll → **Upload Photos** tab → drag up to 3 photos → **Enroll Student**

---

## 🎤 Voice Mode Setup (Optional)

### 1. Download Vosk model

```bash
cd "/home/giri/Projects/Single Shot 2A/Kalyan-Koppula"
wget https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip
unzip vosk-model-small-en-us-0.15.zip -d vosk-model-small-en-us
```

### 2. Install dependencies

```bash
source .venv/bin/activate
pip install vosk sounddevice
```

### 3. Run voice mode

```bash
python main.py --voice
# Say "take attendance" → camera captures → recognition runs
```

---

## 🥧 Raspberry Pi 4 Deployment

### 1. Initial setup (on the Pi)

```bash
# Install pyenv + Python 3.10.20
curl https://pyenv.run | bash
pyenv install 3.10.20

# Clone / copy your project
cd "/home/giri/Projects/Single Shot 2A/Kalyan-Koppula"
python -m venv .venv
source .venv/bin/activate
pip install -r "face recognition source code/requirements.txt"
```

### 2. USB Webcam config

```env
WEBCAM_INDEX=0
CAMERA_WARMUP_FRAMES=20
FACE_DETECTION_MODEL=hog
```

### 3. Install as systemd service (auto-start on boot)

```bash
sudo cp attendance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable attendance
sudo systemctl start attendance

# Check logs
journalctl -u attendance -f
```

### 4. Access from any device on the same WiFi

Open a browser on your phone / laptop:
```
http://<Pi-IP-address>:5000
```

Find the Pi's IP with: `hostname -I`

---

## 🖥️ CLI Reference

```bash
# Web dashboard (recommended)
python main.py --web

# Take attendance from terminal
python main.py

# Enroll student via webcam
python main.py --enroll "Full Name"

# Voice trigger mode
python main.py --voice

# Test microphone
python main.py --test-mic

# IP camera preview
python main.py --preview
```

---

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| `No face detected` | Improve lighting; increase `RECOGNITION_SCALE` |
| `Cannot open camera` | Check `WEBCAM_INDEX` or `IP_CAMERA_URL` in `.env` |
| `credentials.json missing` | Face recognition still works; Sheets sync is disabled |
| `No face encodings loaded` | Enroll at least one student first |
| Recognition is slow | Reduce `RECOGNITION_SCALE` (e.g. 0.1) or set `FACE_DETECTION_MODEL=hog` |
| Wrong students recognized | Lower `RECOGNITION_TOLERANCE` (try 0.45) |
| Pi crashes on camera open | Add `CAMERA_WARMUP_FRAMES=20` in `.env` |
| Web dashboard not loading | Run `python main.py --web` and check terminal for errors |
| Email not sending | Verify `GMAIL_APP_PASSWORD` is a 16-char App Password (not your login password) |

---

## 📐 Architecture

```
Browser (SPA)
    │  HTTP / JSON
    ▼
Flask app.py (15 routes)
    ├── /take-attendance  →  capture.py → recognition.py → spreadsheet.py
    ├── /api/enroll/*     →  face_recognition encode → .pkl save
    ├── /api/students     →  list .pkl files
    ├── /api/settings     →  read/write .env
    ├── /api/camera/stream → MJPEG stream
    └── /captured/<file>  →  serve annotated images
```

---

## 📄 License

Academic project — Kalyan Koppula. All rights reserved.
