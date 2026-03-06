#!/bin/bash

# Installation script for Trading Bot

set -e

echo "📦 Installing Trading Bot..."
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed!"
    echo "Please install Python 3 first:"
    echo "  Ubuntu/Debian: sudo apt-get install python3 python3-pip"
    exit 1
fi

# Install Python dependencies
echo "📥 Installing Python dependencies..."
pip3 install -r requirements.txt

# Create necessary directories
echo "📁 Creating necessary directories..."
mkdir -p logs data configs backups

# Copy environment template
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp .env.template .env
    echo "⚠️  Please edit .env file with your API keys and configuration"
fi

echo ""
echo "✅ Installation complete!"
echo ""
echo "📚 Next steps:"
echo "  1. Configure settings:"
echo "     nano .env"
echo ""
echo "  2. Run the bot:"
echo "     python3 -m src.main"
echo ""
echo "  3. Or use other scripts:"
echo "     python3 scripts/test_connectivity.py  # Test exchange connection"
echo "     python3 scripts/health_check.py       # Check bot health"
echo ""
