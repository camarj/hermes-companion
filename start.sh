#!/usr/bin/env bash
# hermes-companion — start script
# Usage: ./start.sh [port]
#
# Auto-detects HTTPS by looking for a cert pair in certs/. If you set
# COMPANION_CERT and COMPANION_KEY to explicit paths, those are used instead.
# Otherwise the server runs on plain HTTP (note: browsers require HTTPS for
# microphone access except on localhost).

set -e

PORT="${1:-8000}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Prefer the project's own venv if present, fall back to whatever `python3` is.
if [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
elif [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON="$(command -v python3 || command -v python)"
fi

if [ -z "$PYTHON" ]; then
    echo "ERROR: no python interpreter found. Install Python 3.11+ and try again." >&2
    exit 1
fi

# Stream prints to the log without buffering (helps when debugging long tool calls).
export PYTHONUNBUFFERED=1

# ── TLS auto-detect ─────────────────────────────────────────────────────────
SSL_ARGS=""
CERT_FILE="${COMPANION_CERT:-}"
KEY_FILE="${COMPANION_KEY:-}"

if [ -z "$CERT_FILE" ] || [ -z "$KEY_FILE" ]; then
    CERT_DIR="$SCRIPT_DIR/certs"
    if [ -d "$CERT_DIR" ]; then
        for candidate in "$CERT_DIR"/*.crt; do
            [ -e "$candidate" ] || continue
            key_candidate="${candidate%.crt}.key"
            if [ -f "$key_candidate" ]; then
                CERT_FILE="$candidate"
                KEY_FILE="$key_candidate"
                break
            fi
        done
    fi
fi

if [ -f "$CERT_FILE" ] && [ -f "$KEY_FILE" ]; then
    SSL_ARGS="--ssl-certfile=$CERT_FILE --ssl-keyfile=$KEY_FILE"
    SCHEME="https"
else
    SCHEME="http"
fi

echo "========================================="
echo "  hermes-companion ($SCHEME)"
echo "========================================="
echo "  Port:   $PORT"
echo "  URL:    $SCHEME://localhost:$PORT"
if [ "$SCHEME" = "http" ] && [ "$PORT" != "80" ]; then
    echo ""
    echo "  NOTE: microphone access requires HTTPS in most browsers."
    echo "  For remote access, drop a cert pair into certs/ or export"
    echo "  COMPANION_CERT and COMPANION_KEY."
fi
echo "========================================="

cd "$SCRIPT_DIR/backend"
exec "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port "$PORT" $SSL_ARGS
