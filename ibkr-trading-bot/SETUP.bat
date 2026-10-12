@echo off
setlocal
cd /d "%~dp0"
title IBKR Trading Bot - Setup
echo.
echo  ==========================================
echo    IBKR Trading Bot - one-click setup
echo  ==========================================
echo.

rem ---- 1. Python -------------------------------------------------
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul
if errorlevel 1 goto :nopython
echo  [1/6] Python found.

rem ---- 2. Private Python folder for the bot ----------------------
if exist ".venv\Scripts\python.exe" goto :havevenv
echo  [2/6] Creating the bot's Python folder - about 10 seconds...
python -m venv .venv
if errorlevel 1 goto :fail
:havevenv
echo  [2/6] Bot's Python folder ready.

rem ---- 3. Packages ------------------------------------------------
echo  [3/6] Installing packages - about 1 minute, please wait...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :fail
echo  [3/6] Packages installed.

rem ---- 4. Settings file -------------------------------------------
if not exist ".env" copy ".env.example" ".env" >nul
echo.
echo  [4/6] Notepad will open your settings file.
echo        Fill in TELEGRAM_BOT_TOKEN= and TELEGRAM_CHAT_ID= if you have them,
echo        or leave them empty to do it later.
echo        Then SAVE with Ctrl+S and CLOSE Notepad to continue.
echo.
pause
notepad ".env"

rem ---- 5. Desktop shortcut ----------------------------------------
echo  [5/6] Creating the desktop shortcut...
".venv\Scripts\python.exe" make_desktop_shortcut.py
if errorlevel 1 goto :fail

rem ---- 6. Schedule ------------------------------------------------
echo  [6/6] Scheduling the bot to run on market days...
".venv\Scripts\python.exe" setup_schedule.py

echo.
echo  Testing Telegram:
".venv\Scripts\python.exe" test_telegram.py

echo.
echo  ==========================================
echo    DONE. Double-click "IBKR Trading Bot" on your desktop.
echo    Don't move or rename this folder - the bot runs from here.
echo  ==========================================
echo.
pause
exit /b 0

:nopython
echo  Python 3.12 or newer is not installed or not on PATH.
echo  Opening python.org - download and install it, and on the FIRST
echo  installer screen tick "Add python.exe to PATH". Then run SETUP.bat again.
start "" "https://www.python.org/downloads/"
pause
exit /b 1

:fail
echo.
echo  Something went wrong above. Take a screenshot of this window and send it to Claude.
pause
exit /b 1
