@echo off
cd /d "%~dp0"
title IBKR Trading Bot - automatic TWS login setup
if not exist ".venv\Scripts\python.exe" (
  echo Run SETUP.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" setup_autologin.py
