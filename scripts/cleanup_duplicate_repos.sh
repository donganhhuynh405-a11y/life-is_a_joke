#!/bin/bash
#
# cleanup_duplicate_repos.sh
#
# Removes duplicate/stale git repository copies from the server while keeping
# backups (directories whose name contains "backup").
#
# The canonical installation is /opt/trading-bot.  All other non-backup clones
# are considered duplicates (e.g. /opt/Life_Is_A_Joke, /root/life_is_a_joke,
# /opt/Life_Is_A_Joke/life-is_a_joke, etc.)
#
# After cleanup the script fetches the latest code from the main branch of
# https://github.com/donganhhuynh405-a11y/life-is_a_joke into /opt/trading-bot.
#
# Usage:
#   sudo bash scripts/cleanup_duplicate_repos.sh
#

set -e

REPO_URL="https://github.com/donganhhuynh405-a11y/life-is_a_joke.git"
BRANCH="main"
ACTIVE_DIR="/opt/trading-bot"
SERVICE_NAME="trading-bot"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
print_ok()      { echo -e "${GREEN}[OK]${NC}   $1"; }
print_warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
print_error()   { echo -e "${RED}[ERR]${NC}  $1"; }

# ── root check ────────────────────────────────────────────────────────────────
if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root or with sudo"
    exit 1
fi

echo "========================================================"
echo "  Trading Bot – Cleanup Duplicate Repositories"
echo "========================================================"
echo ""

# ── Step 1: discover all .git directories ─────────────────────────────────────
print_info "Step 1/4: Scanning for all git repositories on the server..."
echo ""
mapfile -t ALL_GIT < <(find /opt /root -name ".git" -type d 2>/dev/null | sort)

echo "  Found repositories:"
for g in "${ALL_GIT[@]}"; do
    repo_dir="${g%/.git}"
    branch=$(git -C "$repo_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "?")
    commit=$(git -C "$repo_dir" rev-parse --short HEAD 2>/dev/null || echo "?")
    echo "    $repo_dir  [branch: $branch, commit: $commit]"
done
echo ""

# ── Step 2: classify each repo ────────────────────────────────────────────────
print_info "Step 2/4: Classifying repositories..."
echo ""
declare -a TO_REMOVE=()

for g in "${ALL_GIT[@]}"; do
    repo_dir="${g%/.git}"

    # Always keep the active installation
    if [ "$repo_dir" = "$ACTIVE_DIR" ]; then
        print_ok "  KEEP (active)  $repo_dir"
        continue
    fi

    # Keep anything whose path contains the word "backup"
    if echo "$repo_dir" | grep -qi "backup"; then
        print_ok "  KEEP (backup)  $repo_dir"
        continue
    fi

    # Everything else is a duplicate
    print_warn "  REMOVE (dup)   $repo_dir"
    TO_REMOVE+=("$repo_dir")
done

echo ""

if [ ${#TO_REMOVE[@]} -eq 0 ]; then
    print_ok "No duplicate repositories found. Nothing to remove."
    echo ""
else
    echo "  The following directories will be PERMANENTLY DELETED:"
    for d in "${TO_REMOVE[@]}"; do
        echo "    - $d"
    done
    echo ""
    read -rp "  Proceed? (yes/no): " CONFIRM
    CONFIRM_LC=$(echo "$CONFIRM" | tr '[:upper:]' '[:lower:]')
    if [ "$CONFIRM_LC" != "yes" ] && [ "$CONFIRM_LC" != "y" ]; then
        print_warn "Aborted by user. Nothing was deleted."
        exit 0
    fi
    echo ""

    for d in "${TO_REMOVE[@]}"; do
        print_info "  Removing $d ..."
        rm -rf "$d"
        print_ok "  Removed $d"
    done
    echo ""
fi

# ── Step 3: ensure active bot directory is up to date ─────────────────────────
print_info "Step 3/4: Updating $ACTIVE_DIR from $BRANCH branch..."
echo ""

if [ -d "$ACTIVE_DIR/.git" ]; then
    print_info "  Repository exists – fetching latest changes..."
    cd "$ACTIVE_DIR"
    git fetch origin
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
    if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
        print_info "  Switching from '$CURRENT_BRANCH' to '$BRANCH'..."
        git checkout "$BRANCH"
    fi
    git pull origin "$BRANCH"
    print_ok "  Updated to: $(git log --oneline -1)"
else
    print_info "  $ACTIVE_DIR is not a git repository – cloning fresh..."
    mkdir -p "$(dirname "$ACTIVE_DIR")"
    # Preserve .env if it exists (from a previous non-git installation)
    if [ -f "$ACTIVE_DIR/.env" ]; then
        cp "$ACTIVE_DIR/.env" /tmp/trading-bot-env-backup
        print_info "  .env saved to /tmp/trading-bot-env-backup"
    fi
    rm -rf "$ACTIVE_DIR"
    git clone -b "$BRANCH" "$REPO_URL" "$ACTIVE_DIR"
    if [ -f /tmp/trading-bot-env-backup ]; then
        cp /tmp/trading-bot-env-backup "$ACTIVE_DIR/.env"
        rm -f /tmp/trading-bot-env-backup
        print_ok "  .env restored"
    fi
    print_ok "  Cloned: $(git -C "$ACTIVE_DIR" log --oneline -1)"
fi
echo ""

# ── Step 4: restart the bot ───────────────────────────────────────────────────
print_info "Step 4/4: Restarting the trading bot service..."
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    systemctl restart "$SERVICE_NAME"
else
    systemctl start "$SERVICE_NAME" 2>/dev/null || print_warn "  Service not configured – start it manually."
fi
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
    print_ok "  Bot is running"
else
    print_warn "  Bot did not start. Check: sudo journalctl -u $SERVICE_NAME -n 30"
fi
echo ""

echo "========================================================"
print_ok "Cleanup complete!"
echo "========================================================"
echo ""
echo "  Active installation : $ACTIVE_DIR"
echo "  Branch              : $BRANCH"
echo "  Commit              : $(git -C "$ACTIVE_DIR" log --oneline -1)"
echo ""
echo "  Useful commands:"
echo "    sudo journalctl -u $SERVICE_NAME -f       # live logs"
echo "    sudo systemctl status $SERVICE_NAME        # service status"
echo "    sudo bash $ACTIVE_DIR/scripts/deploy-update.sh  # update from main"
echo ""
