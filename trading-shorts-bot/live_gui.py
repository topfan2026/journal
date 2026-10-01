"""Desktop app to set up and control the daily live stream.

    python live_gui.py

Tabs for the schedule, IB Gateway, the scanner site, OBS and YouTube save into .env.
The buttons along the bottom start/stop the scheduler (`live.py daemon`), go live now,
run a test without streaming, check every connection, and install autostart at log on.
Uses Tkinter, which ships with Python (on Linux: `sudo apt install python3-tk`).
"""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime

from dotenv import dotenv_values

from config import BOT_DIR, ENV_FILE, save_env


@dataclass
class Field:
    key: str
    label: str
    kind: str = "text"   # text | secret | bool | choice | file | dir | days
    default: str = ""
    help: str = ""
    choices: list[str] = field(default_factory=list)


TABS: dict[str, list[Field]] = {
    "Schedule": [
        Field("LIVE_START", "Go live at (HH:MM)", default="06:00"),
        Field("LIVE_DAYS", "Days", "days", default="mon-fri"),
        Field("LIVE_END", "End at (HH:MM)", default="10:00", help="leave empty to use the duration below"),
        Field("LIVE_DURATION_MIN", "Duration (minutes)", default="240"),
        Field("LIVE_TZ", "Time zone", default="", help="empty = this computer's time zone, or e.g. America/New_York"),
        Field("LIVE_PREP_MIN", "Start setup this many minutes early", default="10"),
    ],
    "IB Gateway": [
        Field("IB_USERNAME", "Paper username"),
        Field("IB_PASSWORD", "Paper password", "secret"),
        Field("IBC_PATH", "IBC folder", "dir", help="unzipped IBC from github.com/IbcAlpha/IBC/releases"),
        Field("TWS_MAJOR_VRSN", "Gateway version", help="e.g. 1030 for 10.30 (Gateway: Help > About)"),
        Field("TWS_PATH", "Gateway install folder", "dir", help="usually C:/Jts or ~/Jts"),
        Field("IB_PORT", "API port", default="4002", help="must match the port aialgopro connects to"),
        Field("IB_REQUIRE_PAPER", "Refuse non-paper accounts", "bool", default="true"),
        Field("IB_READ_ONLY", "Read-only API (blocks orders)", "bool", default="false"),
    ],
    "Scanner site": [
        Field("SCANNER_URL", "Scanner URL", default="https://aialgopro.com"),
        Field("SCANNER_START_TEXT", "Start button text", help="the text on the button that starts the scanner"),
        Field("SCANNER_START_SELECTOR", "or CSS selector", help="only if the text doesn't work"),
        Field("SCANNER_READY_SELECTOR", "Ready selector (optional)", help="appears once the scanner is running"),
        Field("SCANNER_WARMUP_SECONDS", "Warm-up seconds", default="20"),
        Field("BROWSER_CHANNEL", "Browser", "choice", default="chrome", choices=["chrome", "msedge", "chromium"]),
        Field("BROWSER_PATH", "or browser program", "file", help="optional: path to chrome.exe / msedge.exe"),
    ],
    "OBS": [
        Field("OBS_PATH", "OBS program", "file",
              help="Windows: C:/Program Files/obs-studio/bin/64bit/obs64.exe"),
        Field("OBS_WS_PORT", "WebSocket port", default="4455"),
        Field("OBS_WS_PASSWORD", "WebSocket password", "secret", help="OBS: Tools > WebSocket Server Settings"),
        Field("OBS_SCENE", "Scene to stream", help="the scene with a Window Capture of the scanner browser"),
    ],
    "YouTube": [
        Field("YOUTUBE_LIVE_API", "Create a new titled broadcast every day", "bool", default="true",
              help="off = stream with the key already set in OBS"),
        Field("LIVE_TITLE", "Title", default="LIVE Stock Scanner | {weekday} {date} | Pre-Market Movers",
              help="{weekday} and {date} are filled in"),
        Field("LIVE_DESCRIPTION", "Description",
              default="Live AI stock scanner every trading morning. Subscribe and turn on notifications."),
        Field("LIVE_TAGS", "Tags (comma separated)",
              default="stock scanner,day trading,premarket movers,stock market live"),
        Field("LIVE_PRIVACY", "Privacy", "choice", default="public", choices=["public", "unlisted", "private"]),
        Field("LIVE_THUMBNAIL", "Thumbnail (1280x720 jpg)", "file"),
        Field("YOUTUBE_CLIENT_ID", "Google OAuth client ID"),
        Field("YOUTUBE_CLIENT_SECRET", "Google OAuth client secret", "secret"),
    ],
}

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def days_to_list(value: str) -> list[str]:
    """'mon-fri' / 'mon,wed' -> ['mon', ...] (same rules as live.live_days)."""
    out: list[str] = []
    for part in (value or "").lower().replace(" ", "").split(","):
        if "-" in part:
            a, b = (DAY_NAMES.index(x[:3]) for x in part.split("-"))
            idx = range(a, b + 1) if a <= b else [*range(a, 7), *range(0, b + 1)]
            out += [DAY_NAMES[i] for i in idx]
        elif part[:3] in DAY_NAMES:
            out.append(part[:3])
    return [d for d in DAY_NAMES if d in out]


def list_to_days(days: list[str]) -> str:
    return ",".join(d for d in DAY_NAMES if d in days)


def current_values() -> dict[str, str]:
    stored = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
    out = {}
    for fields in TABS.values():
        for f in fields:
            # A key present in .env wins even when empty (e.g. LIVE_END cleared on purpose).
            out[f.key] = (stored.get(f.key) or "") if f.key in stored else (os.environ.get(f.key) or f.default)
    return out


def validate(values: dict[str, str]) -> list[str]:
    import live
    problems = []
    for key in ("LIVE_START", "LIVE_END"):
        if values.get(key):
            try:
                live.parse_hhmm(values[key])
            except Exception:
                problems.append(f"{key}: use HH:MM, e.g. 06:00")
    if not days_to_list(values.get("LIVE_DAYS", "")):
        problems.append("pick at least one day")
    for key in ("LIVE_DURATION_MIN", "LIVE_PREP_MIN", "IB_PORT", "OBS_WS_PORT", "SCANNER_WARMUP_SECONDS"):
        if values.get(key) and not values[key].strip().isdigit():
            problems.append(f"{key}: must be a whole number")
    if values.get("LIVE_TZ"):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(values["LIVE_TZ"])
        except Exception:
            problems.append(f"unknown time zone {values['LIVE_TZ']!r}")
    return problems


def bot_command(*args: str) -> list[str]:
    return [sys.executable, "-u", *args]


# --------------------------------------------------------------------------- UI

class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.root = tk, ttk, root
        root.title("Live Stream Bot")
        root.geometry("900x720")
        root.minsize(760, 600)
        self.vars: dict[str, object] = {}
        self.day_vars: dict[str, object] = {}
        self.daemon: subprocess.Popen | None = None
        self.jobs: list[subprocess.Popen] = []
        self.lines: queue.Queue[str] = queue.Queue()

        values = current_values()
        nb = ttk.Notebook(root)
        nb.pack(fill="x", padx=10, pady=(10, 4))
        for tab, fields in TABS.items():
            frame = ttk.Frame(nb, padding=12)
            frame.columnconfigure(1, weight=1)
            nb.add(frame, text=tab)
            for row, f in enumerate(fields):
                self._field(frame, row, f, values.get(f.key, ""))
            extra = len(fields)
            if tab == "Scanner site":
                ttk.Button(frame, text="Sign in to scanner site (once)…",
                           command=lambda: self.spawn("live.py", "site-login")).grid(
                    row=extra, column=1, sticky="w", pady=(10, 0))
            if tab == "YouTube":
                ttk.Button(frame, text="Connect YouTube account…",
                           command=self.connect_youtube).grid(row=extra, column=1, sticky="w", pady=(10, 0))

        bar = ttk.Frame(root, padding=(10, 4))
        bar.pack(fill="x")
        buttons = [
            ("Save", self.save),
            ("▶ Start scheduler", self.start_daemon),
            ("■ Stop scheduler", self.stop_daemon),
            ("Go live now", lambda: self.spawn("live.py", "run")),
            ("End today's stream", lambda: self.spawn("live.py", "stop")),
            ("Test (no stream)", lambda: self.spawn("live.py", "run", "--dry-run")),
            ("Check setup", lambda: self.spawn("live.py", "check")),
        ]
        for text, cmd in buttons:
            ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 6))

        auto = ttk.Frame(root, padding=(10, 0))
        auto.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=self._autostart_installed())
        ttk.Checkbutton(auto, text="Start the scheduler automatically when I log in",
                        variable=self.auto_var, command=self.toggle_autostart).pack(side="left")
        self.status = tk.StringVar()
        ttk.Label(auto, textvariable=self.status, foreground="#0a6").pack(side="right")

        self.log = tk.Text(root, height=14, wrap="word", state="disabled", background="#0b0f17",
                           foreground="#e8edf5", insertbackground="#e8edf5", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        self.update_status()
        root.after(200, self.pump)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ fields
    def _field(self, frame, row, f: Field, value: str):
        tk, ttk = self.tk, self.ttk
        ttk.Label(frame, text=f.label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        cell = ttk.Frame(frame)
        cell.grid(row=row, column=1, sticky="ew", pady=4)
        cell.columnconfigure(0, weight=1)
        if f.kind == "days":
            chosen = days_to_list(value)
            row_frame = ttk.Frame(cell)
            row_frame.grid(row=0, column=0, sticky="w")
            for i, d in enumerate(DAY_NAMES):
                var = tk.BooleanVar(value=d in chosen)
                self.day_vars[d] = var
                ttk.Checkbutton(row_frame, text=d.title(), variable=var).grid(row=0, column=i, padx=(0, 12))
            return
        if f.kind == "bool":
            var = tk.BooleanVar(value=str(value).lower() in ("1", "true", "yes", "on"))
            ttk.Checkbutton(cell, variable=var).grid(row=0, column=0, sticky="w")
        elif f.kind == "choice":
            var = tk.StringVar(value=value or f.default)
            ttk.Combobox(cell, textvariable=var, values=f.choices, state="readonly", width=18).grid(
                row=0, column=0, sticky="w")
        else:
            var = tk.StringVar(value=value)
            ttk.Entry(cell, textvariable=var, show="•" if f.kind == "secret" else "").grid(
                row=0, column=0, sticky="ew")
            if f.kind in ("file", "dir"):
                ttk.Button(cell, text="Browse…", command=lambda: self.browse(var, f.kind)).grid(
                    row=0, column=1, padx=(6, 0))
        if f.help:
            ttk.Label(cell, text=f.help, foreground="#777").grid(row=1, column=0, columnspan=2, sticky="w")
        self.vars[f.key] = var

    def browse(self, var, kind):
        from tkinter import filedialog
        path = filedialog.askdirectory() if kind == "dir" else filedialog.askopenfilename()
        if path:
            var.set(path)

    def values(self) -> dict[str, str]:
        out = {}
        for key, var in self.vars.items():
            v = var.get()
            out[key] = ("true" if v else "false") if isinstance(v, bool) else str(v).strip()
        out["LIVE_DAYS"] = list_to_days([d for d, v in self.day_vars.items() if v.get()])
        return out

    def save(self) -> bool:
        from tkinter import messagebox
        values = self.values()
        problems = validate(values)
        if problems:
            messagebox.showerror("Check these settings", "\n".join(problems))
            return False
        stored = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
        for key, value in values.items():
            if key not in stored or (stored.get(key) or "") != value:
                save_env(key, value)
        self.update_status()
        self.write(f"saved settings to {ENV_FILE}\n")
        return True

    def update_status(self):
        import live
        try:
            nxt = live.next_start(datetime.now(live.tz()))
            text = f"Next stream: {nxt.strftime('%a %d %b %H:%M')}"
        except Exception as e:
            text = f"Schedule: {e}"
        running = self.daemon is not None and self.daemon.poll() is None
        self.status.set(text + (" • scheduler running" if running else " • scheduler stopped"))

    # ------------------------------------------------------------------ processes
    def spawn(self, *args: str, daemon: bool = False):
        if not self.save():
            return None
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {}
        proc = subprocess.Popen(bot_command(*args), cwd=str(BOT_DIR), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace", **kwargs)
        self.write(f"$ {' '.join(args)}\n")
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()
        if not daemon:
            self.jobs.append(proc)
        return proc

    def _reader(self, proc):
        for line in proc.stdout:
            self.lines.put(line)
        self.lines.put(f"[exited with code {proc.wait()}]\n")

    def start_daemon(self):
        if self.daemon is not None and self.daemon.poll() is None:
            self.write("scheduler is already running\n")
            return
        self.daemon = self.spawn("live.py", "daemon", daemon=True)
        self.update_status()

    def stop_daemon(self):
        if self.daemon is None or self.daemon.poll() is not None:
            self.write("scheduler is not running from this window "
                       "(use 'End today's stream' or untick autostart)\n")
            return
        stop_gracefully(self.daemon)
        self.write("stopping scheduler (ending any live stream first)…\n")
        self.root.after(1000, self.update_status)

    def connect_youtube(self):
        if self.save():
            self.spawn("auth_setup.py", "youtube")

    def _autostart_installed(self) -> bool:
        try:
            import autostart
            return autostart.installed()
        except Exception:
            return False

    def toggle_autostart(self):
        from tkinter import messagebox
        import autostart
        try:
            if self.auto_var.get():
                if not self.save():
                    self.auto_var.set(False)
                    return
                if self.daemon is not None and self.daemon.poll() is None:
                    stop_gracefully(self.daemon)  # autostart runs its own scheduler
                self.write(autostart.install() + "\n")
            else:
                self.write(autostart.uninstall() + "\n")
        except Exception as e:
            self.auto_var.set(not self.auto_var.get())
            messagebox.showerror("Autostart", str(e))
        self.update_status()

    # ------------------------------------------------------------------ log
    def write(self, text: str):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def pump(self):
        while True:
            try:
                self.write(self.lines.get_nowait())
            except queue.Empty:
                break
        self.root.after(200, self.pump)

    def on_close(self):
        from tkinter import messagebox
        if self.daemon is not None and self.daemon.poll() is None:
            if not messagebox.askyesno("Quit", "The scheduler is running from this window. "
                                       "Stop it and quit?\n(Tick autostart to keep it running without the app.)"):
                return
            stop_gracefully(self.daemon)
        self.root.destroy()


def stop_gracefully(proc: subprocess.Popen, timeout: float = 90) -> None:
    """Ask live.py to end the stream cleanly (it ends the broadcast), kill it if it hangs."""
    try:
        proc.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
    except Exception:
        proc.terminate()

    def reaper():
        try:
            proc.wait(timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
    threading.Thread(target=reaper, daemon=True).start()


def main() -> None:
    try:
        import tkinter as tk
    except ImportError:
        sys.exit("Tkinter is missing - on Linux run: sudo apt install python3-tk")
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
