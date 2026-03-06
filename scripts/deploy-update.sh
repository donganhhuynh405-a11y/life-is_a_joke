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

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    print_error "Please run as root or with sudo"
    exit 1
fi

# Check if in trading-bot directory
if [ ! -f "requirements.txt" ]; then
    print_error "Not in trading-bot directory"
    print_info "Run: cd /opt/Life_Is_A_Joke && sudo bash scripts/deploy-update.sh"
    exit 1
fi

# Step 1: Stop bot
print_info "Step 1/6: Stopping bot..."
systemctl stop trading-bot 2>/dev/null || true
sleep 2
print_info "   ✅ Stopped"
echo ""

# Step 2: Clean Python cache
print_info "Step 2/6: Cleaning Python cache..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
print_info "   ✅ Cache cleaned"
echo ""

# Step 3: Stash local changes
print_info "Step 3/6: Saving local changes..."
git stash save "Auto-stash before update $(date)" 2>/dev/null || true
print_info "   ✅ Changes saved"
echo ""

# Step 4: Update code
print_info "Step 4/6: Updating code..."
git fetch origin
git checkout copilot/update-notification-format
git pull origin copilot/update-notification-format
print_info "   ✅ Code updated"
echo ""

# Step 5: Update dependencies
print_info "Step 5/6: Updating dependencies..."
if [ ! -d "venv" ]; then
    print_warning "   venv not found, creating..."
    python3 -m venv venv
fi
venv/bin/pip install --upgrade pip > /dev/null 2>&1
venv/bin/pip install -r requirements.txt > /dev/null 2>&1
print_info "   ✅ Dependencies updated"
echo ""

# Step 6: Start bot
print_info "Step 6/6: Starting bot..."
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
