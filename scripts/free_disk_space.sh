#!/bin/bash
# =============================================================================
# scripts/free_disk_space.sh — Free disk space on the trading-bot server
# =============================================================================
# Run this script when the bot fails with:
#   "No space left on device"
#   or venv_prestart.sh exits with disk-space error
#
# WHAT IS PRESERVED (never deleted by this script):
#   /opt/trading-bot/src/          — bot source code
#   /opt/trading-bot/models/       — trained ML model weights (AI knowledge)
#   /opt/trading-bot/config.yaml   — bot configuration
#   /opt/trading-bot/.env          — environment / secrets
#   /var/lib/trading-bot/          — runtime data (positions, trades, DB)
#
# WHAT IS REMOVED (to free disk space):
#   Docker images (all stopped containers + dangling images)
#   Docker build cache
#   /opt/trading-bot/venv/         — Python virtual environment (auto-rebuilt on next start)
#   pip download cache (~/.cache/pip)
#   systemd journal (trimmed to 100 MB)
#   apt package cache
#   Python __pycache__ / *.pyc
#   Temporary files in /tmp
#
# Usage (as root):
#   sudo bash /opt/trading-bot/scripts/free_disk_space.sh
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
step()    { echo -e "${BLUE}[STEP]${NC}  $*"; }
section() { echo ""; echo "=== $* ==="; }

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash $0"
    exit 1
fi

BOT_DIR="/opt/trading-bot"
VENV_DIR="$BOT_DIR/venv"
MODEL_DIR="$BOT_DIR/models"

section "Current disk usage"
df -h /opt /var /tmp 2>/dev/null || df -h

# ---------------------------------------------------------------------------
section "Step 1: Trim systemd journal (often 500 MB – 2 GB)"
# ---------------------------------------------------------------------------
journalctl --disk-usage 2>/dev/null || true
journalctl --vacuum-size=100M
info "Journal trimmed to 100 MB"

# ---------------------------------------------------------------------------
section "Step 2: Clean apt package cache"
# ---------------------------------------------------------------------------
apt-get clean 2>/dev/null && info "apt cache cleared" || warn "apt-get clean failed (non-Debian?)"
apt-get autoremove -y 2>/dev/null || true

# ---------------------------------------------------------------------------
section "Step 3: Remove pip download caches (all users)"
# ---------------------------------------------------------------------------
pip3 cache purge 2>/dev/null || true
rm -rf /root/.cache/pip
# Clear pip cache for all home directories
for home_dir in /home/*; do
    [ -d "$home_dir/.cache/pip" ] && rm -rf "$home_dir/.cache/pip" && info "Cleared pip cache for $home_dir"
done
info "pip caches cleared"

# ---------------------------------------------------------------------------
section "Step 4: Remove temporary files"
# ---------------------------------------------------------------------------
find /tmp -maxdepth 3 -name "*.whl" -delete 2>/dev/null || true
find /tmp -maxdepth 3 -name "pip-*" -exec rm -rf {} + 2>/dev/null || true
find /tmp -maxdepth 2 -name "tmp*" -mtime +1 -exec rm -rf {} + 2>/dev/null || true
info "Temporary files cleaned"

# ---------------------------------------------------------------------------
section "Step 5: Remove Python __pycache__ in the bot"
# ---------------------------------------------------------------------------
if [ -d "$BOT_DIR" ]; then
    find "$BOT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$BOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    info "Python cache cleaned in $BOT_DIR"
fi

# ---------------------------------------------------------------------------
section "Step 6: Remove the Python virtual environment"
# ---------------------------------------------------------------------------
# The venv is NOT the bot code — it is just installed Python packages that are
# automatically rebuilt by venv_prestart.sh on the next 'systemctl start'.
# Removing it is safe and frees several hundred MB.
if [ -d "$VENV_DIR" ]; then
    VENV_SIZE=$(du -sh "$VENV_DIR" 2>/dev/null | cut -f1)
    step "Removing venv ($VENV_SIZE) — will be auto-rebuilt on next bot start..."
    rm -rf "$VENV_DIR"
    # Also remove the requirements stamp so venv_prestart.sh reinstalls everything
    rm -f "$VENV_DIR/.requirements_installed" 2>/dev/null || true
    info "venv removed. The bot will rebuild it automatically on next start."
else
    info "No venv found at $VENV_DIR"
fi

# ---------------------------------------------------------------------------
section "Step 7: Clean Docker images and build cache"
# ---------------------------------------------------------------------------
if command -v docker &>/dev/null; then
    # Stop and remove the trading-bot container if it is not running
    # (leave running containers intact so other services are not disrupted)
    STOPPED=$(docker ps -a --filter "status=exited" --filter "status=created" \
              --filter "status=dead" --format "{{.ID}}" 2>/dev/null || true)
    if [ -n "$STOPPED" ]; then
        step "Removing stopped containers..."
        echo "$STOPPED" | xargs docker rm -f 2>/dev/null || true
        info "Stopped containers removed"
    fi

    # Remove dangling (untagged) images — safe, they are not used by anything
    DANGLING=$(docker images -f "dangling=true" -q 2>/dev/null || true)
    if [ -n "$DANGLING" ]; then
        step "Removing dangling Docker images..."
        echo "$DANGLING" | xargs docker rmi -f 2>/dev/null || true
        info "Dangling images removed"
    fi

    # Remove the trading-bot image itself so it is rebuilt fresh next time
    # (this avoids re-using a broken cached layer that caused the build failure)
    if docker images --format "{{.Repository}}" 2>/dev/null | grep -q "trading-bot\|life-is_a_joke"; then
        step "Removing trading-bot Docker image (will be rebuilt on next docker-compose up)..."
        docker images --format "{{.ID}} {{.Repository}}" 2>/dev/null \
            | grep -E "trading-bot|life-is_a_joke" \
            | awk '{print $1}' \
            | xargs docker rmi -f 2>/dev/null || true
        info "trading-bot image removed"
    fi

    # Prune build cache (often the largest consumer — can be 2–5 GB)
    step "Pruning Docker build cache..."
    docker builder prune -af 2>/dev/null && info "Docker build cache pruned" || \
        warn "docker builder prune failed (Docker version too old?)"

    # Prune unused networks
    docker network prune -f 2>/dev/null || true

    info "Docker cleanup complete"
else
    warn "Docker not found — skipping Docker cleanup"
fi

# ---------------------------------------------------------------------------
section "Step 8: Check for old bot backups"
# ---------------------------------------------------------------------------
OLD_BACKUPS=$(ls -d /opt/trading-bot.backup.* 2>/dev/null || true)
if [ -n "$OLD_BACKUPS" ]; then
    warn "Found old backups — review and remove manually if safe:"
    du -sh /opt/trading-bot.backup.* 2>/dev/null || true
    echo "  To remove: rm -rf /opt/trading-bot.backup.<timestamp>"
else
    info "No old bot backups found"
fi

# ---------------------------------------------------------------------------
section "Step 9: ML model files (PRESERVED)"
# ---------------------------------------------------------------------------
if [ -d "$MODEL_DIR" ]; then
    MODEL_SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    info "ML models directory PRESERVED: $MODEL_SIZE  ($MODEL_DIR)"
    info "  (trained AI knowledge — these files are NOT removed)"
else
    info "No models directory found at $MODEL_DIR"
fi

# ---------------------------------------------------------------------------
section "Disk usage after cleanup"
# ---------------------------------------------------------------------------
df -h /opt /var /tmp 2>/dev/null || df -h

echo ""
echo "======================================================="
echo -e "${GREEN}Cleanup complete!${NC}"
echo "======================================================="
echo ""
echo "PRESERVED (bot code + AI knowledge):"
echo "  $BOT_DIR/src/     — source code"
echo "  $BOT_DIR/models/  — trained ML model weights"
echo "  $BOT_DIR/config.yaml, .env"
echo ""
echo "REMOVED:"
echo "  venv (auto-rebuilt on next start)"
echo "  Docker images + build cache"
echo "  pip/apt/journal/tmp caches"
echo ""
echo "If disk is still full, check these large directories:"
echo "  du -sh /opt/*   /var/*   /home/*   /tmp/*  2>/dev/null | sort -hr | head -20"
echo ""
echo "To restart the bot:"
echo "  sudo systemctl restart trading-bot"
echo "  sudo journalctl -u trading-bot -f"
