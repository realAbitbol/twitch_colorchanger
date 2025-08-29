#!/bin/bash
# Twitch Color Changer Bot - Unix/Linux/macOS Startup Script
# This script helps you start the bot easily on Unix-like systems

echo "Starting Twitch Color Changer Bot..."
echo

# Check if Python is installed
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "Error: Python is not installed or not in PATH"
    echo "Please install Python 3.8+ from your package manager or https://python.org"
    exit 1
fi

# Determine Python command and check for virtual environment
if [ -d ".venv" ]; then
    echo "Using virtual environment..."
    PYTHON_CMD=".venv/bin/python"
    if [ ! -f "$PYTHON_CMD" ]; then
        echo "Error: Virtual environment exists but Python executable not found"
        echo "Try recreating the virtual environment:"
        echo "  rm -rf .venv"
        echo "  python3 -m venv .venv"
        exit 1
    fi
elif command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
else
    PYTHON_CMD="python"
fi

# Check Python version (only if not using venv, as venv Python is assumed to be correct)
if [ ! -d ".venv" ]; then
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    MAJOR_VERSION=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR_VERSION=$(echo $PYTHON_VERSION | cut -d. -f2)

    if [ "$MAJOR_VERSION" -lt 3 ] || ([ "$MAJOR_VERSION" -eq 3 ] && [ "$MINOR_VERSION" -lt 8 ]); then
        echo "Error: Python 3.8+ is required, but found Python $PYTHON_VERSION"
        echo "Please update your Python installation"
        exit 1
    fi
fi

# Check if config file exists
if [ ! -f "twitch_colorchanger.conf" ]; then
    echo "Error: Configuration file not found!"
    echo "Please copy twitch_colorchanger.conf-sample to twitch_colorchanger.conf"
    echo "and configure it with your settings."
    echo
    echo "Quick setup:"
    echo "  cp twitch_colorchanger.conf-sample twitch_colorchanger.conf"
    echo "  nano twitch_colorchanger.conf  # or your preferred editor"
    exit 1
fi

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "Installing/updating dependencies..."
    
    # If we're already using a venv, just install directly
    if [ -d ".venv" ]; then
        .venv/bin/pip install -r requirements.txt
    elif command -v pip3 &> /dev/null; then
        # Try pip3 with user install as fallback
        pip3 install --user -r requirements.txt 2>/dev/null || {
            echo "Note: Could not install system-wide. Creating virtual environment..."
            $PYTHON_CMD -m venv .venv
            echo "Virtual environment created in .venv"
            echo "Installing dependencies in new virtual environment..."
            .venv/bin/pip install -r requirements.txt
            PYTHON_CMD=".venv/bin/python"
            echo "Updated to use virtual environment Python"
        }
    elif command -v pip &> /dev/null; then
        # Try pip with user install as fallback
        pip install --user -r requirements.txt 2>/dev/null || {
            echo "Note: Could not install system-wide. Creating virtual environment..."
            $PYTHON_CMD -m venv .venv
            echo "Virtual environment created in .venv" 
            echo "Installing dependencies in new virtual environment..."
            .venv/bin/pip install -r requirements.txt
            PYTHON_CMD=".venv/bin/python"
            echo "Updated to use virtual environment Python"
        }
    else
        echo "Warning: pip not found. You may need to install dependencies manually"
        echo "Dependencies: aiohttp, watchdog"
    fi
    echo
fi

# Start the bot
echo "Starting the bot..."
$PYTHON_CMD main.py

# Check exit status
if [ $? -ne 0 ]; then
    echo
    echo "Bot exited with an error. Check the output above."
    read -p "Press Enter to continue..."
fi
