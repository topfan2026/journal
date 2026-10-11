"""Start Brain Break Live with automatic updates (what start.bat / start-demo.bat run).

    python launcher.py --demo          update from GitHub, then run the demo
    python launcher.py                 update from GitHub, then run with YouTube chat
    (any other main.py options are passed through)

Every start: get the latest version from GitHub (skipped if offline or AUTO_UPDATE=false in .env),
make sure the Python packages are installed, then run main.py. When you click "Update now" on the
control page, main.py exits with code 75 and this updates and starts it again.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import update

ROOT = Path(__file__).resolve().parent
RESTART = 75


def install_requirements() -> None:
    subprocess.call([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
                     "-r", str(ROOT / "requirements.txt")])


def self_update() -> None:
    if os.environ.get("AUTO_UPDATE", "true").strip().lower() in ("0", "false", "no", "off"):
        print("Automatic updates are off (AUTO_UPDATE=false in .env).")
        return
    try:
        update.update()
    except update.UpdateError as e:
        print(f"Update skipped: {e}. Starting the version you have.")
    except Exception as e:  # never let an update problem stop the stream
        print(f"Update failed: {e}. Starting the version you have.")


def main(argv: list[str]) -> int:
    os.chdir(ROOT)
    update._env_from_dotenv()
    env = dict(os.environ, BBL_LAUNCHER="1")
    while True:
        self_update()
        install_requirements()
        try:
            code = subprocess.call([sys.executable, str(ROOT / "main.py"), *argv], env=env)
        except KeyboardInterrupt:
            return 0
        if code != RESTART:
            return code
        print("\nRestarting with the latest version...\n")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
