#!/bin/bash
set -e

echo "=========================================="
echo "Development Environment Setup"
echo "=========================================="

# Check Python version
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.11"

if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"; then
    echo "Error: Python 3.11 or higher is required (found $PYTHON_VERSION)"
    exit 1
fi

echo "✓ Python version: $PYTHON_VERSION"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
if [ -f "requirements.txt" ]; then
    pip install -r requirements.txt
    echo "✓ Dependencies installed"
else
    echo "Warning: requirements.txt not found"
fi

# Install development dependencies
echo "Installing development dependencies..."
pip install pytest pytest-cov black flake8

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✓ .env file created"
    echo "⚠️  Please update .env with your configuration"
else
    echo "✓ .env file already exists"
fi

echo ""
echo "=========================================="
echo "Setup complete!"
echo "=========================================="
echo ""
echo "To activate the virtual environment, run:"
echo "  source venv/bin/activate"
echo ""
echo "To run the application:"
echo "  python -m src.main"
echo ""
echo "To run tests:"
echo "  pytest tests/"
