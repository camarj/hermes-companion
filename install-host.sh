#!/usr/bin/env bash
# hermes-companion — host-mode provisioning installer (PRD §3.2.1)
#
# One command to stand up the companion *sidecar* in host mode on a machine
# that already runs the `hermes` agent. It pulls the repo, builds a venv,
# installs the backend deps, seeds a bearer token into config.yaml, and prints
# the token + the wss:// URL + the launch command.
#
# It does NOT install `hermes` itself (assumed present) and does NOT start the
# server — it provisions and reports the exact launch command.
#
# Usage:
#   ./install-host.sh [--label NAME] [--dir PATH] [--repo URL] [--branch REF]
#                     [--host PUBLIC_HOST] [--port PORT]
#
#   curl -sSL https://raw.githubusercontent.com/<owner>/hermes-companion/main/install-host.sh | bash -s -- --label vps-prod

set -euo pipefail

REPO="${HERMES_COMPANION_REPO:-https://github.com/camarj/hermes-companion.git}"
BRANCH="main"
INSTALL_DIR=""
LABEL="$(hostname)"
PUBLIC_HOST="$(hostname)"
PORT="8000"

while [ $# -gt 0 ]; do
    case "$1" in
        --label)  LABEL="$2";       shift 2 ;;
        --dir)    INSTALL_DIR="$2";  shift 2 ;;
        --repo)   REPO="$2";         shift 2 ;;
        --branch) BRANCH="$2";       shift 2 ;;
        --host)   PUBLIC_HOST="$2";  shift 2 ;;
        --port)   PORT="$2";         shift 2 ;;
        -h|--help)
            sed -n '2,20p' "$0"; exit 0 ;;
        *)
            echo "ERROR: unknown argument: $1" >&2; exit 2 ;;
    esac
done

err()  { echo "ERROR: $*" >&2; exit 1; }
note() { echo "[install-host] $*"; }

command -v git >/dev/null 2>&1 || err "git is required but not installed."
PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || err "python3 is required but not installed."

if ! command -v hermes >/dev/null 2>&1; then
    note "WARNING: 'hermes' not found on PATH. This installs the companion"
    note "         sidecar only — install the hermes agent before going live."
fi

# ── Locate or fetch the repo ────────────────────────────────────────────────
# If run from inside an existing clone (start.sh next to this script), update
# in place. Otherwise clone REPO into INSTALL_DIR (default ./hermes-companion).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/start.sh" ] && [ -d "$SCRIPT_DIR/backend" ]; then
    INSTALL_DIR="$SCRIPT_DIR"
    note "using existing clone at $INSTALL_DIR"
    git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH" || \
        note "could not fast-forward; continuing with the checked-out tree."
else
    INSTALL_DIR="${INSTALL_DIR:-$PWD/hermes-companion}"
    if [ -d "$INSTALL_DIR/.git" ]; then
        note "updating existing clone at $INSTALL_DIR"
        git -C "$INSTALL_DIR" pull --ff-only origin "$BRANCH"
    else
        note "cloning $REPO into $INSTALL_DIR"
        git clone --branch "$BRANCH" --depth 1 "$REPO" "$INSTALL_DIR"
    fi
fi

cd "$INSTALL_DIR"

# ── venv + backend deps (no frontend: host mode 404s the UI) ────────────────
if [ ! -x "venv/bin/python" ]; then
    note "creating venv"
    "$PYTHON" -m venv venv
fi
note "installing backend dependencies"
./venv/bin/pip install --quiet --upgrade pip
./venv/bin/pip install --quiet -r backend/requirements.txt

# ── Seed the bearer token + report ──────────────────────────────────────────
note "seeding host token (label: $LABEL)"
PYTHONPATH=backend ./venv/bin/python -m provision_host \
    --label "$LABEL" --config "$INSTALL_DIR/config.yaml" \
    --host "$PUBLIC_HOST" --port "$PORT"

echo
note "done — review config.yaml, then run the launch command above."
