#!/usr/bin/env bash
# setup_dev.sh - Development environment setup script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "============================================"
echo "  Trading Bot - Development Environment Setup"
echo "============================================"

# Check Python version
PYTHON_MIN="3.9"
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Python $PYTHON_VERSION detected"

if python3 -c "import sys; exit(0 if sys.version_info >= (3, 9) else 1)"; then
  echo "✓ Python version OK (>= $PYTHON_MIN)"
else
  echo "✗ Python $PYTHON_MIN+ required"
  exit 1
fi

cd "$ROOT_DIR"

# Create and activate virtual environment
if [ ! -d "venv" ]; then
  echo ""
  echo "Creating virtual environment..."
  python3 -m venv venv
  echo "✓ Virtual environment created"
else
  echo "✓ Virtual environment already exists"
fi

# Activate venv
# shellcheck disable=SC1091
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip setuptools wheel -q
echo "✓ pip upgraded"

# Install production dependencies
echo ""
echo "Installing production dependencies..."
pip install -r requirements.txt -q
echo "✓ Production dependencies installed"

# Install test/dev dependencies
echo ""
echo "Installing development dependencies..."
pip install -r requirements-test.txt -q
pip install black flake8 mypy pylint bandit safety isort pre-commit -q
echo "✓ Development dependencies installed"

# Setup pre-commit hooks
echo ""
echo "Setting up pre-commit hooks..."
if command -v pre-commit &>/dev/null; then
  pre-commit install 2>/dev/null || echo "  (pre-commit hooks skipped - .pre-commit-config.yaml not found)"
  echo "✓ Pre-commit hooks installed"
fi

# Create necessary directories
echo ""
echo "Creating directories..."
mkdir -p logs reports models data
echo "✓ Directories created"

# Copy .env template if .env doesn't exist
if [ ! -f ".env" ]; then
  if [ -f ".env.template.secure" ]; then
    cp .env.template.secure .env
    echo "✓ .env file created from template - please edit it with your API keys"
  fi
fi

# Initialize config if needed
if [ ! -f "config.yaml" ]; then
  echo "⚠ config.yaml not found - using defaults"
fi

# Run a quick test to verify setup
echo ""
echo "Running quick verification..."
python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from src.risk_manager import RiskManager
    from src.sentiment import SentimentAnalyzer
    print('✓ Core modules import OK')
except Exception as e:
    print(f'⚠ Import warning: {e}')
"

echo ""
echo "============================================"
echo "  Setup Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Edit .env with your API keys"
echo "  2. Run: source venv/bin/activate"
echo "  3. Run: make test            (run tests)"
echo "  4. Run: make run             (start bot)"
echo "  5. Run: make docker-up-dev   (start with Docker)"
echo ""
