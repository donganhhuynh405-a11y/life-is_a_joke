#!/bin/bash
# =============================================================================
# scripts/venv_prestart.sh  —  Root-level pre-start helper for the systemd service
#
# Invoked by the systemd service as:
#   ExecStartPre=+/opt/trading-bot/scripts/venv_prestart.sh
#
# The "+" prefix makes systemd run this script as root even though the main
# service runs as User=tradingbot.  This allows us to:
#   1. Create the virtual environment if it is absent.
#   2. Fix ownership of the venv so the service user can read/write it.
#   3. Install (or update) Python packages if requirements.txt has changed
#      since the last successful install (tracked via sha256 stamp file).
#
# After this script completes, start_bot.sh (running as tradingbot) will find
# a fully-owned, fully-populated venv and start the bot without any pip calls.
# =============================================================================

set -e

BOT_DIR="/opt/trading-bot"
VENV_DIR="$BOT_DIR/venv"
VENV_PYTHON="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip"
REQUIREMENTS="$BOT_DIR/requirements.txt"
STAMP_FILE="$VENV_DIR/.requirements_installed"
SERVICE_USER="tradingbot"
DATA_DIR="/var/lib/trading-bot"
LOG_DIR="/var/log/trading-bot"

# Minimum free disk space (in MB) required before attempting pip install.
# Core packages need roughly 300–500 MB; leave 512 MB as a safe floor.
MIN_FREE_MB=512

log() { echo "[prestart] $*" >&2; }

# ---------------------------------------------------------------------------
# Self-heal: a plain 'git pull' does not update file modes on disk, so the
# execute bit may be missing after an update.  Fix it here so this script
# and start_bot.sh can always be executed by systemd and the service user.
# ---------------------------------------------------------------------------
for script in "$BOT_DIR/scripts/venv_prestart.sh" "$BOT_DIR/scripts/start_bot.sh"; do
    [ -f "$script" ] && chmod +x "$script"
done

# ---------------------------------------------------------------------------
# Disk space guard — abort early with a clear message instead of filling the
# disk mid-download and leaving a partial / corrupt venv.
# ---------------------------------------------------------------------------
check_disk_space() {
    local target_dir="$1"
    local required_mb="$2"
    local free_mb
    free_mb=$(df -m "$target_dir" 2>/dev/null | tail -1 | awk '{print $4}')
    if [ -n "$free_mb" ] && [ "$free_mb" -lt "$required_mb" ]; then
        log "ERROR: Not enough free disk space for pip install."
        log "  Required : ${required_mb} MB"
        log "  Available: ${free_mb} MB  (on the filesystem containing $target_dir)"
        log ""
        log "Free up disk space before starting the bot:"
        log "  df -h                               # see usage by filesystem"
        log "  du -sh /opt/trading-bot/venv        # venv size"
        log "  journalctl --disk-usage             # journal size"
        log "  journalctl --vacuum-size=100M       # trim journal to 100 MB"
        log "  pip cache purge                     # remove pip's download cache"
        log "  apt-get clean                       # remove cached .deb packages"
        log ""
        log "The heavy ML packages (torch, tensorflow) are NOT required to run"
        log "the bot.  They live in requirements-ml.txt and can be installed"
        log "separately once you have enough free space:"
        log "  pip install -r /opt/trading-bot/requirements-ml.txt"
        return 1
    fi
    return 0
}

# Ensure runtime directories exist and are owned by the service user.
for dir in "$DATA_DIR" "$LOG_DIR"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        log "Created directory: $dir"
    fi
    if id "$SERVICE_USER" &>/dev/null; then
        chown "$SERVICE_USER:$SERVICE_USER" "$dir"
    fi
done

# 1. Create the virtual environment if missing.
if [ ! -x "$VENV_PYTHON" ]; then
    log "venv not found — creating virtual environment..."
    if ! python3 -m venv "$VENV_DIR"; then
        log "ERROR: 'python3 -m venv' failed."
        log "Install the venv package for your Python version, e.g.:"
        log "  Debian/Ubuntu: apt-get install -y python3-venv"
        log "  RHEL/Fedora:   dnf install -y python3"
        exit 1
    fi
    log "venv created."
fi

# 2. Fix ownership so the service user can import packages and write the stamp.
#    This is the core fix: even if the venv was created by root, we transfer
#    ownership to tradingbot so start_bot.sh (running as tradingbot) can work
#    with it without any permission errors.
if id "$SERVICE_USER" &>/dev/null; then
    log "Fixing venv ownership ($SERVICE_USER:$SERVICE_USER)..."
    chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV_DIR"
fi

# 3. Install / update packages only when requirements.txt has changed since the
#    last successful install.  Packages are installed as root (so the script can
#    always write to the venv) and ownership is re-applied afterwards.
CURRENT_HASH=$(sha256sum "$REQUIREMENTS" 2>/dev/null | awk '{print $1}')
STAMP_HASH=$(awk '{print $1}' "$STAMP_FILE" 2>/dev/null)

if [ "$CURRENT_HASH" != "$STAMP_HASH" ]; then
    log "requirements.txt changed — checking disk space before installing packages..."
    if ! check_disk_space "$VENV_DIR" "$MIN_FREE_MB"; then
        exit 1
    fi
    log "Installing packages (this may take a minute)..."
    # Run pip without --quiet so any errors are visible in journalctl.
    if "$VENV_PIP" install -r "$REQUIREMENTS"; then
        sha256sum "$REQUIREMENTS" > "$STAMP_FILE"
        # Re-apply ownership after pip may have written new files as root.
        if id "$SERVICE_USER" &>/dev/null; then
            chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV_DIR"
        fi
        log "Packages installed and stamp updated."
    else
        log "ERROR: pip install failed — see the pip output above for details."
        exit 1
    fi
else
    log "requirements.txt unchanged — skipping pip install."
fi

# 4. Verify that certifi's CA bundle is intact.
#    If the venv was deleted and recreated while the disk was nearly full,
#    certifi may have been partially installed — its cacert.pem may be missing.
#    This causes "Could not find a suitable TLS CA certificate bundle" errors
#    that break all HTTPS connections (exchange API, Telegram, etc.).
CERTIFI_BUNDLE_PATH=$("$VENV_PYTHON" -c "import certifi; print(certifi.where())" 2>/dev/null || true)
if [ -n "$CERTIFI_BUNDLE_PATH" ] && [ ! -f "$CERTIFI_BUNDLE_PATH" ]; then
    log "WARNING: certifi CA bundle missing at $CERTIFI_BUNDLE_PATH — reinstalling certifi..."
    "$VENV_PIP" install --force-reinstall --no-cache-dir certifi 2>&1 | sed 's/^/[prestart] /' >&2
    if id "$SERVICE_USER" &>/dev/null; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV_DIR"
    fi
    log "certifi reinstalled."
elif [ -z "$CERTIFI_BUNDLE_PATH" ]; then
    log "WARNING: certifi not importable — installing..."
    "$VENV_PIP" install --no-cache-dir certifi 2>&1 | sed 's/^/[prestart] /' >&2
    if id "$SERVICE_USER" &>/dev/null; then
        chown -R "$SERVICE_USER:$SERVICE_USER" "$VENV_DIR"
    fi
    log "certifi installed."
fi

