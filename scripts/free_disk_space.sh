#!/bin/bash
# =============================================================================
# scripts/free_disk_space.sh — Free disk space on the trading-bot server
# =============================================================================
# Run this script when the bot fails with:
#   "No space left on device"
#   or venv_prestart.sh exits with disk-space error
#
# Usage (as root):
#   sudo bash /opt/trading-bot/scripts/free_disk_space.sh
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
section() { echo ""; echo "=== $* ==="; }

if [ "$EUID" -ne 0 ]; then
    echo "Run as root: sudo bash $0"
    exit 1
fi

section "Current disk usage"
df -h /opt /var /tmp 2>/dev/null || df -h

section "Step 1: Trim systemd journal (often 500 MB – 2 GB)"
journalctl --disk-usage 2>/dev/null || true
journalctl --vacuum-size=100M
info "Journal trimmed to 100 MB"

section "Step 2: Clean apt package cache"
apt-get clean 2>/dev/null && info "apt cache cleared" || warn "apt-get clean failed (non-Debian?)"

section "Step 3: Remove pip download cache"
pip3 cache purge 2>/dev/null && info "pip cache cleared" || true
# Also clear root's pip cache
rm -rf /root/.cache/pip && info "root pip cache cleared" || true

section "Step 4: Remove old pip partial downloads"
find /tmp -maxdepth 2 -name "*.whl" -delete 2>/dev/null && info "Removed temp .whl files" || true
# Only remove pip temp directories older than 1 day to avoid touching active downloads.
find /tmp -maxdepth 2 -name "pip-*" -mtime +1 -exec rm -rf {} + 2>/dev/null || true

section "Step 5: Remove __pycache__ directories in the bot"
BOT_DIR="/opt/trading-bot"
if [ -d "$BOT_DIR" ]; then
    find "$BOT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$BOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    info "Python cache cleaned in $BOT_DIR"
fi

section "Step 6: Check for old bot backups"
OLD_BACKUPS=$(ls -d /opt/trading-bot.backup.* 2>/dev/null || true)
if [ -n "$OLD_BACKUPS" ]; then
    warn "Found old backups — review and remove manually if safe:"
    du -sh /opt/trading-bot.backup.* 2>/dev/null || true
    echo "  To remove: rm -rf /opt/trading-bot.backup.<timestamp>"
else
    info "No old bot backups found"
fi

section "Step 7: Check for stale ML model files"
MODEL_DIR="$BOT_DIR/models"
if [ -d "$MODEL_DIR" ]; then
    MODEL_SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    warn "ML models directory: $MODEL_SIZE  ($MODEL_DIR)"
    warn "If you do not use advanced ML strategies, remove it with:"
    warn "  rm -rf $MODEL_DIR"
else
    info "No models directory found"
fi

section "Disk usage after cleanup"
df -h /opt /var /tmp 2>/dev/null || df -h

echo ""
echo "======================================================="
echo -e "${GREEN}Cleanup complete!${NC}"
echo "======================================================="
echo ""
echo "If disk is still full, check these large directories:"
echo "  du -sh /opt/*   /var/*   /home/*   /tmp/*  2>/dev/null | sort -hr | head -20"
echo ""
echo "To restart the bot after freeing space:"
echo "  sudo systemctl restart trading-bot"
echo "  sudo journalctl -u trading-bot -f"
