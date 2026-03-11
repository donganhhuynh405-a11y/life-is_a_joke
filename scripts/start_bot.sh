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
        # Do NOT run 'pip install --upgrade pip' here: start_bot.sh runs as the
        # service user (tradingbot) which may not own the venv binary, causing a
        # permission denied error trying to overwrite venv/bin/pip.  The venv
        # pip is already good enough to install packages.
        if "$VENV_PIP" install -r "$REQUIREMENTS" --quiet; then
            # Record the hash only on success so a failed install is retried on
            # the next restart instead of being silently skipped.
            sha256sum "$REQUIREMENTS" > "$STAMP_FILE" 2>/dev/null || true
            echo "[start_bot] Requirements installed." >&2
        else
            echo "[start_bot] WARNING: pip install failed (see above). The bot will" >&2
            echo "[start_bot]   try to start with whatever packages are already in the venv." >&2
            echo "[start_bot]   To fix permanently, run as root:" >&2
            echo "[start_bot]     /opt/trading-bot/venv/bin/pip install -r /opt/trading-bot/requirements.txt" >&2
            echo "[start_bot]     chown -R tradingbot:tradingbot /opt/trading-bot/venv" >&2
        fi
    fi
}

# Check whether the current user can write into the venv.  If the venv was
# created by root and not yet chowned to the service user, pip will fail with
# "Permission denied" and emit confusing error messages.  We detect this early
# and skip the pip step, relying on packages that were already installed.
venv_is_writable() {
    [ -w "$VENV_DIR" ] && [ -w "$VENV_PIP" ]
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
        if venv_is_writable; then
            install_requirements
        else
            echo "[start_bot] WARNING: venv is not writable by $(id -un). Skipping pip." >&2
            echo "[start_bot]   To fix, run as root:" >&2
            echo "[start_bot]     chown -R tradingbot:tradingbot /opt/trading-bot/venv" >&2
            echo "[start_bot]     /opt/trading-bot/venv/bin/pip install -r /opt/trading-bot/requirements.txt" >&2
        fi
    fi
fi

# Launch the bot
exec "$VENV_PYTHON" "$MAIN_PY" "$@"
