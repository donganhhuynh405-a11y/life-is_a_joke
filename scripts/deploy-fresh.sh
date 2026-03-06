#!/bin/bash
set -e

echo "======================================================="
echo "TRADING BOT - FRESH DEPLOYMENT"
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

# Step 1: Stop bot
print_info "Step 1/8: Stopping bot..."
systemctl stop trading-bot 2>/dev/null || true
sleep 2
print_info "   ✅ Stopped"
echo ""

# Step 2: Create backup with timestamp
print_info "Step 2/8: Creating backup..."
cd /opt
if [ -d "Life_Is_A_Joke" ]; then
    TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    BACKUP_DIR="Life_Is_A_Joke.backup.$TIMESTAMP"
    mv Life_Is_A_Joke "$BACKUP_DIR"
    print_info "   ✅ Backup created: $BACKUP_DIR"
else
    print_warning "   No existing installation to backup"
fi
echo ""

# Step 3: Clone repository
print_info "Step 3/8: Cloning repository..."
git clone -b copilot/update-notification-format https://github.com/donganhhuynh405-a11y/Life_Is_A_Joke.git Life_Is_A_Joke
cd Life_Is_A_Joke
print_info "   ✅ Repository cloned"
echo ""

# Step 4: Restore .env
print_info "Step 4/8: Restoring configuration..."
LATEST_BACKUP=$(ls -td /opt/Life_Is_A_Joke.backup* 2>/dev/null | head -1)
if [ -n "$LATEST_BACKUP" ] && [ -f "$LATEST_BACKUP/.env" ]; then
    cp "$LATEST_BACKUP/.env" .
    print_info "   ✅ .env restored from $LATEST_BACKUP"
else
    print_warning "   No .env found - you'll need to configure manually"
    print_warning "   Copy from: cp /opt/Life_Is_A_Joke.backup*/.env /opt/Life_Is_A_Joke/"
fi
echo ""

# Step 5: Create venv
print_info "Step 5/8: Creating virtual environment..."
python3 -m venv venv
print_info "   ✅ venv created"
echo ""

# Step 6: Install dependencies
print_info "Step 6/8: Installing dependencies..."
venv/bin/pip install --upgrade pip > /dev/null 2>&1
venv/bin/pip install -r requirements.txt > /dev/null 2>&1
print_info "   ✅ Dependencies installed"
echo ""

# Step 7: Set permissions
print_info "Step 7/8: Setting permissions..."
chown -R root:root /opt/Life_Is_A_Joke
chmod +x scripts/*.sh 2>/dev/null || true
chmod +x scripts/*.py 2>/dev/null || true
print_info "   ✅ Permissions set"
echo ""

# Step 8: Start bot
print_info "Step 8/8: Starting bot..."
systemctl start trading-bot
sleep 3

if systemctl is-active --quiet trading-bot; then
    PID=$(systemctl show -p MainPID trading-bot | cut -d= -f2)
    print_info "   ✅ Bot is running (PID: $PID)"
    echo ""
    echo "======================================================="
    echo -e "${GREEN}SUCCESS! Fresh deployment complete.${NC}"
    echo "======================================================="
    echo ""
    echo "Status: sudo systemctl status trading-bot"
    echo "Logs:   sudo journalctl -u trading-bot -f"
else
    print_error "   Bot failed to start"
    echo ""
    echo "Check logs: sudo journalctl -u trading-bot -n 50"
    exit 1
fi
