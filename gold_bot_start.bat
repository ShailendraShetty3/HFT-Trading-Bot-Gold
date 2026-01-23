@echo off
title Gold Trading Bot - Launcher
color 0A

echo ============================================================
echo          GOLD TRADING BOT - AUTOMATED LAUNCHER
echo ============================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    color 0C
    echo [ERROR] Python is not installed or not in PATH!
    echo.
    echo Please install Python 3.8 or higher from:
    echo https://www.python.org/downloads/
    echo.
    echo Make sure to check "Add Python to PATH" during installation!
    echo.
    pause
    exit /b 1
)

echo [OK] Python detected
python --version
echo.

REM Check if requirements.txt exists
if not exist "requirements.txt" (
    color 0E
    echo [WARNING] requirements.txt not found!
    echo Continuing without dependency check...
    echo.
    timeout /t 3 >nul
    goto :check_updates
)

echo [INFO] Checking/Installing dependencies...
echo This may take a moment on first run...
echo.

REM Install or upgrade dependencies silently
pip install -q -r requirements.txt

if %errorlevel% neq 0 (
    color 0E
    echo [WARNING] Some dependencies may not have installed correctly
    echo Attempting to continue anyway...
    echo.
    timeout /t 3 >nul
) else (
    echo [OK] All dependencies ready
    echo.
)

:check_updates
REM Run updater if it exists
if exist "updater.py" (
    python updater.py
    if %errorlevel% neq 0 (
        color 0E
        echo [WARNING] Update check failed, continuing anyway...
        echo.
        timeout /t 2 >nul
    )
) else (
    echo [WARNING] updater.py not found, skipping update check
    echo.
    timeout /t 2 >nul
)

:run_bot
echo ============================================================
echo          STARTING GOLD TRADING BOT
echo ============================================================
echo.
echo [INFO] Bot is launching...
echo [INFO] Make sure MetaTrader 5 is running and logged in!
echo.
timeout /t 2 >nul

REM Run the bot
python gold_bot.py

REM If bot exits, show error message
if %errorlevel% neq 0 (
    color 0C
    echo.
    echo ============================================================
    echo [ERROR] Bot exited with error code: %errorlevel%
    echo ============================================================
    echo.
    echo Common issues:
    echo - MetaTrader 5 is not running or not logged in
    echo - XAUUSD symbol not available in Market Watch
    echo - AutoTrading not enabled in MT5 settings
    echo - Python dependencies not properly installed
    echo.
)

pause