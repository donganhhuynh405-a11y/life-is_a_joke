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
#   /opt/trading-bot/scripts/      — bot scripts
#   /opt/trading-bot/models/       — trained ML model weights (AI knowledge)
#   /opt/trading-bot/config.yaml   — bot configuration
#   /opt/trading-bot/.env          — environment / secrets
#   /opt/trading-bot/requirements*.txt  — dependency lists
#   /var/lib/trading-bot/          — runtime data (positions, trades, DB)
#
# WHAT IS REMOVED (to free disk space):
#   All Docker images, containers, volumes, build cache
#   /opt/trading-bot/venv/         — Python virtual environment (auto-rebuilt on next start)
#   All other Python venvs found outside the bot directory
#   pip / npm / yarn download caches (all users)
#   systemd journal (trimmed to 100 MB)
#   apt package cache
#   Python __pycache__ / *.pyc (everywhere)
#   Temporary files in /tmp  (all)
#   node_modules directories outside bot code
#   Old log files in /var/log (rotated/compressed logs)
#   Old bot installations / duplicates in /home, /root etc.
#   Jupyter / IPython notebooks output and checkpoints
#   Build artefacts (.eggs, dist/, build/, __pycache__)
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

# ---------------------------------------------------------------------------
section "Current disk usage"
# ---------------------------------------------------------------------------
df -h / /opt /var /tmp 2>/dev/null || df -h
echo ""
echo "Top 20 largest directories on the system:"
du -sh /opt/* /var/* /home/* /tmp/* /root 2>/dev/null | sort -hr | head -20 || true

# ---------------------------------------------------------------------------
section "Step 1: Trim systemd journal (often 500 MB – 2 GB)"
# ---------------------------------------------------------------------------
journalctl --disk-usage 2>/dev/null || true
journalctl --vacuum-size=50M 2>/dev/null || journalctl --vacuum-size=100M 2>/dev/null || true
# Also remove old rotated journal files directly
find /var/log/journal -name "*.journal~" -delete 2>/dev/null || true
find /var/log/journal -name "system@*.journal" -mtime +7 -delete 2>/dev/null || true
info "Journal trimmed to 50 MB"

# ---------------------------------------------------------------------------
section "Step 2: Clean apt package cache"
# ---------------------------------------------------------------------------
apt-get clean 2>/dev/null && info "apt cache cleared" || warn "apt-get clean failed (non-Debian?)"
apt-get autoremove -y 2>/dev/null || true
rm -rf /var/lib/apt/lists/* 2>/dev/null || true
info "apt lists removed"

# ---------------------------------------------------------------------------
section "Step 3: Remove ALL pip / conda / poetry caches (all users)"
# ---------------------------------------------------------------------------
pip3 cache purge 2>/dev/null || true
rm -rf /root/.cache/pip /root/.cache/poetry /root/.local/share/pip 2>/dev/null || true
for home_dir in /home/*; do
    rm -rf "$home_dir/.cache/pip" "$home_dir/.cache/poetry" \
           "$home_dir/.local/share/pip" 2>/dev/null || true
done
info "pip/poetry caches cleared for all users"

# ---------------------------------------------------------------------------
section "Step 4: Clear temporary files"
# ---------------------------------------------------------------------------
# Remove files older than 1 hour; preserve active sockets/pipes used by
# running processes (X11, systemd, etc.)
find /tmp -mindepth 1 -maxdepth 4 \
     ! -name ".X11-unix" ! -name ".ICE-unix" ! -name ".XIM-unix" \
     ! -name "systemd-*" \
     -mmin +60 -exec rm -rf {} + 2>/dev/null || true
find /var/tmp -mindepth 1 -maxdepth 3 -mtime +1 -exec rm -rf {} + 2>/dev/null || true
info "Temporary directories cleaned"

# ---------------------------------------------------------------------------
section "Step 5: Remove Python __pycache__ / *.pyc everywhere"
# ---------------------------------------------------------------------------
for search_dir in /opt /home /root /srv; do
    [ -d "$search_dir" ] || continue
    find "$search_dir" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$search_dir" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete 2>/dev/null || true
done
info "Python bytecode caches removed"

# ---------------------------------------------------------------------------
section "Step 6: Remove Python virtual environments outside the bot"
# ---------------------------------------------------------------------------
# Any venv/env/virtualenv directory NOT inside $BOT_DIR is a candidate.
# We look for the canonical marker file pyvenv.cfg to identify venvs.
step "Searching for Python virtual environments outside $BOT_DIR ..."
VENV_REMOVED=0
while IFS= read -r -d '' cfg; do
    venv_path=$(dirname "$cfg")
    # Skip the bot's own venv — it will be handled separately below
    [[ "$venv_path" == "$VENV_DIR"* ]] && continue
    # Skip if inside the bot source tree
    [[ "$venv_path" == "$BOT_DIR"* ]] && continue
    sz=$(du -sh "$venv_path" 2>/dev/null | cut -f1)
    step "  Removing external venv ($sz): $venv_path"
    rm -rf "$venv_path"
    VENV_REMOVED=$((VENV_REMOVED + 1))
done < <(find /opt /home /root /srv -name "pyvenv.cfg" -not -path "$BOT_DIR/venv/*" -print0 2>/dev/null)
info "External virtual environments removed: $VENV_REMOVED"

# ---------------------------------------------------------------------------
section "Step 7: Remove the bot's Python virtual environment"
# ---------------------------------------------------------------------------
# The venv is NOT the bot code — it is just installed Python packages that are
# automatically rebuilt by venv_prestart.sh on the next 'systemctl start'.
# Removing it is safe and frees several hundred MB.
if [ -d "$VENV_DIR" ]; then
    VENV_SIZE=$(du -sh "$VENV_DIR" 2>/dev/null | cut -f1)
    step "Removing venv ($VENV_SIZE) — will be auto-rebuilt on next bot start..."
    rm -rf "$VENV_DIR"
    info "venv removed. The bot will rebuild it automatically on next start."
else
    info "No venv found at $VENV_DIR"
fi

# ---------------------------------------------------------------------------
section "Step 8: Remove old/duplicate bot directories"
# ---------------------------------------------------------------------------
# Users sometimes clone the bot repo to multiple locations during setup.
# Everything that looks like a trading-bot repo outside the canonical path
# can be removed (the canonical path is $BOT_DIR).
for candidate in /home/*/trading-bot /home/*/life-is_a_joke /home/*/.trading-bot \
                 /root/trading-bot /root/life-is_a_joke \
                 /srv/trading-bot /tmp/trading-bot; do
    [ -d "$candidate" ] || continue
    [[ "$candidate" == "$BOT_DIR" ]] && continue
    sz=$(du -sh "$candidate" 2>/dev/null | cut -f1)
    step "  Removing duplicate bot directory ($sz): $candidate"
    rm -rf "$candidate"
done
# Old /opt/trading-bot.backup.* directories
for bak in /opt/trading-bot.backup.*; do
    [ -d "$bak" ] || continue
    sz=$(du -sh "$bak" 2>/dev/null | cut -f1)
    step "  Removing old backup ($sz): $bak"
    rm -rf "$bak"
done
info "Old/duplicate bot directories removed"

# ---------------------------------------------------------------------------
section "Step 9: Remove node_modules outside bot frontend"
# ---------------------------------------------------------------------------
find /opt /home /root /srv -type d -name "node_modules" \
     -not -path "$BOT_DIR/frontend/node_modules" \
     -prune -exec rm -rf {} + 2>/dev/null || true
info "node_modules directories removed"

# ---------------------------------------------------------------------------
section "Step 10: Remove Jupyter / IPython checkpoints and output cells"
# ---------------------------------------------------------------------------
find /opt /home /root /srv -type d -name ".ipynb_checkpoints" \
     -exec rm -rf {} + 2>/dev/null || true
# Strip output from notebooks to reclaim space (outputs can be MBs of data)
if command -v jupyter &>/dev/null; then
    find /opt /home /root /srv -name "*.ipynb" 2>/dev/null | while read -r nb; do
        jupyter nbconvert --ClearOutputPreprocessor.enabled=True \
                          --to notebook --inplace "$nb" 2>/dev/null || true
    done
fi
info "Jupyter checkpoints and notebook outputs cleaned"

# ---------------------------------------------------------------------------
section "Step 11: Remove Python build artefacts"
# ---------------------------------------------------------------------------
find /opt /home /root /srv -type d \( -name "dist" -o -name "build" -o -name "*.egg-info" \) \
     -not -path "$BOT_DIR/src/*" \
     -exec rm -rf {} + 2>/dev/null || true
info "Build artefacts removed"

# ---------------------------------------------------------------------------
section "Step 12: Remove old log files"
# ---------------------------------------------------------------------------
# Remove compressed/rotated logs older than 7 days
find /var/log -name "*.gz" -mtime +7 -delete 2>/dev/null || true
find /var/log -name "*.1" -mtime +7 -delete 2>/dev/null || true
find /var/log -name "*.2" -delete 2>/dev/null || true
find /var/log -name "*.3" -delete 2>/dev/null || true
find /var/log -name "*.4" -delete 2>/dev/null || true
# Truncate (not delete) large active log files to keep logging working.
# Use truncate(1) which is atomic and avoids a temp-file on a full disk.
for logfile in /var/log/trading-bot/*.log /var/log/syslog /var/log/auth.log; do
    [ -f "$logfile" ] || continue
    sz_kb=$(du -k "$logfile" 2>/dev/null | cut -f1)
    if [ "${sz_kb:-0}" -gt 51200 ]; then   # > 50 MB
        step "  Truncating large log: $logfile (${sz_kb} KB → 5 MB)"
        truncate -s 5M "$logfile" 2>/dev/null || true
    fi
done
info "Old/large log files cleaned"

# ---------------------------------------------------------------------------
section "Step 13: Docker — full cleanup (all unused images, containers, volumes)"
# ---------------------------------------------------------------------------
if command -v docker &>/dev/null; then
    step "Stopping all running Docker containers..."
    RUNNING_CONTAINERS=$(docker ps -q 2>/dev/null || true)
    if [ -n "$RUNNING_CONTAINERS" ]; then
        echo "$RUNNING_CONTAINERS" | xargs docker stop 2>/dev/null || true
    fi

    step "Removing all stopped/exited containers..."
    docker container prune -f 2>/dev/null || true

    step "Removing ALL unused Docker images (not just dangling)..."
    docker image prune -af 2>/dev/null || true

    step "Pruning Docker build cache..."
    docker builder prune -af 2>/dev/null || \
        warn "docker builder prune failed (Docker version too old?)"

    step "Pruning unused Docker volumes..."
    docker volume prune -f 2>/dev/null || true

    step "Pruning unused Docker networks..."
    docker network prune -f 2>/dev/null || true

    info "Docker cleanup complete"
else
    warn "Docker not found — skipping Docker cleanup"
fi

# ---------------------------------------------------------------------------
section "Step 14: ML model files (PRESERVED)"
# ---------------------------------------------------------------------------
if [ -d "$MODEL_DIR" ]; then
    MODEL_SIZE=$(du -sh "$MODEL_DIR" 2>/dev/null | cut -f1)
    info "ML models directory PRESERVED: $MODEL_SIZE  ($MODEL_DIR)"
    info "  (trained AI knowledge — these files are NOT removed)"
else
    info "No models directory found at $MODEL_DIR — will be created on first training run"
fi

# ---------------------------------------------------------------------------
section "Disk usage after cleanup"
# ---------------------------------------------------------------------------
df -h / /opt /var /tmp 2>/dev/null || df -h
echo ""
FREE_MB=$(df -m / 2>/dev/null | tail -1 | awk '{print $4}')
echo -e "${GREEN}Free space on /: ${FREE_MB} MB${NC}"

echo ""
echo "======================================================="
echo -e "${GREEN}Cleanup complete!${NC}"
echo "======================================================="
echo ""
echo "PRESERVED (bot code + AI knowledge):"
echo "  $BOT_DIR/src/          — source code"
echo "  $BOT_DIR/scripts/      — bot scripts"
echo "  $BOT_DIR/models/       — trained ML model weights"
echo "  $BOT_DIR/config.yaml, .env"
echo "  /var/lib/trading-bot/  — runtime DB / positions"
echo ""
echo "REMOVED:"
echo "  venv (auto-rebuilt on next start)"
echo "  External venvs, old bot copies, build artefacts"
echo "  All Docker images + containers + volumes + build cache"
echo "  pip/apt/journal/tmp/log caches"
echo ""
if [ "${FREE_MB:-0}" -lt 800 ]; then
    warn "Still less than 800 MB free! Check large directories:"
    du -sh /opt/* /var/* /home/* /root /tmp 2>/dev/null | sort -hr | head -20
    echo ""
    warn "Additional actions you can take:"
    echo "  # Remove unused kernels:  apt-get autoremove --purge"
    echo "  # Find largest files:     find / -xdev -size +100M -ls 2>/dev/null | sort -k7 -rn | head -20"
fi
echo ""
echo "To rebuild the venv and restart the bot:"
echo "  sudo systemctl restart trading-bot"
echo "  sudo journalctl -u trading-bot -f"
