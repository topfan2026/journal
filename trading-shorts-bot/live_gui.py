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

import live_status
from config import BOT_DIR, ENV_FILE, save_env

COLORS = {"live": "#d93025", "setup": "#e37400", "waiting": "#1a73e8", "failed": "#a50e0e",
          "off": "#5f6368", "muted": "#9aa0a6", "data": "#1e8e3e"}
DARK = {"bg": "#0d1117", "panel": "#161b22", "field": "#0d1117", "border": "#30363d", "fg": "#e6edf3",
        "muted": "#8b949e", "accent": "#1f6feb", "select": "#1f6feb"}
ICONS = {"ok": ("✓", "#188038"), "working": ("●", "#e37400"), "failed": ("✗", "#d93025"),
         "waiting": ("○", "#9aa0a6"), "off": ("–", "#9aa0a6")}


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
        Field("LIVE_WAKE", "Wake the PC from sleep for the stream", "bool", default="false",
              help="Windows: wakes a sleeping PC 10 minutes before setup, and before Website data starts (not one that was shut down)"),
    ],
    "IB Gateway": [
        Field("IB_USERNAME", "Paper username"),
        Field("IB_PASSWORD", "Paper password", "secret"),
        Field("IBC_PATH", "IBC folder", "dir", help="unzipped IBC from github.com/IbcAlpha/IBC/releases"),
        Field("TWS_MAJOR_VRSN", "Gateway version", help="e.g. 1030 for 10.30 (Gateway: Help > About)"),
        Field("TWS_PATH", "Gateway install folder", "dir", help="usually C:/Jts or ~/Jts"),
        Field("IB_PORT", "API port", default="4002", help="must match the port aialgopro connects to"),
        Field("IB_REQUIRE_PAPER", "Refuse non-paper accounts", "bool", default="true"),
        Field("DATA_OPEN_SITE", "Website data: open the website and connect to IBKR", "bool", default="true",
              help="runs the Scanner site steps up to the IBKR connection (not Stream Mode) in the bot's browser"),
        Field("DATA_SCHEDULE", "Website data on a schedule", "bool", default="false",
              help="runs IB Gateway (+ the site's connector) between the times below; the scheduler must be on"),
        Field("DATA_DAYS", "Website data days", "days", default="mon-fri"),
        Field("DATA_START", "Website data start (HH:MM)", default="06:00"),
        Field("DATA_END", "Website data stop (HH:MM)", default="13:00"),
        Field("DATA_STOP_AT_END", "Close IB Gateway at the stop time", "bool", default="true",
              help="not while a stream is on"),
        Field("IB_READ_ONLY", "Read-only API (blocks orders)", "bool", default="false"),
    ],
    "Scanner site": [
        Field("SCANNER_SOURCE", "Scanner to stream", "choice", default="website", choices=["website", "app"],
              help="website = the site below in Chrome; app = the desktop app below. Each has its own steps."),
        Field("SCANNER_URL", "Site address", default="https://aialgopro.com"),
        Field("SCANNER_APP", "Desktop app", "file", help="e.g. Farhad AI Scanner.exe"),
        Field("SCANNER_EMAIL", "Site email", help="the bot signs in with this when the site shows its sign-in form"),
        Field("SCANNER_PASSWORD", "Site password", "secret",
              help="empty = use the browser's saved (autofill) login"),
        Field("SCANNER_SECRET", "Local connector secret", "secret",
              help="used by the steps as {SCANNER_SECRET}"),
        Field("SCANNER_CONNECTOR_CMD", "Website: connector command",
              help="started before the website, e.g. python C:/TradeLedger/connector.py (empty = you start it)"),
        Field("SCANNER_CONNECTOR_PORT", "Website: connector port", default="8765"),
        Field("SCANNER_TUNNEL_CMD", "Website: tunnel command",
              help="e.g. cloudflared tunnel run ibkr (empty = none / you start it)"),
        Field("SCANNER_LAYOUT", "Wall layout on the stream", "choice", default="A+ setups",
              choices=["A+ setups", "YouTube", "Momentum + charts"],
              help="website only: the Layouts choice picked in Stream Mode ({SCANNER_LAYOUT} in the steps)"),
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
    "TikTok": [
        Field("TIKTOK_STUDIO", "Use TikTok LIVE Studio", "bool", default="false",
              help="opens it at go-live time; you click Go LIVE in it"),
        Field("TIKTOK_STUDIO_PATH", "TikTok LIVE Studio program", "file", help="use Find it, or Browse to the .exe"),
        Field("TIKTOK_STUDIO_REMIND", "Pop up a reminder to press Go LIVE", "bool", default="true"),
        Field("TIKTOK_STUDIO_CLOSE_AT_END", "Close it at the end time (ends the TikTok LIVE)", "bool", default="true"),
    ],
    "Market Radar": [
        Field("RADAR_ENABLED", "Send the Market Radar to Telegram", "bool", default="false",
              help="a market-regime report (trend, VIX, breadth, credit, yields) at the times below"),
        Field("RADAR_TIMES", "Send at (HH:MM, comma separated)", default="06:00,13:15",
              help="this computer's time; the scheduler must be running"),
        Field("RADAR_DAYS", "Days", default="mon-fri"),
        Field("RADAR_WATCHLIST", "Watchlist (optional)", help="e.g. NVDA,TSLA,AMD - adds a heat map"),
        Field("TELEGRAM_BOT_TOKEN", "Telegram bot token", "secret", help="from @BotFather in Telegram"),
        Field("TELEGRAM_CHAT_ID", "Telegram chat id", help="message your bot once, then click Find my chat ID"),
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
        Field("LIVE_PRIVACY", "Privacy once it's working", "choice", default="public",
              choices=["public", "unlisted", "private"]),
        Field("LIVE_START_PRIVACY", "Start the stream as", "choice", default="public",
              choices=["public", "unlisted", "private"],
              help="public: subscribers are notified and YouTube recommends it. Unlisted starts get ~no viewers"),
        Field("LIVE_PUBLIC_AFTER_MIN", "Minutes of healthy stream before switching", default="3",
              help="0 = start with the final privacy straight away"),
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
    if str(values.get("DATA_SCHEDULE", "")).lower() in ("1", "true", "yes", "on"):
        for key in ("DATA_START", "DATA_END"):
            try:
                live.parse_hhmm(values.get(key) or "")
            except Exception:
                problems.append(f"Website data {'start' if key == 'DATA_START' else 'stop'}: use HH:MM, e.g. 06:00")
        if not days_to_list(values.get("DATA_DAYS", "")):
            problems.append("Website data: pick at least one day")
    for key in ("LIVE_DURATION_MIN", "LIVE_PREP_MIN", "IB_PORT", "OBS_WS_PORT", "SCANNER_WARMUP_SECONDS",
                "LIVE_PUBLIC_AFTER_MIN"):
        if values.get(key) and not values[key].strip().isdigit():
            problems.append(f"{key}: must be a whole number")
    if values.get("LIVE_TZ"):
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(values["LIVE_TZ"])
        except Exception:
            problems.append(f"unknown time zone {values['LIVE_TZ']!r}")
    return problems


def read_steps(app: bool | None = None) -> str:
    from scanner_site import default_steps, steps_file, use_layout_setting
    path = steps_file(app)
    return use_layout_setting(path.read_text(encoding="utf-8")) if path.exists() else default_steps(app)


BROWSER_COMMANDS = {"run", "daemon", "check", "site-test", "site-login"}


def uses_browser(args) -> bool:
    """These open the bot's Chrome profile, which only one process can use at a time."""
    return len(args) > 1 and args[0] == "live.py" and args[1] in BROWSER_COMMANDS


def bot_command(*args: str) -> list[str]:
    return [sys.executable, "-u", *args]


# --------------------------------------------------------------------------- UI

class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk

        self.tk, self.ttk, self.root = tk, ttk, root
        apply_dark_theme(root)
        root.title("Live Stream Bot")
        root.geometry("960x960")
        root.minsize(760, 600)
        self.vars: dict[str, object] = {}
        self.day_vars: dict[str, dict[str, object]] = {}  # days field key -> day -> checkbox var
        self.daemon: subprocess.Popen | None = None
        self.jobs: list[subprocess.Popen] = []
        self.running: list[tuple[tuple[str, ...], subprocess.Popen]] = []
        self.lines: queue.Queue[str] = queue.Queue()

        values = current_values()
        nb = ttk.Notebook(root)
        nb.pack(fill="x", padx=10, pady=(10, 4))
        self._build_status_tab(nb)
        for tab, fields in TABS.items():
            frame = ttk.Frame(nb, padding=12)
            frame.columnconfigure(1, weight=1)
            nb.add(frame, text=tab)
            for row, f in enumerate(fields):
                self._field(frame, row, f, values.get(f.key, ""))
            extra = len(fields)
            if tab == "Scanner site":
                ttk.Label(frame, text="Steps\n(top to bottom)").grid(
                    row=extra, column=0, sticky="nw", padx=(0, 10), pady=(10, 0))
                self.steps = tk.Text(frame, height=11, wrap="none", font=("Consolas", 10), undo=True, bg=DARK["field"],
                                     fg=DARK["fg"], insertbackground=DARK["fg"], highlightthickness=1,
                                     highlightbackground=DARK["border"], relief="flat")
                self.steps.grid(row=extra, column=1, sticky="ew", pady=(10, 0))
                self.steps_for_app = values.get("SCANNER_SOURCE") == "app"
                self.steps.insert("1.0", read_steps(self.steps_for_app))
                self.vars["SCANNER_SOURCE"].trace_add("write", lambda *_: self.switch_steps())
                row_btns = ttk.Frame(frame)
                row_btns.grid(row=extra + 1, column=1, sticky="w", pady=(8, 0))
                ttk.Button(row_btns, text="Sign in to scanner site (once)…",
                           command=lambda: self.spawn("live.py", "site-login")).pack(side="left", padx=(0, 6))
                ttk.Button(row_btns, text="Test scanner steps",
                           command=lambda: self.spawn("live.py", "site-test")).pack(side="left")
            if tab == "TikTok":
                row_btns = ttk.Frame(frame)
                row_btns.grid(row=extra, column=1, sticky="w", pady=(10, 0))
                ttk.Button(row_btns, text="Find it", command=self.find_tiktok).pack(side="left", padx=(0, 6))
                ttk.Button(row_btns, text="Open LIVE Studio now", command=self.open_tiktok).pack(side="left")
                ttk.Label(frame, foreground=DARK["muted"], wraplength=560, justify="left", text=(
                    "Set up LIVE Studio once: Add source > Window capture > 'LIVE BOT - Scanner - Google Chrome', "
                    "landscape view, your title. TikTok has no remote control for LIVE Studio, so pressing "
                    "Go LIVE stays a click for you; the bot opens it, reminds you and closes it at the end.")
                          ).grid(row=extra + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))
            if tab == "Market Radar":
                row_btns = ttk.Frame(frame)
                row_btns.grid(row=extra, column=1, sticky="w", pady=(10, 0))
                ttk.Button(row_btns, text="Find my chat ID", command=self.radar_chat_id).pack(side="left", padx=(0, 6))
                ttk.Button(row_btns, text="Preview report",
                           command=lambda: self.spawn("market_radar.py", "print")).pack(side="left", padx=(0, 6))
                ttk.Button(row_btns, text="Send to Telegram now",
                           command=lambda: self.spawn("market_radar.py", "send")).pack(side="left")
            if tab == "YouTube":
                ttk.Button(frame, text="Connect YouTube account…",
                           command=self.connect_youtube).grid(row=extra, column=1, sticky="w", pady=(10, 0))

        rows = [
            [("Save settings", self.save),
             ("Test (no stream)", lambda: self.spawn("live.py", "run", "--dry-run")),
             ("Check setup", lambda: self.spawn("live.py", "check")),
             ("Update bot", self.update_bot)],
        ]
        for buttons in rows:
            bar = ttk.Frame(root, padding=(10, 2))
            bar.pack(fill="x")
            for text, cmd in buttons:
                ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=(0, 6))

        auto = ttk.Frame(root, padding=(10, 0))
        auto.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=self._autostart_installed())
        ttk.Checkbutton(auto, text="Start the scheduler automatically when I log in",
                        variable=self.auto_var, command=self.toggle_autostart).pack(side="left")
        self.status = tk.StringVar()
        ttk.Label(auto, textvariable=self.status, foreground="#3fb950").pack(side="right")

        self.log = tk.Text(root, height=7, wrap="word", state="disabled", background="#010409", relief="flat",
                           foreground="#e8edf5", insertbackground="#e8edf5", font=("Consolas", 10))
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        self.update_status()
        self._refresh_wake()
        self.refresh_dashboard()
        root.after(200, self.pump)
        root.after(15000, self._refresh_status)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ status tab
    def _build_status_tab(self, nb):
        tk, ttk = self.tk, self.ttk
        tab = ttk.Frame(nb, padding=10)
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)
        nb.add(tab, text="  Status  ")

        self.banner = tk.Frame(tab, bg=COLORS["off"], padx=16, pady=12)
        self.banner.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.banner.columnconfigure(0, weight=1)
        self.b_title = tk.Label(self.banner, font=("Segoe UI", 20, "bold"), fg="white", bg=COLORS["off"], anchor="w")
        self.b_title.grid(row=0, column=0, sticky="w")
        self.b_sub = tk.Label(self.banner, font=("Segoe UI", 11), fg="white", bg=COLORS["off"], anchor="w")
        self.b_sub.grid(row=1, column=0, sticky="w")
        self.b_clock = tk.Label(self.banner, font=("Segoe UI", 18, "bold"), fg="white", bg=COLORS["off"])
        self.b_clock.grid(row=0, column=1, rowspan=2, sticky="e")

        actions = ttk.Frame(tab)
        actions.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 6))
        self.sched_btn = ttk.Button(actions, text="▶ Start scheduler", command=self.toggle_scheduler, width=20)
        self.sched_btn.pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="● Go live now", command=self.go_live_now).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="■ End today's stream", command=self.end_today).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Open on YouTube", command=self.open_youtube).pack(side="left", padx=(0, 6))
        self.data_btn = ttk.Button(actions, text="▶ Website data only", command=self.toggle_data, width=22)
        self.data_btn.pack(side="left")

        from pipeline_view import PipelineView
        self.pipe = PipelineView(tab, height=320)
        self.pipe.grid(row=2, column=0, columnspan=2, sticky="ew")

        cards = ttk.Frame(tab)
        cards.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.stats = {}
        for i, (key, label) in enumerate([("live_for", "LIVE FOR"), ("viewers", "WATCHING"), ("privacy", "PRIVACY"),
                                          ("fixes", "AUTO-FIXES"), ("last_check", "LAST CHECK"), ("ends", "ENDS AT")]):
            cards.columnconfigure(i, weight=1, uniform="card")
            card = tk.Frame(cards, bg=DARK["panel"], padx=10, pady=6, highlightthickness=1,
                            highlightbackground=DARK["border"])
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0))
            val = tk.Label(card, text="–", font=("Segoe UI", 16, "bold"), fg=DARK["fg"], bg=DARK["panel"])
            val.pack(anchor="w")
            tk.Label(card, text=label, font=("Segoe UI", 8, "bold"), fg=DARK["muted"], bg=DARK["panel"]).pack(anchor="w")
            self.stats[key] = val
        self.problem = ttk.Label(tab, text="", foreground="#f85149")
        self.problem.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        hist = ttk.LabelFrame(tab, text=" Last 7 days (double-click to open on YouTube) ", padding=6)
        hist.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.hist = ttk.Treeview(hist, columns=("date", "result", "minutes", "public"), show="headings", height=4)
        for col, text, width in (("date", "Day", 130), ("result", "Result", 300), ("minutes", "Live (min)", 90),
                                 ("public", "Went public", 90)):
            self.hist.heading(col, text=text)
            self.hist.column(col, width=width, anchor="w")
        self.hist.pack(fill="x")
        self.hist.bind("<Double-1>", self._open_history)
        self.hist_urls: dict[str, str] = {}

    def _refresh_wake(self):
        """schtasks is slow-ish, so check the wake task now and after Save, not every refresh."""
        def work():
            try:
                import wake
                self.wake_installed = wake.installed()
            except Exception:
                self.wake_installed = False
        self.wake_installed = getattr(self, "wake_installed", False)
        threading.Thread(target=work, daemon=True).start()

    def _set_row(self, key, state, detail=""):
        self._pipe_states[key] = (state, detail)

    def refresh_dashboard(self):
        try:
            self._refresh_dashboard()
        except Exception as e:  # never let the status screen kill the app
            self.b_sub.configure(text=f"(status screen error: {e})")
        self.root.after(2000, self.refresh_dashboard)

    def _refresh_dashboard(self):
        import live
        from datetime import timezone
        if getattr(self, "live_root", None) is None:
            from config import Settings
            self.live_root = live.live_root(Settings.load())
        root = self.live_root
        st = live_status.read(root)
        now = datetime.now(live.tz())
        running = (self.daemon is not None and self.daemon.poll() is None) or live.scheduler_running()
        phase = st.get("phase", "")
        age = live_status.age_seconds(st)
        active = phase in ("setup", "ready", "live", "ending", "test")
        stale = active and age is not None and age > (180 if phase == "live" else 420)
        try:
            nxt = live.next_start(now)
        except Exception:
            nxt = None

        def hm(iso):
            try:
                return datetime.fromisoformat(iso).astimezone(live.tz()).strftime("%H:%M")
            except Exception:
                return ""

        def until(when):
            secs = int((when - now).total_seconds())
            if secs <= 0:
                return ""
            h, m = divmod(secs // 60, 60)
            return f"in {h} h {m:02d} min" if h else f"in {m} min {secs % 60:02d} s"

        clock = ""
        if stale:
            kind, title = "failed", "No news from the bot"
            sub = f"Last update {int(age // 60)} min ago - it may have been closed. Check the scheduler window."
        elif phase == "live":
            kind, title = "live", "● LIVE NOW"
            sub = f"on YouTube since {hm(st.get('live_since'))}" + (
                f"  •  {st.get('privacy')}" if st.get("privacy") else "")
            try:
                secs = int((datetime.now(timezone.utc) - datetime.fromisoformat(st["live_since"])).total_seconds())
                clock = f"{secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}"
            except Exception:
                pass
        elif phase in ("setup", "test"):
            kind = "setup"
            title = "Test run…" if phase == "test" else "Getting ready…"
            working = [live_status.STEP_LABELS[n] for n, v in st.get("steps", {}).items()
                       if v.get("state") == "working" and n in live_status.STEP_LABELS]
            sub = f"now: {working[0]}" if working else st.get("message", "")
            if st.get("show_start"):
                clock = f"goes live {hm(st['show_start'])}"
        elif phase == "ready":
            kind, title = "setup", "Ready"
            sub = st.get("message", "")
            try:
                clock = until(datetime.fromisoformat(st["show_start"]))
            except Exception:
                pass
        elif phase == "ending":
            kind, title, sub = "setup", "Ending the stream…", ""
        elif phase == "retrying":
            kind, title, sub = "failed", "Problem - retrying", st.get("message", "")
        elif not running:
            kind, title = "off", "Scheduler is OFF"
            sub = "Nothing will start by itself. Click ▶ Start scheduler."
        else:
            kind = "waiting"
            title = "Waiting for the next stream"
            sub = f"next: {nxt.strftime('%A %d %b  %H:%M')}" if nxt else st.get("message", "")
            if phase in ("ended", "failed", "tested") and age is not None and age < 3600:
                last = {"ended": "Last stream ended", "failed": "Last stream FAILED - see the log",
                        "tested": "Test finished"}[phase]
                sub = f"{last}  •  {sub}"
            clock = until(nxt) if nxt else ""
        color = COLORS[kind]
        for w in (self.banner, self.b_title, self.b_sub, self.b_clock):
            w.configure(bg=color)
        self.b_title.configure(text=title)
        self.b_sub.configure(text=sub)
        self.b_clock.configure(text=clock)
        data_proc = getattr(self, "data_proc", None)
        data_on = data_proc is not None and data_proc.poll() is None
        if hasattr(self, "data_btn") and not (data_on and self.data_btn.cget("text") == "Stopping…"):
            self.data_btn.configure(text="■ Stop website data" if data_on else "▶ Website data only")
        data = st.get("data") or {}
        try:
            data_age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["updated"])).total_seconds()
        except Exception:
            data_age = 1e9
        scheduled_on = bool(data.get("scheduled")) and data.get("state") in ("on", "failed") and data_age < 120
        if (data_on or scheduled_on) and not active and phase != "live":
            kind = "data"
            title = ("Website data: ON (scheduled)" if scheduled_on and not data_on else "Website data: ON") \
                if data.get("state") == "on" else (
                "Website data: problem - retrying" if data.get("state") == "failed" else "Website data: starting…")
            sub = data.get("detail", "")
            color = COLORS["failed"] if data.get("state") == "failed" else COLORS[kind]
            for w in (self.banner, self.b_title, self.b_sub, self.b_clock):
                w.configure(bg=color)
            self.b_title.configure(text=title)
            self.b_sub.configure(text=sub)
            self.b_clock.configure(text="")
        if datetime.now().timestamp() >= getattr(self, "_button_hold_until", 0):
            self.sched_btn.configure(text="■ Stop scheduler" if running and not self._stopping()
                                     else "▶ Start scheduler")
        self._pipe_states = {}

        self._set_row("scheduler", "ok" if running else "failed",
                      (f"next {nxt.strftime('%a %H:%M')}" if nxt else "running") if running else "OFF")
        if (self.vars.get("LIVE_WAKE") and self.vars["LIVE_WAKE"].get()) and nxt is not None:
            prep = float(self.vars["LIVE_PREP_MIN"].get() or 10)
            import wake
            at = wake.wake_time(nxt, prep).strftime("%H:%M")
            self._set_row("wake", "ok" if self.wake_installed else "waiting",
                          f"wakes PC {at}" if self.wake_installed else "Save to set it up")
        else:
            self._set_row("wake", "off", "off")
        steps = st.get("steps", {})
        for name in live_status.STEPS:
            v = steps.get(name, {})
            self._set_row(name, v.get("state", "waiting"), v.get("detail", ""))

        import tiktok_studio
        if not tiktok_studio.enabled():
            self._set_row("tiktok", "off", "off")
        elif phase == "live":
            self._set_row("tiktok", "working", "press Go LIVE in Studio")
        else:
            self._set_row("tiktok", "waiting", "opens when live")
        if not running and not active:
            for name in live_status.STEPS:  # nothing is happening: show the chain idle
                if self._pipe_states[name][0] != "failed":
                    self._pipe_states[name] = ("waiting", "")
        self.pipe.set_states(self._pipe_states)

        self.stats["live_for"].configure(text=clock if phase == "live" and clock else "–")
        viewers = st.get("viewers")
        self.stats["viewers"].configure(text="–" if viewers is None or phase != "live" else str(viewers))
        self.stats["privacy"].configure(text=st.get("privacy") or "–")
        self.stats["fixes"].configure(text=str(st.get("fixes") or 0) if active else "–")
        self.stats["last_check"].configure(text=hm(st.get("last_check")) or "–")
        self.stats["ends"].configure(text=hm(st.get("show_end")) if active else "–")
        self.problem.configure(text=f"Last problem: {st['error']}" if st.get("error") and active else "")
        self.current_url = st.get("url", "")

        if getattr(self, "_hist_tick", 0) % 5 == 0:
            self.hist.delete(*self.hist.get_children())
            self.hist_urls.clear()
            for row in live_status.history(root):
                mins = "" if row["minutes"] is None else f"{row['minutes']:.0f}"
                day = datetime.strptime(row["date"], "%Y-%m-%d").strftime("%a %d %b %Y")
                iid = self.hist.insert("", "end", values=(day, row["result"] + (
                    f": {row['error'][:60]}" if row["result"] == "failed" and row["error"] else ""),
                    mins, "yes" if row["public"] else ""))
                self.hist_urls[iid] = row["url"]
        self._hist_tick = getattr(self, "_hist_tick", 0) + 1

    def _open_history(self, _event):
        import webbrowser
        sel = self.hist.selection()
        if sel and self.hist_urls.get(sel[0]):
            webbrowser.open(self.hist_urls[sel[0]])

    def open_youtube(self):
        import webbrowser
        webbrowser.open(getattr(self, "current_url", "") or "https://studio.youtube.com")

    def toggle_scheduler(self):
        from tkinter import messagebox
        import live
        running = (self.daemon is not None and self.daemon.poll() is None) or live.scheduler_running()
        if running and not self._stopping():
            if not messagebox.askyesno(
                    "Stop the scheduler?",
                    "Stop the scheduler?\n\nNothing will start by itself until you click Start scheduler again "
                    "(it also ends a stream that is live now)."):
                return
            self.stop_daemon()
            self._hold_button("Stopping…")
        else:
            self.start_daemon()
            self._hold_button("Starting…")

    def _hold_button(self, text: str, seconds: int = 6) -> None:
        """Show what's happening and ignore double clicks while the scheduler starts or stops."""
        self.sched_btn.configure(text=text, state="disabled")
        self._button_hold_until = datetime.now().timestamp() + seconds

        def release():
            self.sched_btn.configure(state="normal")
        self.root.after(seconds * 1000, release)

    def _stopping(self) -> bool:
        """A scheduler that was asked to stop but hasn't exited yet."""
        import live
        from config import Settings
        try:
            return live.scheduler_stop_file(Settings.load()).exists()
        except Exception:
            return False

    def go_live_now(self):
        from tkinter import messagebox
        if messagebox.askyesno("Go live now", "Start streaming to YouTube now?"):
            self.spawn("live.py", "run")

    def toggle_data(self):
        """Website data only: IB Gateway (+ the scanner site's connector/tunnel), nothing else."""
        from tkinter import messagebox
        proc = getattr(self, "data_proc", None)
        if proc is not None and proc.poll() is None:
            self.data_btn.configure(text="Stopping…")
            threading.Thread(target=stop_gracefully, args=(proc, 20), daemon=True).start()
            return
        if not messagebox.askyesno("Website data only",
                                   "Start IB Gateway (paper), open the website and connect it to IBKR - without OBS or YouTube?"):
            return
        self.data_proc = self.spawn("live.py", "data")

    def end_today(self):
        from tkinter import messagebox
        if messagebox.askyesno("End today's stream",
                               "End today's stream now?\nIt won't restart today; the schedule carries on tomorrow."):
            self.spawn("live.py", "stop")

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
                self.day_vars.setdefault(f.key, {})[d] = var
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
            ttk.Label(cell, text=f.help, foreground=DARK["muted"]).grid(row=1, column=0, columnspan=2, sticky="w")
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
        for key, day_vars in self.day_vars.items():
            out[key] = list_to_days([d for d, v in day_vars.items() if v.get()])
        return out

    def save(self) -> bool:
        from tkinter import messagebox
        values = self.values()
        problems = validate(values)
        if problems:
            messagebox.showerror("Check these settings", "\n".join(problems))
            return False
        try:
            from scanner_site import parse_steps, steps_file
            text = self.steps.get("1.0", "end").rstrip() + "\n"
            parse_steps(text)
            steps_file(self.steps_for_app).write_text(text, encoding="utf-8")
        except Exception as e:
            messagebox.showerror("Scanner steps", str(e))
            return False
        stored = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
        for key, value in values.items():
            if key not in stored or (stored.get(key) or "") != value:
                save_env(key, value)
        self.update_status()
        self.write(f"saved settings to {ENV_FILE}\n")
        self.sync_wake(values)
        self._refresh_wake()
        return True

    def sync_wake(self, values: dict[str, str]) -> None:
        """Create, update or remove the Windows wake-from-sleep task to match the schedule."""
        try:
            import live
            import wake
            from config import reload_env
            if values.get("LIVE_WAKE") == "true":
                reload_env()
                start = live.next_start(datetime.now(live.tz()))
                prep = float(values.get("LIVE_PREP_MIN") or 10)
                self.write(wake.install(start, prep, live.live_days()) + "\n")
                # Website data on a schedule: wake for its start time too (10 minutes before).
                if values.get("DATA_SCHEDULE") == "true":
                    data_start = live.next_start(datetime.now(live.tz()), "DATA_START", "DATA_DAYS")
                    self.write(wake.install(data_start, 0, live.live_days("DATA_DAYS"), task=wake.DATA_TASK,
                                            what="website data days") + "\n")
                elif wake.installed(wake.DATA_TASK):
                    self.write(wake.uninstall(wake.DATA_TASK) + "\n")
            else:
                for task in (wake.TASK, wake.DATA_TASK):
                    if wake.installed(task):
                        self.write(wake.uninstall(task) + "\n")
        except Exception as e:
            self.write(f"couldn't set up waking the PC: {e}\n")
        self.write_next()

    def write_next(self) -> None:
        """After Save: say exactly when the next stream happens, and warn if nothing will start it."""
        import live
        try:
            start = live.next_start(datetime.now(live.tz()))
        except Exception as e:
            self.write(f"schedule problem: {e}\n")
            return
        prep = float(self.vars["LIVE_PREP_MIN"].get() or 10)
        from datetime import timedelta
        self.write(f"next stream: {start.strftime('%A %d %b %H:%M')} (setup starts "
                   f"{(start - timedelta(minutes=prep)).strftime('%H:%M')})\n")
        running = (self.daemon is not None and self.daemon.poll() is None) or live.scheduler_running()
        if not running or self._stopping():
            self.write("!! the scheduler is OFF - nothing will start. Click ▶ Start scheduler on the Status tab.\n")

    def update_status(self):
        import live
        try:
            nxt = live.next_start(datetime.now(live.tz()))
            text = f"Next stream: {nxt.strftime('%a %d %b %H:%M')}"
        except Exception as e:
            text = f"Schedule: {e}"
        mine = self.daemon is not None and self.daemon.poll() is None
        if mine:
            state = " • scheduler running"
        elif live.scheduler_running():
            state = " • scheduler running (in the background)"
        else:
            state = " • scheduler STOPPED - click Start scheduler"
        self.status.set(text + state)

    def _refresh_status(self):
        self.update_status()  # picks up a scheduler started or stopped outside this window
        self.root.after(15000, self._refresh_status)

    # ------------------------------------------------------------------ processes
    def spawn(self, *args: str, daemon: bool = False):
        if uses_browser(args):
            busy = [a for a, p in self.running if p.poll() is None and uses_browser(a)]
            if busy:
                self.write(f"'{' '.join(busy[0][1:])}' is still running - wait for it to finish "
                           "(it uses the same browser), or use Stop / End today's stream.\n")
                return None
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
        self.running.append((args, proc))
        return proc

    def _reader(self, proc):
        for line in proc.stdout:
            self.lines.put(line)
        self.lines.put(f"[exited with code {proc.wait()}]\n")

    def _start_background(self) -> None:
        """Start the autostart launcher once the previous scheduler has released its lock."""
        import autostart
        import live
        if live.scheduler_running() and self._handover_tries > 0:
            self._handover_tries -= 1
            self.root.after(2000, self._start_background)
            return
        if autostart._start_windows_now(autostart.startup_file()):
            self.write("scheduler started in the background (minimised window)\n")
        self.update_status()

    def start_daemon(self):
        import live
        if self._stopping() and live.scheduler_running():
            # The old one is still shutting down: start the new one as soon as it has gone.
            self.write("waiting for the previous scheduler to finish stopping, then starting it again…\n")
            self._restart_tries = 30
            self.root.after(2000, self._start_when_free)
            return
        if (self.daemon is not None and self.daemon.poll() is None) or live.scheduler_running():
            self.write("scheduler is already running\n")
            return
        if os.name == "nt" and self._autostart_installed():
            self._handover_tries = 0
            self._start_background()  # independent of this window, so closing the app doesn't stop it
            return
        self.daemon = self.spawn("live.py", "daemon", daemon=True)
        self.update_status()

    def _start_when_free(self):
        import live
        if live.scheduler_running() and self._restart_tries > 0:
            self._restart_tries -= 1
            self.root.after(2000, self._start_when_free)
            return
        self.start_daemon()

    def stop_daemon(self):
        if self.daemon is None or self.daemon.poll() is not None:
            import live
            from config import Settings
            if live.scheduler_running():
                live.request_scheduler_stop(Settings.load())
                self.write("asked the background scheduler to stop (it ends any live stream first; "
                           "it starts again at your next log in while autostart is ticked)\n")
                self.root.after(35000, self.update_status)
            else:
                self.write("the scheduler is not running\n")
            return
        stop_gracefully(self.daemon)
        self.write("stopping scheduler (ending any live stream first)…\n")
        self.root.after(1000, self.update_status)

    def update_bot(self):
        if os.name != "nt":
            self.write("Update bot is for Windows; elsewhere use: git pull\n")
            return
        if any(p.poll() is None for _, p in self.running):
            self.write("stop the running task first, then update\n")
            return
        proc = subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                 str(BOT_DIR / "update.ps1")], cwd=str(BOT_DIR), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True,
                                encoding="utf-8", errors="replace")
        self.write("$ update\n")
        threading.Thread(target=self._reader, args=(proc,), daemon=True).start()

    def switch_steps(self):
        """Website <-> desktop app: keep the box's current steps, show the other source's steps."""
        from tkinter import messagebox
        from scanner_site import parse_steps, steps_file
        app = self.vars["SCANNER_SOURCE"].get() == "app"
        if app == self.steps_for_app:
            return
        text = self.steps.get("1.0", "end").rstrip() + "\n"
        try:
            parse_steps(text)
            steps_file(self.steps_for_app).write_text(text, encoding="utf-8")
        except Exception as e:
            messagebox.showwarning("Scanner steps", f"The current steps weren't saved: {e}")
        self.steps_for_app = app
        self.steps.delete("1.0", "end")
        self.steps.insert("1.0", read_steps(app))
        self.write(f"showing the {'desktop app' if app else 'website'} steps\n")

    def radar_chat_id(self):
        """Fill in the chat id of whoever last messaged the bot."""
        if not self.save():
            return

        def work():
            try:
                import market_radar
                from config import reload_env
                reload_env()
                found = market_radar.telegram_chat_id()
                chat = found.split()[0]
                self.lines.put(f"found your Telegram chat: {found} - click Save settings\n")
                self.root.after(0, lambda: self.vars["TELEGRAM_CHAT_ID"].set(chat))
            except Exception as e:
                self.lines.put(f"couldn't find the chat id: {e}\n")
        threading.Thread(target=work, daemon=True).start()

    def find_tiktok(self):
        import tiktok_studio
        hit = tiktok_studio.find_exe()
        if hit:
            self.vars["TIKTOK_STUDIO_PATH"].set(str(hit))
            self.write(f"found TikTok LIVE Studio: {hit} (click Save)\n")
        else:
            self.write("couldn't find TikTok LIVE Studio - use Browse… and pick its .exe\n")

    def open_tiktok(self):
        import tiktok_studio
        if self.save():
            self.write(tiktok_studio.open_studio() + "\n")

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
                own = self.daemon is not None and self.daemon.poll() is None
                self.write(autostart.install() + "\n")
                if own and os.name == "nt":
                    # Hand over to the background scheduler, which keeps running after this window closes.
                    stop_gracefully(self.daemon)
                    self._handover_tries = 45
                    self.root.after(2000, self._start_background)
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
        data_proc = getattr(self, "data_proc", None)
        if data_proc is not None and data_proc.poll() is None:
            if not messagebox.askyesno("Quit", "Website data (IB Gateway) is being kept up from this window. "
                                       "Stop watching it and quit?\n(IB Gateway itself stays logged in.)"):
                return
            stop_gracefully(data_proc, 20)
        self.root.destroy()


def apply_dark_theme(root) -> None:
    """A dark, app-like look for all tabs (ttk 'clam' theme recoloured)."""
    from tkinter import ttk
    d = DARK
    st = ttk.Style(root)
    st.theme_use("clam")
    root.configure(bg=d["bg"])
    root.option_add("*TCombobox*Listbox.background", d["panel"])
    root.option_add("*TCombobox*Listbox.foreground", d["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", d["select"])
    st.configure(".", background=d["bg"], foreground=d["fg"], fieldbackground=d["field"], bordercolor=d["border"],
                 lightcolor=d["border"], darkcolor=d["border"], troughcolor=d["panel"], focuscolor=d["accent"],
                 selectbackground=d["select"], selectforeground="white", insertcolor=d["fg"],
                 font=("Segoe UI", 10))
    st.configure("TFrame", background=d["bg"])
    st.configure("TLabel", background=d["bg"], foreground=d["fg"])
    st.configure("TLabelframe", background=d["bg"], bordercolor=d["border"])
    st.configure("TLabelframe.Label", background=d["bg"], foreground=d["muted"], font=("Segoe UI", 9, "bold"))
    st.configure("TNotebook", background=d["bg"], bordercolor=d["border"], tabmargins=(0, 4, 0, 0))
    st.configure("TNotebook.Tab", background=d["panel"], foreground=d["muted"], padding=(14, 6),
                 bordercolor=d["border"])
    st.map("TNotebook.Tab", background=[("selected", d["bg"])], foreground=[("selected", d["fg"])])
    st.configure("TButton", background=d["panel"], foreground=d["fg"], padding=(10, 5), bordercolor=d["border"])
    st.map("TButton", background=[("active", "#21262d"), ("pressed", d["accent"])])
    st.configure("TEntry", fieldbackground=d["field"], foreground=d["fg"], insertcolor=d["fg"])
    st.configure("TCombobox", fieldbackground=d["field"], background=d["panel"], foreground=d["fg"],
                 arrowcolor=d["fg"])
    st.map("TCombobox", fieldbackground=[("readonly", d["field"])], foreground=[("readonly", d["fg"])])
    st.configure("TCheckbutton", background=d["bg"], foreground=d["fg"], indicatorbackground=d["field"],
                 indicatorforeground=d["fg"])
    st.map("TCheckbutton", background=[("active", d["bg"])],
           indicatorbackground=[("selected", d["accent"]), ("active", d["panel"])])
    st.configure("Treeview", background=d["panel"], fieldbackground=d["panel"], foreground=d["fg"], rowheight=22,
                 bordercolor=d["border"])
    st.configure("Treeview.Heading", background=d["bg"], foreground=d["muted"], font=("Segoe UI", 9, "bold"))
    st.map("Treeview", background=[("selected", d["select"])])


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
