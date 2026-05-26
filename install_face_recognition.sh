#!/usr/bin/env bash
# ============================================================================
# Install face_recognition (optional, for the "known person" feature).
#
# face_recognition pulls dlib, which needs cmake + a C++ toolchain. On CPUs
# without AVX it has to compile from source (~5-10 min).
#
# Usage: ./install_face_recognition.sh
#
# This script assumes the project venv lives at ./venv/. If you keep the venv
# elsewhere, activate it first and run `pip install face_recognition` directly.
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -x "$SCRIPT_DIR/venv/bin/pip" ]; then
    PIP="$SCRIPT_DIR/venv/bin/pip"
    PYTHON="$SCRIPT_DIR/venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/bin/pip" ]; then
    PIP="$SCRIPT_DIR/.venv/bin/pip"
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    echo "ERROR: no venv found at ./venv or ./.venv." >&2
    echo "Create one with: python3 -m venv venv && ./venv/bin/pip install -r backend/requirements.txt" >&2
    exit 1
fi

log() { echo "[$(date '+%H:%M:%S')] $*"; }

log "Ensuring cmake is available..."
if ! "$PIP" show cmake >/dev/null 2>&1; then
    log "Installing cmake via pip..."
    "$PIP" install cmake
fi

log "Installing face_recognition (compiles dlib from source — this can take 5-10 min)..."
START_TIME=$(date +%s)
"$PIP" install face_recognition
DURATION=$(( $(date +%s) - START_TIME ))

log "Verifying import..."
if "$PYTHON" -c "import face_recognition; print('OK')"; then
    echo ""
    echo "========================================="
    echo "  face_recognition installed (${DURATION}s)"
    echo "  Vision name recognition is now available."
    echo "========================================="
else
    echo "ERROR: face_recognition installed but failed to import." >&2
    exit 1
fi
