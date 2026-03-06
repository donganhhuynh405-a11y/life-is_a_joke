#!/bin/bash
set -e

echo "======================================================="
echo "TRADING BOT - UPDATE DEPLOYMENT"
echo "======================================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Canonical repository URL and branch
CORRECT_REPO_URL="https://github.com/donganhhuynh405-a11y/life-is_a_joke.git"
BRANCH="main"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root or with sudo"
    exit 1
fi

# Check if in trading-bot directory
if [ ! -f "requirements.txt" ]; then
    print_error "Not in trading-bot directory"
    print_info "Run: cd /opt/trading-bot && sudo bash scripts/deploy-update.sh"
    exit 1
fi

# Step 1: Stop bot
print_info "Step 1/7: Stopping bot..."
systemctl stop trading-bot 2>/dev/null || true
sleep 2
print_info "   ✅ Stopped"
echo ""

# Step 2: Fix remote URL if it points to the wrong repository
print_info "Step 2/7: Verifying git remote URL..."
CURRENT_REMOTE=$(git remote get-url origin 2>/dev/null || echo "")
if [ "$CURRENT_REMOTE" != "$CORRECT_REPO_URL" ]; then
    print_warning "   Remote URL is wrong: $CURRENT_REMOTE"
    print_info   "   Fixing remote URL to: $CORRECT_REPO_URL"
    git remote set-url origin "$CORRECT_REPO_URL"
    print_info   "   ✅ Remote URL corrected"
else
    print_info   "   ✅ Remote URL is correct: $CURRENT_REMOTE"
fi
echo ""

# Step 3: Clean Python cache
print_info "Step 3/7: Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
print_info "   ✅ Cache cleaned"
echo ""

# Step 4: Stash local changes (including config.yaml and any other modified files)
print_info "Step 4/7: Saving local changes..."
# 'git stash push --include-untracked' requires git ≥ 2.13.
# If nothing is to stash, git still exits 0 on modern git; the || true handles
# older versions that may exit 1 when there is nothing to stash.
if git stash push --include-untracked -m "Auto-stash before update $(date)" 2>/dev/null; then
    print_info "   ✅ Local changes stashed"
else
    print_info "   ✅ No local changes to stash"
fi
echo ""

# Step 5: Update code from the correct remote and branch
print_info "Step 5/7: Updating code from $CORRECT_REPO_URL ($BRANCH)..."
git fetch origin
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    print_info "   Switching branch: $CURRENT_BRANCH → $BRANCH"
    git checkout "$BRANCH"
fi
git pull origin "$BRANCH"
print_info "   ✅ Code updated to: $(git log --oneline -1)"
echo ""

# Step 6: Update dependencies
print_info "Step 6/7: Updating dependencies..."
if [ ! -d "venv" ]; then
    print_warning "   venv not found, creating..."
    python3 -m venv venv
fi
venv/bin/pip install --upgrade pip > /dev/null 2>&1
venv/bin/pip install -r requirements.txt > /dev/null 2>&1
print_info "   ✅ Dependencies updated"
echo ""

# Step 7: Start bot
print_info "Step 7/7: Starting bot..."
systemctl start trading-bot
sleep 3

if systemctl is-active --quiet trading-bot; then
    PID=$(systemctl show -p MainPID trading-bot | cut -d= -f2)
    print_info "   ✅ Bot is running (PID: $PID)"
    echo ""
    echo "======================================================="
    echo -e "${GREEN}SUCCESS! Update complete.${NC}"
    echo "======================================================="
    echo ""
    echo "Status: sudo systemctl status trading-bot"
    echo "Logs:   sudo journalctl -u trading-bot -f"
    echo ""
    # Show last 10 log lines
    print_info "Recent logs:"
    journalctl -u trading-bot -n 10 --no-pager
else
    print_error "   Bot failed to start"
    echo ""
    echo "Check logs: sudo journalctl -u trading-bot -n 50"
    exit 1
fi
