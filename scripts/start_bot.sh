#!/bin/bash
# =============================================================================
# scripts/start_bot.sh  —  Trading Bot startup wrapper
#
# Used by the systemd service as ExecStart.
# Ensures the virtual environment exists and all requirements are installed
# before launching main.py.
# This prevents the 203/EXEC failure that occurs when venv/bin/python3 is
# absent, and the ModuleNotFoundError crashes that happen when the venv exists
# but is missing packages (e.g. after a requirements.txt update).
# =============================================================================

BOT_DIR="/opt/trading-bot"
VENV_DIR="$BOT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"
MAIN_PY="$BOT_DIR/src/main.py"
REQUIREMENTS="$BOT_DIR/requirements.txt"
# Stamp file stores the sha256 of the last successfully installed requirements.txt
# so we only re-run pip when the file actually changes.
STAMP_FILE="$VENV_DIR/.requirements_installed"

install_requirements() {
    if [ -f "$REQUIREMENTS" ]; then
        echo "[start_bot] Installing/updating requirements..." >&2
        "$VENV_PIP" install --upgrade pip --quiet
        "$VENV_PIP" install -r "$REQUIREMENTS" --quiet
        # Record the hash so we can skip reinstall on the next start
        sha256sum "$REQUIREMENTS" > "$STAMP_FILE" 2>/dev/null || true
        echo "[start_bot] Requirements installed." >&2
    fi
}

# Rebuild the virtual environment if the python3 binary is missing.
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[start_bot] venv/bin/python3 not found — rebuilding virtual environment..." >&2
    if ! python3 -m venv "$VENV_DIR"; then
        echo "[start_bot] ERROR: 'python3 -m venv' failed." >&2
        echo "[start_bot] Install the venv module first: apt-get install -y python3-venv" >&2
        exit 1
    fi
    install_requirements
    echo "[start_bot] venv rebuild complete." >&2
else
    # Venv exists — reinstall requirements if requirements.txt has changed since
    # the last successful install (detected via sha256 stamp file).
    CURRENT_HASH=""
    STAMP_HASH=""
    if [ -f "$REQUIREMENTS" ]; then
        CURRENT_HASH=$(sha256sum "$REQUIREMENTS" 2>/dev/null | awk '{print $1}')
    fi
    if [ -f "$STAMP_FILE" ]; then
        STAMP_HASH=$(awk '{print $1}' "$STAMP_FILE" 2>/dev/null)
    fi
    if [ "$CURRENT_HASH" != "$STAMP_HASH" ]; then
        echo "[start_bot] requirements.txt changed — reinstalling..." >&2
        install_requirements
    fi
fi

# Launch the bot
exec "$VENV_PYTHON" "$MAIN_PY" "$@"
