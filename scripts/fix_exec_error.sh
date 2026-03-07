#!/bin/bash
# =============================================================================
# scripts/fix_exec_error.sh
#
# Quick-fix script for the systemd 203/EXEC error:
#   "trading-bot.service: Main process exited, code=exited, status=203/EXEC"
#
# This error means the Python interpreter referenced in the service file
# does not exist.  The most common cause is that the virtual environment
# was never created, was deleted, or was created without a 'python3' binary.
#
# Run with root / sudo:
#   sudo bash /opt/trading-bot/scripts/fix_exec_error.sh
#
# What this script does:
#   1. Diagnoses the exact cause of 203/EXEC
#   2. Rebuilds the virtual environment if needed
#   3. Installs Python dependencies
#   4. Updates the systemd service file from the repo
#   5. Restarts the service and shows the result
# =============================================================================

set -e

# --- Colours -----------------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
info() { echo -e "${BLUE}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR]${NC}  $*"; }

BOT_DIR="/opt/trading-bot"
VENV_DIR="$BOT_DIR/venv"
SERVICE_NAME="trading-bot"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
REPO_SERVICE="$BOT_DIR/deployment/systemd/$SERVICE_NAME.service"

echo "============================================================"
echo "  TRADING BOT – 203/EXEC FIX SCRIPT"
echo "============================================================"
echo ""

# --- Check root --------------------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    err "Please run as root:  sudo bash $0"
    exit 1
fi

# --- 1. Diagnose -------------------------------------------------------------
info "Step 1/5: Diagnosing the problem..."

PYTHON3_SYS=$(command -v python3 || echo "")
if [ -z "$PYTHON3_SYS" ]; then
    err "System python3 not found!  Install it first:"
    err "  apt-get install -y python3 python3-venv python3-pip"
    exit 1
fi
ok  "System python3 found: $PYTHON3_SYS  ($(python3 --version 2>&1))"

VENV_PYTHON="$VENV_DIR/bin/python3"
if [ ! -f "$VENV_PYTHON" ]; then
    warn "Virtual environment python3 NOT found at: $VENV_PYTHON"
    warn "This is the cause of the 203/EXEC error."
    NEED_VENV=true
elif [ ! -x "$VENV_PYTHON" ]; then
    warn "$VENV_PYTHON exists but is not executable"
    warn "This is the cause of the 203/EXEC error."
    NEED_VENV=true
else
    ok  "Virtual environment python3 found: $VENV_PYTHON"
    NEED_VENV=false
fi

# Check for old 'python' reference (not 'python3') in service file — another common cause
# of 203/EXEC on systems where venv only creates python3, not python.
if [ -f "$SERVICE_FILE" ] && grep -qP 'venv/bin/python(?!3)' "$SERVICE_FILE" 2>/dev/null; then
    warn "Service file uses 'venv/bin/python' — on some systems this doesn't exist."
    warn "It should be 'venv/bin/python3'."
    NEED_SERVICE_FIX=true
elif [ -f "$SERVICE_FILE" ] && grep -q 'venv/bin/python[^3]' "$SERVICE_FILE"; then
    warn "Service file uses 'venv/bin/python' — on some systems this doesn't exist."
    warn "It should be 'venv/bin/python3'."
    NEED_SERVICE_FIX=true
else
    NEED_SERVICE_FIX=false
fi

echo ""

# --- 2. Rebuild venv ---------------------------------------------------------
info "Step 2/5: Ensuring virtual environment exists..."

if [ "$NEED_VENV" = true ]; then
    info "  Removing old (broken) venv..."
    rm -rf "$VENV_DIR"
    info "  Creating fresh virtual environment..."
    python3 -m venv "$VENV_DIR"
    ok  "  Virtual environment created at $VENV_DIR"
else
    ok  "  Virtual environment OK"
fi

echo ""

# --- 3. Install dependencies -------------------------------------------------
info "Step 3/5: Installing Python dependencies..."

REQUIREMENTS="$BOT_DIR/requirements.txt"
if [ ! -f "$REQUIREMENTS" ]; then
    warn "requirements.txt not found at $REQUIREMENTS"
    warn "Skipping dependency installation"
else
    "$VENV_DIR/bin/pip" install --upgrade pip --quiet
    "$VENV_DIR/bin/pip" install -r "$REQUIREMENTS" --quiet
    ok  "Dependencies installed"
fi

echo ""

# --- 4. Update service file --------------------------------------------------
info "Step 4/5: Updating systemd service file..."

if [ -f "$REPO_SERVICE" ]; then
    # Ensure it uses python3, not python
    cp "$REPO_SERVICE" "$SERVICE_FILE"
    # If somehow the repo file still has 'venv/bin/python' without '3', fix it.
    # The pattern matches 'python' NOT followed by '3' to avoid double-substitution.
    sed -i 's|venv/bin/python\([^3]\)|venv/bin/python3\1|g' "$SERVICE_FILE"
    systemctl daemon-reload
    ok  "Service file updated from repo: $REPO_SERVICE"
elif [ -f "$SERVICE_FILE" ]; then
    # Fix python → python3 in the existing service file
    if [ "$NEED_SERVICE_FIX" = true ]; then
        info "  Patching existing service file (python → python3)..."
        sed -i 's|venv/bin/python\([^3]\)|venv/bin/python3\1|g' "$SERVICE_FILE"
        systemctl daemon-reload
        ok  "Service file patched"
    else
        ok  "Service file does not need changes"
    fi
else
    warn "No service file found at $SERVICE_FILE"
    warn "You may need to reinstall the service:"
    warn "  sudo bash $BOT_DIR/deployment/deploy.sh"
fi

echo ""

# --- 5. Fix ownership and restart --------------------------------------------
info "Step 5/5: Fixing ownership and starting service..."

if id "tradingbot" &>/dev/null; then
    chown -R tradingbot:tradingbot "$VENV_DIR"
    ok  "Ownership fixed (tradingbot:tradingbot)"
else
    warn "User 'tradingbot' not found — skipping chown"
fi

systemctl stop "$SERVICE_NAME" 2>/dev/null || true
sleep 1
systemctl start "$SERVICE_NAME"
sleep 3

echo ""
echo "============================================================"
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok  "Service started successfully!"
    echo ""
    systemctl status "$SERVICE_NAME" --no-pager -l | head -20
else
    err "Service still failed to start.  Full status:"
    echo ""
    systemctl status "$SERVICE_NAME" --no-pager -l | head -30
    echo ""
    err "Last 30 log lines:"
    journalctl -u "$SERVICE_NAME" -n 30 --no-pager
    echo ""
    err "Investigate with:  sudo journalctl -u $SERVICE_NAME -f"
    exit 1
fi
echo "============================================================"
