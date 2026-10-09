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
from pathlib import Path

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
        Field("LIVE_REQUIRE_DATA", "Only go live with live market data", "bool", default="true",
              help="Checks the internet and that IB Gateway returns recent prices: holds the stream until they do, "
                   "and reconnects the website, the connector, then IB Gateway when they stop (also for Autopilot)"),
    ],
    "IB Gateway": [
        Field("IB_USERNAME", "Paper username"),
        Field("IB_PASSWORD", "Paper password", "secret"),
        Field("IBC_PATH", "IBC folder", "dir", help="unzipped IBC from github.com/IbcAlpha/IBC/releases"),
        Field("TWS_MAJOR_VRSN", "Gateway version", help="e.g. 1051 for 10.51 (Gateway: Help > About); if it's no longer installed, the newest installed one is used"),
        Field("TWS_PATH", "Gateway install folder", "dir", help="usually C:/Jts or ~/Jts"),
        Field("IB_PORT", "API port", default="4002", help="must match the port aialgopro connects to"),
        Field("IB_REQUIRE_PAPER", "Refuse non-paper accounts", "bool", default="true"),
        Field("DATA_OPEN_SITE", "Website data: open the website and connect to IBKR", "bool", default="true",
              help="runs the Scanner site steps up to the IBKR connection (not Stream Mode) in the bot's browser"),
        Field("AUTOPILOT_WINDOW", "Also open Autopilot (runs the simulated traders 9:30-16:00 NY)", "bool", default="true",
              help="the site's Autopilot page in a second window, 'LIVE BOT - Trading'; switch Autopilot on in that page once"),
        Field("DATA_SCHEDULE", "Website data on a schedule", "bool", default="false",
              help="runs IB Gateway (+ the site's connector) between the times below; the scheduler must be on"),
        Field("DATA_DAYS", "Website data days", "days", default="mon-fri"),
        Field("DATA_START", "Website data start (HH:MM)", default="09:00"),
        Field("DATA_END", "Website data stop (HH:MM)", default="16:15", help="keep it after 16:00 New York so Autopilot trades the whole session"),
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
        Field("STREAM_TO", "Scheduled stream goes to", "choice", default="youtube", choices=["youtube", "tiktok", "both"],
              help="youtube or tiktok on its own, or both at once; 'TikTok live now' always goes to TikTok only"),
        Field("TIKTOK_METHOD", "Reach TikTok with", "choice", default="studio", choices=["studio", "rtmp"],
              help="studio: TikTok LIVE Studio (you click Go LIVE) · rtmp: OBS + stream key from TikTok LIVE Center"),
        Field("TIKTOK_RTMP_SERVER", "TikTok server URL (rtmp)", help="rtmp only: Server URL from TikTok LIVE Center"),
        Field("TIKTOK_STREAM_KEY", "TikTok stream key (rtmp)", "secret",
              help="rtmp only: TikTok may give a new key for each LIVE - paste the current one"),
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
    if "STREAM_TO" not in stored and not os.environ.get("STREAM_TO"):
        # Before the destination choice, "Use TikTok LIVE Studio" meant YouTube and TikTok together.
        legacy = stored.get("TIKTOK_STUDIO") if "TIKTOK_STUDIO" in stored else os.environ.get("TIKTOK_STUDIO", "")
        if str(legacy).strip().lower() in ("1", "true", "yes", "on"):
            out["STREAM_TO"] = "both"
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
    dest, method = (values.get("STREAM_TO") or "youtube").lower(), (values.get("TIKTOK_METHOD") or "studio").lower()
    if dest == "both" and method == "rtmp":
        problems.append("TikTok: OBS streams to one place at a time - for YouTube and TikTok together, reach TikTok with studio")
    if method == "rtmp" and dest in ("tiktok", "both"):
        server = (values.get("TIKTOK_RTMP_SERVER") or "").strip().lower()
        if not server.startswith(("rtmp://", "rtmps://")):
            problems.append("TikTok server URL: paste the rtmp:// address from TikTok LIVE Center")
        if not (values.get("TIKTOK_STREAM_KEY") or "").strip():
            problems.append("TikTok stream key: paste it from TikTok LIVE Center")
    return problems


def read_steps(app: bool | None = None) -> str:
    from scanner_site import default_steps, steps_file, use_layout_setting
    path = steps_file(app)
    return use_layout_setting(path.read_text(encoding="utf-8")) if path.exists() else default_steps(app)


BROWSER_COMMANDS = {"run", "daemon", "check", "check-autopilot", "site-test", "site-login"}


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
        root.title(APP_NAME)
        set_app_icon(root)
        # Fit the screen (a 1366x768 laptop too): the buttons are at the top, so a shorter window only shortens the tabs.
        width, height = min(1120, root.winfo_screenwidth() - 40), min(960, root.winfo_screenheight() - 90)
        root.geometry(f"{width}x{height}")
        root.minsize(760, 600)
        self.vars: dict[str, object] = {}
        self.day_vars: dict[str, dict[str, object]] = {}  # days field key -> day -> checkbox var
        self.daemon: subprocess.Popen | None = None
        self.jobs: list[subprocess.Popen] = []
        self.running: list[tuple[tuple[str, ...], subprocess.Popen]] = []
        self.lines: queue.Queue[str] = queue.Queue()

        values = current_values()
        # The buttons and the autostart switch sit at the top and the log at the bottom, both packed before the
        # tabs, so they always keep their space; the tabs get what is left (a tall Status tab can never push the
        # buttons off the window).
        top = ttk.Frame(root)
        top.pack(side="top", fill="x", pady=(8, 0))
        bottom = ttk.Frame(root)
        bottom.pack(side="bottom", fill="x")
        nb = ttk.Notebook(root)
        nb.pack(side="top", fill="both", expand=True, padx=10, pady=(6, 0))
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
                make_button(row_btns, "Sign in to scanner site (once)…", lambda: self.spawn("live.py", "site-login"),
                            "site_login").pack(side="left", padx=(0, 6))
                make_button(row_btns, "Test scanner steps", lambda: self.spawn("live.py", "site-test"),
                            "site_test").pack(side="left")
            if tab == "TikTok":
                row_btns = ttk.Frame(frame)
                row_btns.grid(row=extra, column=1, sticky="w", pady=(10, 0))
                make_button(row_btns, "Find it", self.find_tiktok, "find_tiktok").pack(side="left", padx=(0, 6))
                make_button(row_btns, "Open LIVE Studio now", self.open_tiktok, "open_tiktok").pack(side="left")
                ttk.Label(frame, foreground=DARK["muted"], wraplength=560, justify="left", text=(
                    "Set up LIVE Studio once: Add source > Window capture > 'LIVE BOT - Scanner - Google Chrome', "
                    "landscape view, your title. TikTok has no remote control for LIVE Studio, so pressing "
                    "Go LIVE stays a click for you; the bot opens it, reminds you and closes it at the end.")
                          ).grid(row=extra + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))
            if tab == "Market Radar":
                row_btns = ttk.Frame(frame)
                row_btns.grid(row=extra, column=1, sticky="w", pady=(10, 0))
                make_button(row_btns, "Find my chat ID", self.radar_chat_id, "chat_id").pack(side="left", padx=(0, 6))
                make_button(row_btns, "Preview report", lambda: self.spawn("market_radar.py", "print"),
                            "radar_preview").pack(side="left", padx=(0, 6))
                make_button(row_btns, "Send to Telegram now", lambda: self.spawn("market_radar.py", "send"),
                            "radar_send").pack(side="left")
            if tab == "YouTube":
                make_button(frame, "Connect YouTube account…", self.connect_youtube,
                            "connect_youtube").grid(row=extra, column=1, sticky="w", pady=(10, 0))

        rows = [
            [("Save settings", self.save, "save"),
             ("Test (no stream)", lambda: self.spawn("live.py", "run", "--dry-run"), "test"),
             ("Check setup (stream)", lambda: self.spawn("live.py", "check"), "check"),
             ("Check Autopilot setup", lambda: self.spawn("live.py", "check-autopilot"), "check_autopilot"),
             ("Update bot", self.update_bot, "update"),
             ("Desktop shortcut", self.desktop_shortcut, "shortcut")],
        ]
        for buttons in rows:
            bar = ttk.Frame(top, padding=(10, 2))
            bar.pack(fill="x")
            for text, cmd, key in buttons:
                make_button(bar, text, cmd, key).pack(side="left", padx=(0, 6))

        auto = ttk.Frame(top, padding=(10, 0))
        auto.pack(fill="x")
        self.auto_var = tk.BooleanVar(value=self._autostart_installed())
        ttk.Checkbutton(auto, text="Start the scheduler automatically when I log in",
                        variable=self.auto_var, command=self.toggle_autostart).pack(side="left")
        self.status = tk.StringVar()
        ttk.Label(auto, textvariable=self.status, foreground="#3fb950").pack(side="right")

        self.log = tk.Text(bottom, height=4 if root.winfo_screenheight() < 1000 else 6, wrap="word", state="disabled", background="#010409", relief="flat",
                           foreground="#e8edf5", insertbackground="#e8edf5", font=("Consolas", 10))
        self.log.pack(fill="x", padx=10, pady=10)
        self.update_status()
        self._refresh_wake()
        self.refresh_dashboard()
        root.after(200, self.pump)
        root.after(15000, self._refresh_status)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ status tab
    def _build_status_tab(self, nb):
        tk, ttk = self.tk, self.ttk
        # The Status tab scrolls (mouse wheel or the bar on the right) when the window is shorter than its content.
        outer = ttk.Frame(nb)
        nb.add(outer, text="  Status  ")
        canvas = tk.Canvas(outer, bg=DARK["bg"], highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        tab = ttk.Frame(canvas, padding=10)
        inner = canvas.create_window((0, 0), window=tab, anchor="nw")
        tab.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(inner, width=e.width))

        def wheel(event):
            over = canvas.winfo_containing(event.x_root, event.y_root)
            if over is None or not str(over).startswith(str(canvas)):
                return  # the log and the settings tabs scroll themselves
            if canvas.winfo_ismapped() and canvas.bbox("all") and canvas.bbox("all")[3] > canvas.winfo_height():
                canvas.yview_scroll(-1 if (event.delta > 0 or getattr(event, "num", 0) == 4) else 1, "units")
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            canvas.bind_all(seq, wheel, add="+")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

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
        self.sched_btn = make_button(actions, "Start scheduler", self.toggle_scheduler, "scheduler_start", width=16)
        self.sched_btn.pack(side="left", padx=(0, 6))
        make_button(actions, "Go live now", self.go_live_now, "go_live").pack(side="left", padx=(0, 6))
        make_button(actions, "TikTok live now", self.tiktok_live_now, "tiktok_live").pack(side="left", padx=(0, 6))
        make_button(actions, "End today's stream", self.end_today, "end_stream").pack(side="left", padx=(0, 6))
        make_button(actions, "Open on YouTube", self.open_youtube, "open_youtube").pack(side="left", padx=(0, 6))
        self.data_btn = make_button(actions, "Website data only", self.toggle_data, "data_start", width=17)
        self.data_btn.pack(side="left")

        from pipeline_view import PipelineView
        self.pipe = PipelineView(tab, height=320)
        self.pipe.grid(row=2, column=0, columnspan=2, sticky="ew")

        cards = ttk.Frame(tab)
        cards.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        self.stats = {}
        for i, (key, label) in enumerate([("autopilot", "AUTOPILOT"), ("live_for", "LIVE FOR"), ("viewers", "WATCHING"),
                                          ("privacy", "PRIVACY"), ("fixes", "AUTO-FIXES"), ("last_check", "LAST CHECK"),
                                          ("ends", "ENDS AT")]):
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

        # Today's Autopilot trades and the last 7 streams share one space (tabs), to keep the Status tab short.
        tables = ttk.Notebook(tab)
        tables.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        trades = ttk.Frame(tables, padding=6)
        tables.add(trades, text=" Autopilot today (simulated trades) ")
        self.ap_summary = ttk.Label(trades, text="")
        self.ap_summary.pack(anchor="w")
        cols = (("time", "Time", 70), ("source", "Trader", 110), ("symbol", "Symbol", 80), ("side", "Side", 60),
                ("result", "Result", 70), ("entry", "Entry", 80), ("exit", "Exit", 80), ("pnl", "P&L", 90))
        self.ap_trades = ttk.Treeview(trades, columns=[c[0] for c in cols], show="headings", height=4)
        for col, text, width in cols:
            self.ap_trades.heading(col, text=text)
            self.ap_trades.column(col, width=width, anchor="w")
        self.ap_trades.pack(fill="x")

        hist = ttk.Frame(tables, padding=6)
        tables.add(hist, text=" Last 7 streams (double-click to open on YouTube) ")
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
        elif phase == "tested" and st.get("check") and age is not None and age < 900:
            check = st["check"]
            kind = "data" if check.get("ok") else "failed"
            title = f"{check.get('name', 'Check')}: " + ("passed" if check.get("ok") else "found a problem")
            sub = check.get("summary", "")
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
        if hasattr(self, "data_btn") and not (data_on and "Stopping" in str(self.data_btn.cget("text"))):
            set_button(self.data_btn, "Stop website data" if data_on else "Website data only", "data_stop" if data_on else "data_start")
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
            stop = running and not self._stopping()
            set_button(self.sched_btn, "Stop scheduler" if stop else "Start scheduler", "scheduler_stop" if stop else "scheduler_start")
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
        ap = st.get("autopilot") or {}
        ap_state, ap_detail = autopilot_row(ap)
        self.stats["autopilot"].configure(text=AUTOPILOT_WORD[ap_state], fg=AUTOPILOT_COLOR[ap_state])
        self.ap_detail = ap_detail
        self.ap_summary.configure(text=f"Autopilot: {ap_detail}. " + autopilot_summary(ap))
        rows = trade_rows(ap)
        if rows != getattr(self, "_ap_rows", None):
            self._ap_rows = rows
            self.ap_trades.delete(*self.ap_trades.get_children())
            for row in rows:
                self.ap_trades.insert("", "end", values=row)
        steps = st.get("steps", {})
        for name in live_status.STEPS:
            v = steps.get(name, {})
            self._set_row(name, v.get("state", "waiting"), v.get("detail", ""))

        import tiktok_studio
        live_to = st.get("to") if phase in ("setup", "ready", "live") else None
        try:
            dest = live_to or tiktok_studio.destination()
            studio = tiktok_studio.uses_studio(dest)
        except Exception:
            dest, studio = "youtube", False
        if not tiktok_studio.to_tiktok(dest):
            self._set_row("tiktok", "off", "off")
        elif phase == "live":
            self._set_row("tiktok", "working" if studio else "ok", "press Go LIVE in Studio" if studio else "OBS streams to TikTok")
        else:
            self._set_row("tiktok", "waiting", "opens when live" if studio else "OBS streams when live")
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
        where = {"youtube": "YouTube", "tiktok": "TikTok", "both": "YouTube and TikTok"}.get(
            (self.vars["STREAM_TO"].get() if "STREAM_TO" in self.vars else "youtube").lower(), "YouTube")
        if messagebox.askyesno("Go live now", f"Start streaming to {where} now?\n\n(Set where it goes in the TikTok tab.)"):
            self.spawn("live.py", "run")

    def tiktok_live_now(self):
        """TikTok on its own, whatever the scheduled stream is set to: no YouTube broadcast."""
        from tkinter import messagebox
        method = (self.vars["TIKTOK_METHOD"].get() if "TIKTOK_METHOD" in self.vars else "studio").lower()
        how = ("OBS streams to TikTok with your stream key." if method == "rtmp"
               else "TikTok LIVE Studio opens - you click Go LIVE in it.")
        if messagebox.askyesno("TikTok live now", f"Start a TikTok LIVE on its own now (no YouTube)?\n\n{how}"):
            self.spawn("live.py", "run", "--to", "tiktok")

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
                make_button(cell, "Browse…", lambda: self.browse(var, f.kind), "browse").grid(
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
        root = getattr(self, "live_root", None)
        phase = live_status.read(root).get("phase") if root is not None else None
        if phase in ("setup", "ready", "live"):
            self.write("the running stream picks up the new end time and check settings within about 30 s; "
                       "the destination, title and privacy apply from the next stream\n")
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

    def desktop_shortcut(self):
        """An AiAlgobot icon on the desktop that opens this app."""
        if os.name != "nt":
            self.write("Desktop shortcut is for Windows\n")
            return
        if not ICON_ICO.exists():
            self.write("the icon file is missing - click Update bot first, then try again\n")
            return
        desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
                                  "[Environment]::GetFolderPath('Desktop')"], capture_output=True, text=True, timeout=20)
            if out.stdout.strip():
                desktop = Path(out.stdout.strip())  # OneDrive can move the Desktop folder
            subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", shortcut_ps(BOT_DIR, desktop)],
                           check=True, capture_output=True, text=True, timeout=30)
            self.write(f"made a desktop shortcut: {desktop / (APP_NAME + '.lnk')}\n"
                       "If it still shows the old picture: delete any other bot shortcut on the desktop, "
                       "then sign out of Windows and back in (that clears Windows' icon cache).\n")
        except Exception as e:
            self.write(f"couldn't make the desktop shortcut: {e}\n")

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


APP_NAME = "AiAlgobot"
ICON_DIR = BOT_DIR / "assets" / "icons"

# What each button does: (icon in assets/icons, the tip shown on hover).
BUTTONS: dict[str, tuple[str, str]] = {
    "save": ("save", "Save every setting on all tabs to .env. Also sets up (or removes) the PC wake-up tasks for your schedules."),
    "test": ("test", "A dry run of the whole stream: IB Gateway, the website and OBS, without going live or creating a broadcast."),
    "check": ("check", "Checks everything a STREAM needs: IB Gateway login, OBS, YouTube and the website steps. Opens OBS."),
    "check_autopilot": ("autopilot", "Checks only what Autopilot needs: IB Gateway (paper), the website signed in and connected, and the Autopilot window. No OBS or YouTube."),
    "update": ("update", "Downloads the latest AiAlgobot and replaces the program files. Your settings, passwords and scanner steps are kept. Stop running tasks first."),
    "shortcut": ("shortcut", "Puts an AiAlgobot icon on your desktop that opens this app (no console window). Replaces its own older copy."),
    "scheduler_start": ("play", "Starts the scheduler: it goes live at your stream time, runs the Website data schedule (IB Gateway + website + Autopilot) and sends the Market Radar. Keep it running."),
    "scheduler_stop": ("stop", "Stops the scheduler. Nothing starts by itself until you start it again."),
    "go_live": ("live", "Starts the stream now, to where 'Scheduled stream goes to' (TikTok tab) says, and runs it until the end time."),
    "tiktok_live": ("tiktok", "Starts a TikTok-only LIVE now (no YouTube): LIVE Studio opens and you press Go LIVE, or OBS streams with your TikTok key."),
    "end_stream": ("stop", "Ends today's stream now (OBS stops, the YouTube broadcast ends) and keeps it from restarting today."),
    "open_youtube": ("youtube", "Opens today's broadcast on YouTube in your browser."),
    "data_start": ("globe", "Website data only: IB Gateway (paper), the website signed in and connected, and the Autopilot window. No OBS or YouTube. Runs until you stop it."),
    "data_stop": ("stop", "Stops Website data: closes the website and Autopilot windows. IB Gateway stays logged in."),
    "site_login": ("key", "Opens the bot's own browser so you can sign in to aialgopro.com once. It remembers you after that."),
    "site_test": ("steps", "Runs just the Scanner site steps in the bot's browser and leaves the window open for 60 seconds so you can watch."),
    "find_tiktok": ("search", "Looks for TikTok LIVE Studio on this PC and fills in its location."),
    "open_tiktok": ("window", "Opens TikTok LIVE Studio now, to set up its window capture or test it."),
    "chat_id": ("chat", "After you message your Telegram bot once, finds your chat id and fills it in."),
    "radar_preview": ("eye", "Builds the Market Radar report and shows it in the log below (nothing is sent)."),
    "radar_send": ("send", "Builds the Market Radar report and sends it to your Telegram now."),
    "connect_youtube": ("link", "Opens Google sign-in so the bot can create and end YouTube broadcasts on your channel."),
    "browse": ("folder", "Pick the file or folder instead of typing it."),
}


class Tooltip:
    """A small note that appears when the mouse rests on a widget."""

    def __init__(self, widget, text: str, delay_ms: int = 450):
        self.widget, self.text, self.delay, self.job, self.tip = widget, text, delay_ms, None, None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _=None):
        self._hide()
        self.job = self.widget.after(self.delay, self._show)

    def _show(self):
        import tkinter as tk
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", wraplength=340, padx=8, pady=5, bg="#0f172a", fg="#e2e8f0",
                 relief="solid", borderwidth=1, font=("Segoe UI", 9)).pack()

    def _hide(self, _=None):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


_ICONS: dict[str, object] = {}


def icon(name: str):
    """A button icon from assets/icons (cached; None when the file is missing)."""
    if name not in _ICONS:
        path = ICON_DIR / f"{name}.png"
        try:
            import tkinter as tk
            _ICONS[name] = tk.PhotoImage(file=str(path)) if path.exists() else None
        except Exception:
            _ICONS[name] = None
    return _ICONS[name]



def _fresh(ap: dict, now: datetime | None = None, minutes: float = 3) -> bool:
    try:
        read = datetime.fromisoformat(ap["read"])
    except Exception:
        return False
    return ((now or datetime.now(read.tzinfo)) - read).total_seconds() < minutes * 60


def _money(n) -> str:
    return "" if n is None else f"{'-' if n < 0 else '+'}${abs(n):,.2f}"


AUTOPILOT_WORD = {"ok": "TRADING", "waiting": "WAITING", "failed": "PROBLEM", "off": "–"}
AUTOPILOT_COLOR = {"ok": "#3fb950", "waiting": "#f0883e", "failed": "#f85149", "off": "#e6edf3"}


def autopilot_row(ap: dict, now: datetime | None = None) -> tuple[str, str]:
    """The Autopilot node on the Status tab: (state, detail) from the Autopilot window's own summary."""
    if not ap or not _fresh(ap, now):
        return "off", "not running"
    if not ap.get("window"):
        return "waiting", "window not open"
    if not ap.get("enabled"):
        return "failed", "'Run every market day' off"
    if not ap.get("connected"):
        return "failed", "IBKR not connected"
    if not ap.get("trading"):
        return "waiting", "waits for 9:30 NY"
    trades = ap.get("trades") or []
    opened = sum(1 for t in trades if t.get("status") == "open")
    return "ok", f"trading · {opened} open · {len(trades) - opened} closed"


def autopilot_summary(ap: dict, now: datetime | None = None) -> str:
    if not ap or not _fresh(ap, now) or not ap.get("window"):
        return "Autopilot isn't open on this PC (it opens in the Website data window or with the stream)."
    trades = ap.get("trades") or []
    closed = [t for t in trades if t.get("status") != "open" and t.get("pnl") is not None]
    total = sum(t["pnl"] for t in closed)
    wins = sum(1 for t in closed if t["pnl"] > 0)
    bt = ap.get("botTrader") or {}
    parts = [ap.get("state") or "", f"closed today {_money(total) if closed else '$0.00'}"
             + (f" ({wins}/{len(closed)} won)" if closed else "")]
    if bt.get("halt"):
        parts.append(f"Bot Trader halted: {bt['halt']}")
    if ap.get("alerts"):
        parts.append(f"{ap['alerts']} Monitor alert(s)")
    return " · ".join(p for p in parts if p)


def trade_rows(ap: dict, now: datetime | None = None) -> list[tuple]:
    """Today's simulated trades for the table: newest first, times in New York."""
    if not ap or not _fresh(ap, now):
        return []
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    out = []
    for t in ap.get("trades") or []:
        try:
            at = datetime.fromtimestamp(t["at"] / 1000, ny).strftime("%H:%M")
        except Exception:
            at = ""
        price = lambda v: "" if v is None else f"{v:,.2f}"  # noqa: E731
        out.append((at, t.get("source", ""), t.get("symbol", ""), t.get("side", ""), t.get("status", ""),
                    price(t.get("entry")), price(t.get("exit")), _money(t.get("pnl"))))
    return out


def make_button(parent, text: str, command, key: str, **kw):
    """A button with its icon and hover tip."""
    from tkinter import ttk
    name, tip = BUTTONS[key]
    image = icon(name)
    button = ttk.Button(parent, text=f" {text}" if image else text, command=command,
                        **({"image": image, "compound": "left"} if image else {}), **kw)
    button._tip = Tooltip(button, tip)
    return button


def set_button(button, text: str, key: str) -> None:
    """Change a toggle button's label, icon and tip together (Start/Stop)."""
    name, tip = BUTTONS[key]
    image = icon(name)
    button.configure(text=f" {text}" if image else text, **({"image": image} if image else {}))
    button._tip.text = tip
ICON_ICO = BOT_DIR / "assets" / "app.ico"
ICON_PNG = BOT_DIR / "assets" / "app-256.png"


def set_app_icon(root) -> None:
    """The AiAlgobot icon on the window, and on the taskbar (Windows groups the app under its own id,
    not python's). Missing files just leave the default icon."""
    try:
        if os.name == "nt" and ICON_ICO.exists():
            root.iconbitmap(default=str(ICON_ICO))
        elif ICON_PNG.exists():
            import tkinter as tk
            root._icon = tk.PhotoImage(file=str(ICON_PNG))  # keep a reference or Tk drops it
            root.iconphoto(True, root._icon)
    except Exception:
        pass


def shortcut_ps(bot_dir: Path, desktop: Path) -> str:
    """PowerShell that makes a desktop shortcut starting the app without a console window."""
    pythonw = bot_dir / ".venv" / "Scripts" / "pythonw.exe"
    q = lambda p: str(p).replace("'", "''")
    lnk = q(desktop / f"{APP_NAME}.lnk")
    # Replace an older copy (Windows keeps showing a cached icon for a shortcut it already knows).
    return (f"Remove-Item -LiteralPath '{lnk}' -Force -ErrorAction SilentlyContinue; "
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut('" + lnk + "'); "
            f"$s.TargetPath = '{q(pythonw)}'; $s.Arguments = '\"{q(bot_dir / 'live_gui.py')}\"'; "
            f"$s.WorkingDirectory = '{q(bot_dir)}'; $s.IconLocation = '{q(bot_dir / 'assets' / 'app.ico')},0'; "
            f"$s.Description = '{APP_NAME} - live stream and trading bot'; $s.Save(); "
            # Ask Explorer to redraw icons now instead of showing the cached one.
            "Start-Process -FilePath ie4uinit.exe -ArgumentList '-show' -ErrorAction SilentlyContinue")


def main() -> None:
    try:
        import tkinter as tk
    except ImportError:
        sys.exit("Tkinter is missing - on Linux run: sudo apt install python3-tk")
    if os.name == "nt":
        try:  # its own taskbar button and icon instead of python's
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AiAlgoPro.AiAlgobot")
        except Exception:
            pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
