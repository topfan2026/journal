"""Create "IBKR Trading Bot" shortcuts (desktop + Start menu) that open TWS and the app window.

Run once from the project folder, with the venv created:
    python make_desktop_shortcut.py
"""
from __future__ import annotations

import stat
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
NAME = "IBKR Trading Bot"


def venv_python() -> Path:
    win = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    nix = PROJECT_DIR / ".venv" / "bin" / "python"
    return win if sys.platform == "win32" else nix


def windows() -> Path:
    def q(x) -> str:  # PowerShell single-quoted string literal
        return "'" + str(x).replace("'", "''") + "'"

    # pythonw.exe = no black console window; the app shows in its own window instead.
    pyw = venv_python().with_name("pythonw.exe")
    py = pyw if pyw.exists() else venv_python()
    launcher, icon = PROJECT_DIR / "launch.py", PROJECT_DIR / "icon.ico"
    ps = f"""
$made = @()
foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {{
  $lnk = Join-Path $dir {q(NAME + '.lnk')}
  $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
  $s.TargetPath = {q(py)}
  $s.Arguments = {q(f'"{launcher}"')}
  $s.WorkingDirectory = {q(PROJECT_DIR)}
  $s.IconLocation = {q(f'{icon},0')}
  $s.Description = 'Open TWS and the IBKR Trading Bot app'
  $s.Save()
  $made += $lnk
}}
Write-Output ($made -join "`n")
"""
    out = subprocess.run(["powershell", "-NoProfile", "-c", ps], capture_output=True, text=True, check=True)
    return Path(out.stdout.strip().splitlines()[0])


def mac_or_linux() -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    py, launcher = venv_python(), PROJECT_DIR / "launch.py"
    if sys.platform == "darwin":
        path = desktop / f"{NAME}.command"
        path.write_text(f'#!/bin/bash\ncd "{PROJECT_DIR}"\n"{py}" "{launcher}"\n')
    else:
        path = desktop / "ibkr-trading-bot.desktop"
        path.write_text(f"[Desktop Entry]\nType=Application\nName={NAME}\nTerminal=true\n"
                        f'Path={PROJECT_DIR}\nExec="{py}" "{launcher}"\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def main() -> int:
    if not venv_python().exists():
        print(f"Create the venv first (python -m venv .venv); missing {venv_python()}")
        return 1
    path = windows() if sys.platform == "win32" else mac_or_linux()
    print(f"Shortcut created: {path}")
    if sys.platform == "win32":
        print("Also added to the Start menu. Tip: right-click it there > Pin to taskbar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
