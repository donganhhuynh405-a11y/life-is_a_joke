#!/bin/bash
# =============================================================================
# scripts/start_bot.sh  —  Trading Bot startup wrapper
#
# Used by the systemd service as ExecStart.
# Ensures the virtual environment exists before launching main.py.
# This prevents the 203/EXEC failure that occurs when venv/bin/python3 is absent.
# =============================================================================

BOT_DIR="/opt/trading-bot"
VENV_DIR="$BOT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
MAIN_PY="$BOT_DIR/src/main.py"

# Rebuild the virtual environment if the python3 binary is missing.
if [ ! -x "$VENV_PYTHON" ]; then
    echo "[start_bot] venv/bin/python3 not found — rebuilding virtual environment..." >&2
    if ! python3 -m venv "$VENV_DIR"; then
        echo "[start_bot] ERROR: 'python3 -m venv' failed." >&2
        echo "[start_bot] Install the venv module first: apt-get install -y python3-venv" >&2
        exit 1
    fi
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    if [ -f "$BOT_DIR/requirements.txt" ]; then
        "$VENV_DIR/bin/pip" install -r "$BOT_DIR/requirements.txt" --quiet
    fi
    echo "[start_bot] venv rebuild complete." >&2
fi

# Launch the bot
exec "$VENV_PYTHON" "$MAIN_PY" "$@"
