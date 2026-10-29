@echo off
title Dungeon Blitz Bot Launcher
cd /d "%~dp0"
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred running the bot. Press any key to exit.
    pause >nul
)
