#!/bin/bash
set -e

echo "======================================================="
echo "FIXING CURRENT DEPLOYMENT ERRORS"
echo "======================================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Step 1: Stop the bot
print_info "Step 1/6: Stopping bot..."
sudo systemctl stop trading-bot 2>/dev/null || true
sleep 2
print_info "   ✅ Bot stopped"
echo ""

# Step 2: Analyze current situation
print_info "Step 2/6: Analyzing current situation..."
cd /opt

if [ -d "trading-bot" ]; then
    print_info "   Found: /opt/trading-bot"
fi

if [ -d "trading-bot.backup" ]; then
    print_info "   Found: /opt/trading-bot.backup"
fi

# Check for incomplete clone
if [ -d "trading-bot" ] && [ ! -f "trading-bot/requirements.txt" ]; then
    print_warning "   trading-bot directory is incomplete (failed clone)"
fi
echo ""

# Step 3: Clean up failed deployment
print_info "Step 3/6: Cleaning up failed deployment..."

# Remove incomplete trading-bot if it exists
if [ -d "trading-bot" ] && [ ! -f "trading-bot/requirements.txt" ]; then
    print_info "   Removing incomplete trading-bot..."
    sudo rm -rf trading-bot
    print_info "   ✅ Removed"
fi

# If trading-bot exists and is complete, create backup with timestamp
if [ -d "trading-bot" ] && [ -f "trading-bot/requirements.txt" ]; then
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    print_info "   Creating backup: trading-bot.backup.$TIMESTAMP"
    sudo mv trading-bot "trading-bot.backup.$TIMESTAMP"
    print_info "   ✅ Backup created"
fi
echo ""

# Step 4: Prepare for fresh deployment
print_info "Step 4/6: Preparing for fresh deployment..."
cd /opt

# Find the most recent backup to restore .env from
LATEST_BACKUP=$(ls -td trading-bot.backup* 2>/dev/null | head -1)
if [ -n "$LATEST_BACKUP" ]; then
    print_info "   Will restore .env from: $LATEST_BACKUP"
fi
echo ""

# Step 5: Clone fresh code
print_info "Step 5/6: Cloning fresh code..."
sudo git clone -b main https://github.com/donganhhuynh405-a11y/life-is_a_joke.git trading-bot
cd trading-bot

print_info "   ✅ Code cloned"
echo ""

# Step 6: Setup environment
print_info "Step 6/6: Setting up environment..."

# Restore .env if backup exists
if [ -n "$LATEST_BACKUP" ] && [ -f "/opt/$LATEST_BACKUP/.env" ]; then
    print_info "   Restoring .env..."
    sudo cp "/opt/$LATEST_BACKUP/.env" .
    print_info "   ✅ .env restored"
else
    print_warning "   No .env found in backup - you'll need to configure manually"
fi

# Create venv
print_info "   Creating virtual environment..."
sudo python3 -m venv venv
print_info "   ✅ venv created"

# Install dependencies
print_info "   Installing dependencies..."
sudo venv/bin/pip install --upgrade pip > /dev/null 2>&1
sudo venv/bin/pip install -r requirements.txt > /dev/null 2>&1
print_info "   ✅ Dependencies installed"

# Set proper permissions
print_info "   Setting permissions..."
sudo chown -R root:root /opt/trading-bot
print_info "   ✅ Permissions set"
echo ""

# Start the bot
print_info "Starting bot..."
sudo systemctl start trading-bot
sleep 3

# Check status
if sudo systemctl is-active --quiet trading-bot; then
    print_info "   ✅ Bot is running"
    echo ""
    echo "======================================================="
    echo -e "${GREEN}SUCCESS! Bot deployed and running.${NC}"
    echo "======================================================="
    echo ""
    echo "Check logs: sudo journalctl -u trading-bot -f"
else
    print_error "   Bot failed to start"
    echo ""
    echo "Check logs: sudo journalctl -u trading-bot -n 50"
    exit 1
fi
