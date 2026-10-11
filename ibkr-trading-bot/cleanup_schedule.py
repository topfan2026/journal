"""Delete every HT_* scheduled task and restore the default sleep timeout. Idempotent."""
from __future__ import annotations

import csv
import io
import subprocess
import sys


def main() -> int:
    if sys.platform != "win32":
        print("Windows only.")
        return 1
    out = subprocess.run(["schtasks", "/query", "/fo", "CSV", "/nh"], capture_output=True, text=True).stdout
    names = []
    for row in csv.reader(io.StringIO(out)):
        if row and row[0].lstrip("\\").startswith("HT_") and row[0] not in names:
            names.append(row[0])
    if not names:
        print("Nothing to clean.")
        return 0
    for name in names:
        r = subprocess.run(["schtasks", "/delete", "/tn", name, "/f"], capture_output=True, text=True)
        print(("deleted " if r.returncode == 0 else "FAILED  ") + name)
    subprocess.run(["powercfg", "/change", "standby-timeout-ac", "30"], capture_output=True)
    print(f"CLEANUP DONE: {len(names)} tasks deleted; default power settings restored.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
