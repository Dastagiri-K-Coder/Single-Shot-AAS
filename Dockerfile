# syntax=docker/dockerfile:1
# =============================================================================
#  Dockerfile — AI Attendance System
#
#  Multi-stage build:
#    Stage 1 (builder): compile dlib + face_recognition (20 min, cached)
#    Stage 2 (runtime): lean runtime image without build tools
#
#  Build:
#    docker build -t attendance-system:latest .
#
#  Run (web mode):
#    docker run -p 5000:5000 \
#      --env-file .env \
#      -v $(pwd)/data:/app/data \
#      -v $(pwd)/config:/app/config \
#      -v $(pwd)/credentials.json:/app/credentials.json \
#      attendance-system:latest
# =============================================================================

# ── Stage 1: Builder (compile dlib) ──────────────────────────────────────────
FROM python:3.10-slim-bullseye AS builder

# System build dependencies for dlib + OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    g++ \
    libboost-all-dev \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgstreamer-plugins-base1.0-dev \
    ffmpeg \
    portaudio19-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

COPY requirements.txt ./requirements.txt

# Build wheels (dlib compile happens here — cached unless requirements.txt changes)
RUN pip install --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.10-slim-bullseye AS runtime

LABEL org.opencontainers.image.title="AI Attendance System"
LABEL org.opencontainers.image.description="Face-recognition classroom attendance"
LABEL org.opencontainers.image.version="2.0"

# Runtime system libraries (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libboost-python1.74.0 \
    libopenblas0 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1-mesa-glx \
    portaudio19-dev \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install pre-built wheels from builder stage
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl \
    && rm -rf /wheels

# ── App code ──────────────────────────────────────────────────────────────────
WORKDIR /app

# Copy source code
COPY src/ ./src/
COPY main.py ./main.py
COPY config/ ./config/

# Create data directories (mounted as volumes in production)
RUN mkdir -p \
    /app/data/known_face_photos \
    /app/data/known_face_encodings \
    /app/data/captured

# Symlink data dirs so config.py paths resolve correctly
# config.py uses ROOT_DIR = parent of src/ = /app
# PHOTO_FOLDER      = /app/known face photos  →  we rename to underscores
# Override via environment variables in config.py if needed

# ── Runtime user (non-root) ───────────────────────────────────────────────────
RUN useradd -m -u 1001 appuser && \
    chown -R appuser:appuser /app
USER appuser

# ── Environment defaults ──────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=5000 \
    FACE_DETECTION_MODEL=hog \
    RECOGNITION_SCALE=0.25 \
    RECOGNITION_TOLERANCE=0.55

EXPOSE 5000

# ── Health check ─────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:5000/api/status || exit 1

# ── Entry point ───────────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app/src
WORKDIR /app
CMD ["python", "main.py", "--web"]
