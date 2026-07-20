#!/bin/bash
# setup.sh — One-shot setup script for Single Shot AAS v2
# Usage: bash setup.sh
set -e

echo "═══════════════════════════════════════════════════════════"
echo "  Single Shot AAS — v2 Setup"
echo "═══════════════════════════════════════════════════════════"

# ── 1. Python version check ───────────────────────────────────────────────────
echo ""
echo "► Checking Python version..."
python3 --version

# ── 2. Virtual environment ───────────────────────────────────────────────────
if [ ! -d "venv" ]; then
  echo ""
  echo "► Creating virtual environment..."
  python3 -m venv venv
fi

echo "► Activating virtual environment..."
source venv/bin/activate

# ── 3. Install dependencies ──────────────────────────────────────────────────
echo ""
echo "► Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# ── 4. System dependencies (pyttsx3 on Linux requires espeak) ────────────────
echo ""
echo "► Checking system TTS dependency (espeak-ng)..."
if ! command -v espeak-ng &>/dev/null && ! command -v espeak &>/dev/null; then
  echo "  espeak-ng not found. Installing..."
  if command -v apt-get &>/dev/null; then
    sudo apt-get install -y espeak-ng
  elif command -v dnf &>/dev/null; then
    sudo dnf install -y espeak-ng
  else
    echo "  [WARN] Cannot auto-install espeak-ng. TTS voice announcement may not work."
    echo "  Install manually: sudo apt-get install espeak-ng"
  fi
else
  echo "  ✓ espeak found."
fi

# ── 5. Create data directories ───────────────────────────────────────────────
echo ""
echo "► Creating required directories..."
mkdir -p "known face encodings" "captured" "photos"
echo "  ✓ Directories ready."

# ── 6. .env file ────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
  echo ""
  echo "► Creating .env from .env.example..."
  cp .env.example .env
  echo "  ✓ .env created. Edit it to set your configuration."
else
  echo ""
  echo "  ✓ .env already exists."
fi

# ── 7. OAuth credentials check ───────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
echo "  IMPORTANT: Google OAuth Setup"
echo "══════════════════════════════════════════════════════════"
echo ""
if [ -f "oauth_credentials.json" ]; then
  echo "  ✓ oauth_credentials.json found."
else
  echo "  ✗ oauth_credentials.json NOT found!"
  echo ""
  echo "  To use Google Drive sync, you must:"
  echo "  1. Go to https://console.cloud.google.com"
  echo "  2. Create a project → Enable: Google Drive API, Google Sheets API, Google OAuth2 API"
  echo "  3. OAuth & OpenID Connect → Create OAuth 2.0 Client ID (Desktop / Web App)"
  echo "  4. Download the JSON → save as: oauth_credentials.json"
  echo "     (place it in: face recognition source code/)"
  echo "  5. Add this Authorized redirect URI:"
  echo "     http://localhost:5000/auth/google/callback"
  echo ""
  echo "  The app will still run without this, but Google Drive sync and"
  echo "  the setup wizard will be disabled."
fi

# ── 8. Vosk model (voice trigger) ────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
echo "  OPTIONAL: Voice Trigger Model (Vosk)"
echo "══════════════════════════════════════════════════════════"
echo ""
if ls vosk-model-* 1>/dev/null 2>&1; then
  echo "  ✓ Vosk model directory found."
else
  echo "  ✗ No Vosk model found."
  echo "  To use voice trigger mode (--voice):"
  echo "  Download from: https://alphacephei.com/vosk/models"
  echo "  Recommended: vosk-model-small-en-us-0.15"
  echo "  Extract into: face recognition source code/"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Setup Complete!"
echo ""
echo "  To start the app:"
echo "    source venv/bin/activate"
echo "    python3 main.py --web"
echo ""
echo "  Then open: http://localhost:5000"
echo "  (You will be redirected to the Google login page)"
echo "═══════════════════════════════════════════════════════════"
