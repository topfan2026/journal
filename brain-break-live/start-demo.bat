@echo off
rem Brain Break Live - preview with fake viewers (no YouTube needed). Double-click to run.
cd /d "%~dp0"
call :setup || goto :end
echo.
echo  Brain Break Live DEMO is starting...
echo  Control page:  http://127.0.0.1:8790/control
echo  Overlay (OBS): http://127.0.0.1:8790/
echo  Keep this window open. Close it (or press Ctrl+C) to stop.
echo.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8790/control"
.venv\Scripts\python main.py --demo
goto :end

:setup
if exist .venv\Scripts\python.exe goto :deps
echo First run: installing (this takes a minute)...
where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
if not exist .venv\Scripts\python.exe (
  echo.
  echo  Python was not found. Install it from https://www.python.org/downloads/
  echo  ^(tick "Add python.exe to PATH" in the installer^), then double-click this file again.
  exit /b 1
)
.venv\Scripts\python -m pip install --upgrade pip >nul
:deps
.venv\Scripts\python -m pip install -q -r requirements.txt || exit /b 1
exit /b 0

:end
pause
