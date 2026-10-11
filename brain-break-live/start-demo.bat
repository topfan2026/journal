@echo off
rem Brain Break Live - preview with fake viewers (no YouTube needed). Double-click to run.
rem Updates itself from GitHub every time it starts.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe call :firstrun || goto :end
echo.
echo  Brain Break Live DEMO
echo  Control page:  http://127.0.0.1:8790/control
echo  Overlay (OBS): http://127.0.0.1:8790/
echo  Keep this window open. Close it (or press Ctrl+C) to stop.
echo.
start "" cmd /c "timeout /t 8 >nul & start http://127.0.0.1:8790/control"
.venv\Scripts\python launcher.py --demo
goto :end

:firstrun
echo First run: setting up (this takes a minute)...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist .venv\Scripts\python.exe (
  echo.
  echo  Python was not found. Install it from https://www.python.org/downloads/
  echo  ^(tick "Add python.exe to PATH" in the installer^), then double-click this file again.
  exit /b 1
)
.venv\Scripts\python -m pip install -q --upgrade pip
exit /b 0

:end
pause
