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
REPO_URL="https://github.com/donganhhuynh405-a11y/Life_Is_A_Joke.git"
REPO_DIR="$HOME/trading-bot-setup/life_is_a_joke"
BOT_DIR="/opt/Life_Is_A_Joke"
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
    git clone "$REPO_URL" "$REPO_DIR"
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

# Step 5: Checkout and pull the target branch
if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    print_status "Switching to branch: $BRANCH"
    git checkout "$BRANCH"
fi

print_status "Pulling latest changes..."
git pull origin "$BRANCH"
print_success "Repository updated to latest version"

# Step 6: Copy files to bot directory
print_status "Copying updated files to bot directory: $BOT_DIR"
if [ ! -d "$BOT_DIR" ]; then
    print_warning "Bot directory doesn't exist, creating it..."
    mkdir -p "$BOT_DIR"
fi

# Copy all files except .git directory
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' "$REPO_DIR/" "$BOT_DIR/"
print_success "Files copied successfully"

# Step 7: Set correct ownership
print_status "Setting correct file ownership..."
if id "tradingbot" &>/dev/null; then
    chown -R tradingbot:tradingbot "$BOT_DIR"
    print_success "Ownership set to tradingbot:tradingbot"
else
    print_warning "User 'tradingbot' not found, skipping ownership change"
    print_warning "If you have a different user for the bot, please update manually"
fi

# Step 8: Clean up Python cache files
print_status "Cleaning up Python cache files..."
find "$BOT_DIR" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find "$BOT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
print_success "Cache files cleaned"

# Step 9: Show git commit info
print_status "Current version information:"
cd "$REPO_DIR"
COMMIT_HASH=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --pretty=%B | head -n 1)
COMMIT_DATE=$(git log -1 --pretty=%ci)
echo "  Commit: $COMMIT_HASH"
echo "  Message: $COMMIT_MSG"
echo "  Date: $COMMIT_DATE"

# Step 10: Start the trading bot service
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

# Step 11: Show service status
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
