#!/usr/bin/env bash
# =============================================================================
#  setup.sh — One-click development setup for AI Attendance System
#
#  Usage:
#      chmod +x setup.sh
#      ./setup.sh               # full setup (default)
#      ./setup.sh --no-vosk     # skip large Vosk model download
#      ./setup.sh --ci          # CI-safe mode (no interactive prompts)
# =============================================================================

set -euo pipefail

# ── Colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN}[OK]${RESET}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERR]${RESET}  $*"; }
step()    { echo -e "\n${BOLD}══ $* ══${RESET}"; }

# ── Parse flags ───────────────────────────────────────────────────────────────
SKIP_VOSK=false
CI_MODE=false
for arg in "$@"; do
    case $arg in
        --no-vosk) SKIP_VOSK=true ;;
        --ci)      CI_MODE=true   ;;
    esac
done

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$ROOT_DIR/face recognition source code"

# ── Banner ─────────────────────────────────────────────────────────────────────
echo -e "${BOLD}"
echo "╔═══════════════════════════════════════════════════╗"
echo "║    🎓  AI Attendance System — Dev Setup            ║"
echo "╚═══════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ── Step 1: Check OS prerequisites ───────────────────────────────────────────
step "Step 1/7: Checking system prerequisites"

OS="$(uname -s)"
if [[ "$OS" == "Linux" ]]; then
    info "Detected Linux — checking apt packages ..."
    MISSING_APT=()
    for pkg in cmake libboost-all-dev portaudio19-dev git; do
        dpkg -s "$pkg" &>/dev/null || MISSING_APT+=("$pkg")
    done
    if [[ ${#MISSING_APT[@]} -gt 0 ]]; then
        warn "Missing apt packages: ${MISSING_APT[*]}"
        if [[ "$CI_MODE" == false ]]; then
            read -r -p "Install them now with sudo? [y/N] " ans
            [[ "$ans" =~ ^[Yy]$ ]] && sudo apt-get install -y "${MISSING_APT[@]}"
        else
            warn "CI mode: skipping apt install. Ensure packages are pre-installed."
        fi
    else
        success "All apt prerequisites present."
    fi
elif [[ "$OS" == "Darwin" ]]; then
    command -v brew &>/dev/null || { error "Homebrew not found. Install from https://brew.sh"; exit 1; }
    info "Detected macOS — checking brew packages ..."
    brew install cmake boost portaudio 2>/dev/null && success "brew packages OK"
else
    warn "Unsupported OS: $OS. Continuing anyway ..."
fi

# ── Step 2: Python version check ─────────────────────────────────────────────
step "Step 2/7: Python version"

REQUIRED="3.10"
PYTHON_BIN=""
for py in python3.10 python3 python; do
    if command -v "$py" &>/dev/null; then
        ver=$("$py" --version 2>&1 | awk '{print $2}')
        major_minor="${ver%.*}"
        if [[ "$major_minor" == "$REQUIRED" ]]; then
            PYTHON_BIN="$py"
            success "Found Python $ver at $(command -v "$py")"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    error "Python $REQUIRED not found. Install via pyenv:"
    echo "  curl https://pyenv.run | bash"
    echo "  pyenv install 3.10.20 && pyenv local 3.10.20"
    exit 1
fi

# ── Step 3: Virtual environment ───────────────────────────────────────────────
step "Step 3/7: Virtual environment"

VENV_DIR="$ROOT_DIR/.venv"
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at .venv ..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    success "Virtual environment created."
else
    success "Virtual environment already exists."
fi

# Activate
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
success "Activated: $(python --version) at $(which python)"

# ── Step 4: Install Python dependencies ───────────────────────────────────────
step "Step 4/7: Installing Python dependencies"

info "Installing from face recognition source code/requirements.txt ..."
info "(dlib compilation may take 10–20 min on first install)"
pip install --upgrade pip --quiet
pip install -r "$SRC_DIR/requirements.txt"
success "Python dependencies installed."

# Install dev dependencies
DEV_REQS="$ROOT_DIR/requirements-dev.txt"
if [[ -f "$DEV_REQS" ]]; then
    info "Installing dev dependencies ..."
    pip install -r "$DEV_REQS"
    success "Dev dependencies installed."
fi

# ── Step 5: Environment file ──────────────────────────────────────────────────
step "Step 5/7: Environment configuration"

ENV_FILE="$SRC_DIR/.env"
ENV_EXAMPLE="$SRC_DIR/.env.example"

if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -f "$ENV_EXAMPLE" ]]; then
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        success ".env created from .env.example"
        warn "ACTION REQUIRED: Edit $ENV_FILE with your real values before running."
    else
        error ".env.example not found — cannot create .env"
    fi
else
    # Validate that all keys in .env.example exist in .env
    info "Validating .env against .env.example ..."
    MISSING_KEYS=()
    while IFS= read -r line; do
        [[ "$line" =~ ^#.*$ || -z "$line" ]] && continue
        key="${line%%=*}"
        grep -q "^${key}=" "$ENV_FILE" || MISSING_KEYS+=("$key")
    done < "$ENV_EXAMPLE"

    if [[ ${#MISSING_KEYS[@]} -gt 0 ]]; then
        warn "Your .env is missing keys from .env.example:"
        for k in "${MISSING_KEYS[@]}"; do echo "    ❌  $k"; done
    else
        success ".env is complete — all required keys present."
    fi
fi

# ── Step 6: Pre-commit hooks ──────────────────────────────────────────────────
step "Step 6/7: Git hooks (pre-commit)"

if command -v pre-commit &>/dev/null || pip show pre-commit &>/dev/null 2>&1; then
    if [[ -d "$ROOT_DIR/.git" ]]; then
        info "Installing pre-commit hooks ..."
        cd "$ROOT_DIR"
        pre-commit install
        pre-commit install --hook-type commit-msg
        success "Pre-commit hooks installed."
    else
        warn "Not a git repository — skipping pre-commit install."
    fi
else
    warn "pre-commit not found — run: pip install pre-commit && pre-commit install"
fi

# ── Step 7: Vosk model download ───────────────────────────────────────────────
step "Step 7/7: Vosk voice model"

VOSK_DIR="$ROOT_DIR/vosk-model-small-en-us"
VOSK_ZIP="$ROOT_DIR/vosk-model-small-en-us-0.15.zip"
VOSK_URL="https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"

if [[ -d "$VOSK_DIR" ]]; then
    success "Vosk model already present at $VOSK_DIR"
elif [[ "$SKIP_VOSK" == true ]]; then
    warn "Skipping Vosk model download (--no-vosk). Voice mode will not work."
else
    if [[ "$CI_MODE" == false ]]; then
        read -r -p "Download Vosk voice model (~50 MB)? [Y/n] " ans
        ans="${ans:-Y}"
    else
        ans="N"
        warn "CI mode: skipping Vosk model download."
    fi

    if [[ "$ans" =~ ^[Yy]$ ]]; then
        info "Downloading Vosk model ..."
        wget -q --show-progress "$VOSK_URL" -O "$VOSK_ZIP"
        info "Extracting ..."
        unzip -q "$VOSK_ZIP" -d "$ROOT_DIR"
        mv "$ROOT_DIR/vosk-model-small-en-us-0.15" "$VOSK_DIR" 2>/dev/null || true
        rm -f "$VOSK_ZIP"
        success "Vosk model ready at $VOSK_DIR"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "╔═══════════════════════════════════════════════════╗"
echo "║    ✅  Setup complete!                             ║"
echo "╚═══════════════════════════════════════════════════╝"
echo -e "${RESET}"
echo "  Next steps:"
echo "  1. Edit: face recognition source code/.env"
echo "  2. Add:  face recognition source code/credentials.json  (Google Cloud)"
echo "  3. Run:  source .venv/bin/activate"
echo "  4. Run:  cd 'face recognition source code' && python main.py --web"
echo "  5. Open: http://localhost:5000"
echo ""
