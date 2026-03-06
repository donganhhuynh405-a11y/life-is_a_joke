#!/bin/bash
#
# Setup bot-help alias for Trading Bot
# This script adds an alias to run bot_help.py with just "bot-help" command
#

set -e

BOT_DIR="/opt/Life_Is_A_Joke"
ALIAS_NAME="bot-help"
ALIAS_COMMAND="python3 $BOT_DIR/scripts/bot_help.py"

echo "=========================================="
echo "   BOT-HELP ALIAS SETUP"
echo "=========================================="
echo ""

# Check if bot directory exists
if [ ! -d "$BOT_DIR" ]; then
    echo "❌ Error: Bot directory $BOT_DIR not found"
    echo "   Please update BOT_DIR in this script to match your installation"
    exit 1
fi

# Check if bot_help.py exists
if [ ! -f "$BOT_DIR/scripts/bot_help.py" ]; then
    echo "❌ Error: bot_help.py not found at $BOT_DIR/scripts/bot_help.py"
    echo "   Please ensure the bot is properly installed"
    exit 1
fi

echo "📋 Installing alias for current user: $USER"
echo ""

# Determine shell config file
SHELL_CONFIG=""
if [ -n "$BASH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.bashrc"
elif [ -n "$ZSH_VERSION" ]; then
    SHELL_CONFIG="$HOME/.zshrc"
else
    SHELL_CONFIG="$HOME/.bashrc"  # Default to bashrc
fi

echo "📝 Shell config file: $SHELL_CONFIG"
echo ""

# Check if alias already exists
if grep -q "alias $ALIAS_NAME=" "$SHELL_CONFIG" 2>/dev/null; then
    echo "⚠️  Alias '$ALIAS_NAME' already exists in $SHELL_CONFIG"
    echo ""
    echo "Current definition:"
    grep "alias $ALIAS_NAME=" "$SHELL_CONFIG"
    echo ""
    read -p "Do you want to replace it? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Cancelled"
        exit 0
    fi
    # Remove old alias
    sed -i "/alias $ALIAS_NAME=/d" "$SHELL_CONFIG"
fi

# Add alias to config file
echo "" >> "$SHELL_CONFIG"
echo "# Trading Bot Help Menu" >> "$SHELL_CONFIG"
echo "alias $ALIAS_NAME='$ALIAS_COMMAND'" >> "$SHELL_CONFIG"

echo "✅ Alias added to $SHELL_CONFIG"
echo ""
echo "To activate the alias, run:"
echo "  source $SHELL_CONFIG"
echo ""
echo "Or simply open a new terminal session"
echo ""
echo "Then you can use: $ALIAS_NAME"
echo ""

# Offer to activate now
read -p "Activate alias now? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Source the file (note: this only works in the script context)
    source "$SHELL_CONFIG"
    echo "✅ Alias activated!"
    echo ""
    echo "Try it now: $ALIAS_NAME"
else
    echo "Run 'source $SHELL_CONFIG' to activate"
fi

echo ""
echo "=========================================="
echo "   SETUP COMPLETE!"
echo "=========================================="
