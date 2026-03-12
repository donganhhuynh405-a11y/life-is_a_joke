#!/bin/bash

################################################################################
# Trading Bot Update Script
# 
# This script automates the process of updating the trading bot on the server
# with the latest code from the repository.
#
# Usage:
#   chmod +x scripts/update_bot.sh
#   ./scripts/update_bot.sh
#
# Or with sudo if needed:
#   sudo ./scripts/update_bot.sh
################################################################################

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
REPO_URL="https://github.com/donganhhuynh405-a11y/life-is_a_joke.git"
REPO_DIR="/opt/trading-bot"
BOT_DIR="/opt/trading-bot"
SERVICE_NAME="trading-bot"
BRANCH="main"  # Default to stable branch; override with --branch for PR/feature branches

print_usage() {
    echo "Usage: $0 [--branch <branch_name>]"
    echo
    echo "Options:"
    echo "  --branch, -b   Specify the git branch to deploy."
}

# Parse optional --branch argument so the user can deploy a specific PR branch.
# Usage: sudo ./scripts/update_bot.sh --branch main
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --branch|-b)
            if [[ -z "$2" ]]; then
                echo "Error: --branch requires a non-empty <branch_name> argument."
                print_usage
                exit 1
            fi
            BRANCH="$2"
            shift
            ;;
        *)
            echo "Unknown parameter: $1. Use --branch <branch_name> to specify a branch."
            print_usage
            exit 1
            ;;
    esac
    shift
done

# Print colored message
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Print header
echo "================================================================================"
echo "                    TRADING BOT UPDATE SCRIPT                                  "
echo "================================================================================"
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then 
    print_warning "This script requires root privileges to update the bot."
    print_warning "Please run with sudo: sudo $0"
    exit 1
fi

# Step 1: Stop the trading bot service
print_status "Stopping trading bot service..."
if systemctl is-active --quiet "$SERVICE_NAME"; then
    systemctl stop "$SERVICE_NAME"
    print_success "Trading bot service stopped"
else
    print_warning "Trading bot service was not running"
fi

# Step 2: Navigate to repository directory or clone it
print_status "Checking repository directory: $REPO_DIR"
if [ ! -d "$REPO_DIR" ]; then
    print_warning "Repository directory not found, cloning it..."
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone -b "$BRANCH" "$REPO_URL" "$REPO_DIR"
    print_success "Repository cloned successfully"
fi

cd "$REPO_DIR"
print_success "Changed to repository directory"

# Step 3: Fetch latest changes
print_status "Fetching latest changes from remote..."
git fetch origin

# Step 4: Check current branch
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
print_status "Current branch: $CURRENT_BRANCH"

# Step 4a: Stash any local modifications so git pull cannot fail due to conflicts
# Use git status --porcelain to detect ALL local changes (modified, staged, untracked)
if [ -z "$(git status --porcelain)" ]; then
    print_status "No local changes to stash"
else
    print_warning "Local changes detected — stashing them so the pull can proceed..."
    if git stash push --include-untracked -m "Auto-stash before update $(date)"; then
        print_success "Local changes stashed"
    else
        print_error "git stash failed.  Cannot safely pull without losing local changes."
        print_error "Please manually commit or discard your local changes and re-run this script:"
        print_error "  git status  (to see what changed)"
        print_error "  git stash   (to save changes)"
        print_error "  git checkout -- <file>  (to discard a specific file)"
        exit 1
    fi
fi

# Step 5: Checkout and pull the target branch
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    print_status "Switching to branch: $BRANCH"
    git checkout "$BRANCH"
fi

print_status "Pulling latest changes..."
git pull origin "$BRANCH"
print_success "Repository updated to latest version"

# Step 5a: Ensure all scripts in the repo are executable
print_status "Ensuring scripts are executable..."
chmod +x "$REPO_DIR"/scripts/*.sh 2>/dev/null || true
print_success "Script permissions set"

# Step 5b: Update the installed systemd service file to match the repo
SERVICE_SRC="$REPO_DIR/deployment/systemd/trading-bot.service"
SERVICE_DST="/etc/systemd/system/trading-bot.service"
if [ -f "$SERVICE_SRC" ]; then
    if ! diff -q "$SERVICE_SRC" "$SERVICE_DST" > /dev/null 2>&1; then
        print_status "Updating systemd service file..."
        cp "$SERVICE_SRC" "$SERVICE_DST"
        systemctl daemon-reload
        print_success "systemd service file updated and daemon reloaded"
    else
        print_status "systemd service file is already up to date"
    fi
fi

# Step 6: Clean Python cache files
print_status "Cleaning Python cache files..."
find "$BOT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$BOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
print_success "Cache files cleaned"

# Step 6a: Ensure the virtual environment exists and install/update dependencies
VENV_PYTHON="$BOT_DIR/venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    print_warning "Virtual environment not found or python3 missing — creating venv..."
    python3 -m venv "$BOT_DIR/venv"
    print_success "Virtual environment created"
fi
print_status "Updating Python dependencies..."
# Do NOT run 'pip install --upgrade pip': unnecessary at update time and it
# overwrites the pip binary which can fail with permission errors when the venv
# is owned by a different user.
"$BOT_DIR/venv/bin/pip" install -r "$BOT_DIR/requirements.txt" --quiet
# Record the stamp so start_bot.sh does not re-attempt pip install on startup.
sha256sum "$BOT_DIR/requirements.txt" > "$BOT_DIR/venv/.requirements_installed" 2>/dev/null || true
print_success "Python dependencies installed"

# Step 7: Set correct ownership
print_status "Setting correct file ownership..."
if id "tradingbot" &>/dev/null; then
    chown -R tradingbot:tradingbot "$BOT_DIR"
    print_success "Ownership set to tradingbot:tradingbot"
else
    print_warning "User 'tradingbot' not found, skipping ownership change"
    print_warning "If you have a different user for the bot, please update manually"
fi

# Step 8: Show git commit info
print_status "Current version information:"
COMMIT_HASH=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --pretty=%B | head -n 1)
COMMIT_DATE=$(git log -1 --pretty=%ci)
echo "  Commit: $COMMIT_HASH"
echo "  Message: $COMMIT_MSG"
echo "  Date: $COMMIT_DATE"

# Step 9: Start the trading bot service
print_status "Starting trading bot service..."
systemctl start "$SERVICE_NAME"

# Wait a moment for service to start
sleep 2

# Check if service started successfully
if systemctl is-active --quiet "$SERVICE_NAME"; then
    print_success "Trading bot service started successfully"
else
    print_error "Failed to start trading bot service"
    print_error "Check status with: sudo systemctl status $SERVICE_NAME"
    print_error "Check logs with: sudo journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

# Step 10: Show service status
print_status "Service status:"
systemctl status "$SERVICE_NAME" --no-pager -l | head -n 15

echo ""
echo "================================================================================"
print_success "Trading bot update completed successfully!"
echo "================================================================================"
echo ""
print_status "Useful commands:"
echo "  View logs:        sudo journalctl -u $SERVICE_NAME -f"
echo "  Stop bot:         sudo systemctl stop $SERVICE_NAME"
echo "  Start bot:        sudo systemctl start $SERVICE_NAME"
echo "  Restart bot:      sudo systemctl restart $SERVICE_NAME"
echo "  Check status:     sudo systemctl status $SERVICE_NAME"
echo "  Diagnose:         cd $REPO_DIR && python3 scripts/diagnose_positions.py"
echo ""
