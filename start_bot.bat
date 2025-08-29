@echo off
REM Twitch Color Changer Bot - Windows Startup Script
REM This script helps you start the bot easily on Windows

echo Starting Twitch Color Changer Bot...
echo.

REM Check if virtual environment exists and use it
if exist ".venv\Scripts\python.exe" (
    echo Using virtual environment...
    set PYTHON_CMD=.venv\Scripts\python.exe
    set PIP_CMD=.venv\Scripts\pip.exe
) else (
    REM Check if Python is installed
    python --version >nul 2>&1
    if %errorlevel% neq 0 (
        echo Error: Python is not installed or not in PATH
        echo Please install Python 3.8+ from https://python.org
        pause
        exit /b 1
    )
    set PYTHON_CMD=python
    set PIP_CMD=pip
)

REM Check if config file exists
if not exist "twitch_colorchanger.conf" (
    echo Error: Configuration file not found!
    echo Please copy twitch_colorchanger.conf-sample to twitch_colorchanger.conf
    echo and configure it with your settings.
    pause
    exit /b 1
)

REM Install dependencies if requirements.txt exists
if exist "requirements.txt" (
    echo Installing/updating dependencies...
    
    REM If we're already using a venv, just install directly
    if exist ".venv\Scripts\python.exe" (
        %PIP_CMD% install -r requirements.txt
        if %errorlevel% neq 0 (
            echo Warning: Failed to install dependencies in virtual environment
            echo You may need to recreate the virtual environment
            pause
        )
    ) else (
        REM Try pip install with user flag as fallback
        %PIP_CMD% install --user -r requirements.txt >nul 2>&1
        if %errorlevel% neq 0 (
            echo Note: Could not install system-wide. Creating virtual environment...
            python -m venv .venv
            if %errorlevel% equ 0 (
                echo Virtual environment created in .venv
                echo Installing dependencies in new virtual environment...
                .venv\Scripts\pip.exe install -r requirements.txt
                if %errorlevel% equ 0 (
                    echo Updated to use virtual environment Python
                    set PYTHON_CMD=.venv\Scripts\python.exe
                    set PIP_CMD=.venv\Scripts\pip.exe
                ) else (
                    echo Warning: Failed to install dependencies in new virtual environment
                    pause
                )
            ) else (
                echo Warning: Failed to create virtual environment
                echo You may need to install dependencies manually: aiohttp, watchdog
                pause
            )
        )
    )
    echo.
)

REM Start the bot
echo Starting the bot...
%PYTHON_CMD% main.py

REM Keep window open if there's an error
if %errorlevel% neq 0 (
    echo.
    echo Bot exited with an error. Check the output above.
    pause
)
