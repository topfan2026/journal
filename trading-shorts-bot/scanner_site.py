"""Browser agent's plumbing: open your scanner website (aialgopro.com) and start the scanner.

Runs a real, visible browser window through Playwright with its own profile folder
(~/TradingShorts/Live/browser-profile), so you log in to the site once with
`python live.py site-login` and the login is remembered every morning after that.
OBS shows this window with a Window Capture source that you add once.

What the agent does on the site is a list of steps in scanner_steps.txt (editable in
the app's "Scanner site" tab), one per line, run top to bottom. Buttons inside an open
popup are tried before the rest of the page:

    goto https://aialgopro.com      open an address (or a path like /scanner)
    click Connection                click the button / link / tab / menu item with that text
    click css=#fullscreen           ... or the element matching a CSS selector
    click at 16,14                  ... or a spot in the window (x,y from its top-left), for icon buttons
    type Local connector secret = {SCANNER_SECRET}
                                    fill a text box ({NAME} = a value saved in .env)
    select IBKR Gateway             pick that option in a drop-down list
    wait Connected                  wait until that text shows on the page
    wait 5                          wait 5 seconds
    key F11                         press a key
    fullscreen                      make the browser window full screen (like F11)
    maximize                        maximise the window (the [] button) - done automatically for apps
    hide A row is tinted            hide text on the page that starts with these words
    ifnot Terminal / Connection     only when that is NOT on screen (e.g. a closed menu), do the steps
      click Scanner                 up to the matching 'end'
    end
    if Gateway Paper                only when that shows up (within 10s), do the steps
      ...                           up to the matching 'end'; otherwise skip them
    end
    # comment                       ignored

Without a steps file it opens SCANNER_URL and, if set, clicks SCANNER_START_TEXT /
SCANNER_START_SELECTOR and waits for SCANNER_READY_SELECTOR.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from config import BOT_DIR, env, env_bool, env_float

log = logging.getLogger(__name__)

DEFAULT_URL = "https://aialgopro.com"


CLICK_ROLES = ("button", "link", "tab", "menuitem", "option", "radio", "checkbox", "switch")
VERBS = ("goto", "click", "select", "type", "wait", "key", "fullscreen", "maximize", "hide", "if", "ifnot", "end")
AT_POINT = re.compile(r"^at\s+(\d+)\s*,\s*(\d+)$", re.IGNORECASE)  # "click at 16,14"
DIALOGS = "[role=dialog]:visible, [role=alertdialog]:visible, [aria-modal=true]:visible, dialog[open]"

DEFAULT_STEPS = """\
# What the bot does on the site every morning, top to bottom.
# Make the words after click / wait / type / if match the site exactly.
# Steps: goto <address>, click <text>, type <box> = <text>, wait <text or seconds>,
#        fullscreen (the whole browser window, like F11), key <F11>, hide <start of a text>,
#        if <text> ... end   = only do the lines in between when <text> shows up
goto https://aialgopro.com
click Scanner
click Scan Market
if Gateway Paper
  click Gateway Paper
  type Local connector secret = {SCANNER_SECRET}
  click Test connector
  wait Connected
  click Connect read-only
end
# The connection window doesn't always close by itself: Esc, then its Close button.
if Private IBKR Gateway setup
  key Escape
end
if Private IBKR Gateway setup
  click Close
end
# Stream Mode, then the wall layout picked in the app (Scanner site tab > Wall layout on the stream).
select Stream Mode
wait 5
select {SCANNER_LAYOUT}
wait 10
click Full screen
hide A row is tinted
"""


# Pins the page title, whatever the site sets it to.
TITLE_JS = """(() => {
  // The Autopilot window (opened with ?bot=trading) gets its own title, so OBS never captures it.
  const title = location.search.includes('bot=trading') ? __TRADING__ : __TITLE__;
  const fix = () => { if (document.title !== title) document.title = title; };
  const watch = () => {
    fix();
    const head = document.querySelector('head') || document.documentElement;
    new MutationObserver(fix).observe(head, { childList: true, subtree: true, characterData: true });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', watch); else watch();
})();"""


# Hides every text-only element whose text starts with the given words, and keeps hiding it
# when the page redraws (the scanner re-renders every few seconds).
HIDE_JS = """(start) => {
  const want = start.trim().toLowerCase();
  const sweep = () => {
    for (const el of document.querySelectorAll('p, span, div, small, li')) {
      if (el.childElementCount === 0 && el.style.display !== 'none'
          && (el.textContent || '').trim().toLowerCase().startsWith(want)) {
        el.style.setProperty('display', 'none', 'important');
      }
    }
  };
  sweep();
  let queued = false;
  new MutationObserver(() => {
    if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; sweep(); }); }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
}"""


class SiteError(Exception):
    pass


def whole_words(text: str, negatable: bool = False) -> re.Pattern:
    """Match *text* as whole words; with negatable, not when it reads "not <text>" (e.g. Not connected)."""
    no = r"(?<!not )(?<!no )" if negatable else ""
    return re.compile(rf"{no}(?<![\w]){re.escape(text.strip())}(?![\w])", re.IGNORECASE)


def close_app(exe: Path | None, proc=None) -> None:
    """Close the desktop scanner app (the one we started, or any running copy of it)."""
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(10)
        except Exception:
            proc.kill()
    if exe is None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/IM", exe.name], capture_output=True)
    else:
        out = subprocess.run(["pgrep", "-f", "--", str(exe)], capture_output=True, text=True).stdout
        for pid in out.split():
            if pid.isdigit() and int(pid) not in (os.getpid(), os.getppid()):
                subprocess.run(["kill", "-9", pid], capture_output=True)


def close_stale_browsers(profile_dir: Path) -> int:
    """Kill browser processes started with --user-data-dir=<profile_dir> (the bot's own profile)."""
    profile = str(profile_dir.resolve())
    try:
        if os.name == "nt":
            ps = ("$p = '" + profile.replace("'", "''") + "'; "
                  "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe' OR Name='msedge.exe'\" | "
                  "Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($p.ToLower()) } | "
                  "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $_.ProcessId }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                                 timeout=30).stdout
        else:
            out = subprocess.run(["pgrep", "-f", "--", f"--user-data-dir={profile}"], capture_output=True, text=True).stdout
            for pid in out.split():
                subprocess.run(["kill", "-9", pid], capture_output=True)
        return len([line for line in out.split() if line.strip().isdigit()])
    except Exception as e:  # never block the morning run on this
        log.debug("stale browser check failed: %s", e)
        return 0


def use_app() -> bool:
    """SCANNER_SOURCE=app streams the desktop scanner app; anything else the website."""
    return (env("SCANNER_SOURCE", "website") or "website").lower() == "app"


def app_path() -> Path | None:
    """SCANNER_APP: the desktop scanner app (Electron, e.g. Farhad AI Scanner.exe), used when SCANNER_SOURCE=app."""
    path = env("SCANNER_APP")
    return Path(path).expanduser() if (path and use_app()) else None


def browser_exe() -> str:
    """The executable name OBS sees for the bot's browser window."""
    if app_path():
        return app_path().name
    if env("BROWSER_PATH"):
        return Path(env("BROWSER_PATH")).name
    return "msedge.exe" if (env("BROWSER_CHANNEL", "chrome") or "").startswith("msedge") else "chrome.exe"


TITLE_SUFFIXES = {"chrome.exe": " - Google Chrome", "msedge.exe": " - Microsoft\u200b Edge"}


def os_window_title() -> str:
    """The bot window's title as Windows/OBS sees it: the page title plus the browser's suffix,
    e.g. "LIVE BOT - Scanner - Google Chrome". Read from the real window when possible."""
    title = window_title()
    found = _find_window_title(title) if os.name == "nt" and title else None
    if app_path():  # an app window's title is just its page title, no browser name added
        return found or title
    return found or title + TITLE_SUFFIXES.get(browser_exe().lower(), " - Chromium")


def _find_window_title(prefix: str) -> str | None:
    """Windows only: the title of the visible top-level browser window whose title starts with *prefix*."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        found: list[str] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                cls = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, cls, 64)
                if buf.value.startswith(prefix) and cls.value == "Chrome_WidgetWin_1":
                    found.append(buf.value)
            return True
        user32.EnumWindows(visit, 0)
        return found[0] if found else None
    except Exception as e:  # fall back to the known suffix
        log.debug("window lookup failed: %s", e)
        return None


def _win_maximize(title: str) -> bool:
    """Windows only: maximise and bring forward the visible window whose title starts with *title*."""
    if os.name != "nt" or not title:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        hits: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if buf.value.startswith(title):
                    hits.append(hwnd)
            return True
        user32.EnumWindows(visit, 0)
        for hwnd in hits:
            user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
            user32.SetForegroundWindow(hwnd)
        return bool(hits)
    except Exception as e:
        log.debug("window maximise failed: %s", e)
        return False


def _win_restore(title: str) -> bool:
    """Windows only: if the window titled *title* is minimised, maximise it again. True if it was."""
    if os.name != "nt" or not title:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        restored = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def visit(hwnd, _):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if buf.value.startswith(title) and user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
                restored.append(hwnd)
            return True
        user32.EnumWindows(visit, 0)
        return bool(restored)
    except Exception as e:
        log.debug("window restore failed: %s", e)
        return False


def window_title() -> str:
    return env("BROWSER_WINDOW_TITLE", "LIVE BOT - Scanner") or ""


TRADING_TITLE = "LIVE BOT - Trading"


def title_js(title: str) -> str:
    return TITLE_JS.replace("__TITLE__", json.dumps(title)).replace("__TRADING__", json.dumps(TRADING_TITLE))


def autopilot_wanted() -> bool:
    """Open the site's Autopilot page (it runs the simulated traders 9:30-16:00 New York) next to the scanner."""
    return env_bool("AUTOPILOT_WINDOW", True) and not app_path()


def autopilot_url(base: str) -> str:
    return base.split("#", 1)[0].split("?", 1)[0].rstrip("/") + "/?bot=trading#/autopilot"


def steps_file(app: bool | None = None) -> Path:
    """Website steps and desktop-app steps are kept in separate files, so switching keeps both."""
    app = use_app() if app is None else app
    default = BOT_DIR / ("scanner_steps_app.txt" if app else "scanner_steps.txt")
    key = "SCANNER_APP_STEPS_FILE" if app else "SCANNER_STEPS_FILE"
    return Path(env(key, str(default))).expanduser()


DEFAULT_APP_STEPS = """\
# Farhad AI Scanner, every morning (IB Gateway is already logged in to paper by the bot).
# The app remembers how it was left, so each part only acts when needed.
wait 5
# show the side menu if it's hidden (the corner button reads ☰ when hidden, ◧ when shown)
ifnot ◧
  click ☰
end
ifnot Terminal / Connection
  click Scanner
end
click Terminal / Connection
if DISCONNECTED
  select IB Gateway
  select Paper
  type Port = 4002
  click Connect
  wait Connected
end
click Scanner
wait Top Gainers
wait 5
# hide the tools, then the side menu - only if they're showing
ifnot Show tools
  click Clean view
end
ifnot ☰
  click ◧
end
"""


def default_steps(app: bool | None = None) -> str:
    return DEFAULT_APP_STEPS if (use_app() if app is None else app) else DEFAULT_STEPS


def parse_steps(text: str) -> list[tuple[str, str]]:
    steps, depth = [], 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        verb, _, arg = line.partition(" ")
        verb, arg = verb.lower(), arg.strip()
        if verb not in VERBS:
            raise SiteError(f"scanner steps line {n}: unknown step {verb!r} (use {', '.join(VERBS)})")
        if verb == "fullscreen":
            steps.append((verb, arg or "on"))
            continue
        if verb == "maximize":
            steps.append((verb, arg or "window"))
            continue
        if verb == "end":
            depth -= 1
            if depth < 0:
                raise SiteError(f"scanner steps line {n}: 'end' without an 'if' above it")
            steps.append((verb, ""))
            continue
        if not arg:
            raise SiteError(f"scanner steps line {n}: {verb!r} needs something after it")
        if verb in ("if", "ifnot"):
            depth += 1
        if verb == "type" and "=" not in arg:
            raise SiteError(f"scanner steps line {n}: write it as  type <box name> = <text>")
        steps.append((verb, arg))
    if depth:
        raise SiteError("scanner steps: an 'if' is missing its 'end'")
    return steps


def skip_block(steps: list[tuple[str, str]], i: int) -> int:
    """Index of the 'end' that closes the 'if' at index *i*."""
    depth = 0
    for j in range(i, len(steps)):
        if steps[j][0] in ("if", "ifnot"):
            depth += 1
        elif steps[j][0] == "end":
            depth -= 1
            if depth == 0:
                return j
    return len(steps)


# Names the steps may use without setting them first.
EXPAND_DEFAULTS = {"SCANNER_LAYOUT": "A+ setups"}


def expand(text: str) -> str:
    """Replace {SCANNER_SECRET}-style names with values from .env, so secrets stay out of the steps."""
    def value(m):
        v = env(m.group(1), EXPAND_DEFAULTS.get(m.group(1)))
        if v is None:
            raise SiteError(f"{{{m.group(1)}}} is used in the steps but not set (Scanner site tab)")
        return v
    return re.sub(r"\{([A-Z][A-Z0-9_]*)\}", value, text)


def shown(verb: str, arg: str) -> str:
    """A step as it may appear in logs: what a 'type' step enters is hidden."""
    if verb == "type":
        return f"type {arg.partition('=')[0].strip()} = ******"
    return f"{verb} {arg}"


def use_layout_setting(text: str) -> str:
    """Older saved steps picked the "YouTube" layout by name; point that line at the app's drop-down."""
    return re.sub(r"(?mi)^(\s*)select YouTube\s*$", r"\1select {SCANNER_LAYOUT}", text)


def connect_steps(steps: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The steps up to the IBKR connection: everything before Stream Mode / full screen.
    Used by Website data only, which signs in and connects but doesn't set up the stream view."""
    for i, (verb, arg) in enumerate(steps):
        text = arg.strip().lower()
        if "stream mode" in text or verb in ("fullscreen", "hide") or text == "full screen":
            return steps[:i]
    return steps


def load_steps() -> list[tuple[str, str]]:
    path = steps_file()
    return parse_steps(use_layout_setting(path.read_text(encoding="utf-8"))) if path.exists() else []


class ScannerSite:
    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = self.context = self.page = None
        self.trading_page = None
        self.want_fullscreen = False

    # ------------------------------------------------------------------ browser
    def open(self) -> "ScannerSite":
        if app_path():
            return self.open_app()
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        # A bot browser left over from an earlier run holds this profile; Chrome would then hand
        # over to it and exit at once. Only browsers using the bot's own profile are closed.
        closed = close_stale_browsers(self.profile_dir)
        if closed:
            log.warning("browser: closed %d leftover bot browser process(es) using its profile", closed)
            time.sleep(2)
        self._pw = sync_playwright().start()
        kwargs = dict(
            headless=False, no_viewport=True,
            # The Autopilot window is often behind the scanner: keep Chrome from slowing its timers down.
            args=["--start-maximized", "--disable-background-timer-throttling",
                  "--disable-backgrounding-occluded-windows", "--disable-renderer-backgrounding"],
            # No "controlled by automated test software" / "--no-sandbox" bars on the stream.
            # (Chrome's sandbox can't run as root on Linux, so it stays off there.)
            chromium_sandbox=env_bool("BROWSER_SANDBOX", os.name == "nt" or sys.platform == "darwin"),
            ignore_default_args=["--enable-automation"],
        )
        channel = env("BROWSER_CHANNEL", "chrome")  # chrome | msedge | chromium (Playwright's own)
        if env("BROWSER_PATH"):  # any Chromium-based browser executable
            kwargs["executable_path"] = str(Path(env("BROWSER_PATH")).expanduser())
            channel = "chromium"
        try:
            self.context = self._pw.chromium.launch_persistent_context(
                str(self.profile_dir), **({"channel": channel} if channel != "chromium" else {}), **kwargs)
        except Exception as e:
            if channel == "chromium":
                raise
            log.warning("browser: %s not available (%s) - using Playwright's Chromium", channel, e)
            self.context = self._pw.chromium.launch_persistent_context(str(self.profile_dir), **kwargs)
        # Leave the site's own pop-ups ("Delete this watchlist? OK / Cancel") on screen for you to
        # answer. Without a listener, Playwright silently clicks Cancel on every one of them.
        # Give the bot's window one fixed title ("LIVE BOT - Scanner"), so OBS's Window Capture set to
        # "Window title must match" always finds it and never grabs your everyday browser instead.
        title = window_title()
        if title:
            self.context.add_init_script(title_js(title))
        for page in self.context.pages:
            self._keep_dialogs(page)
        self.context.on("page", self._keep_dialogs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def open_app(self) -> "ScannerSite":
        """Start the desktop app with Chromium's remote-debugging port and drive its window."""
        import urllib.request

        from playwright.sync_api import sync_playwright

        exe = app_path()
        if not exe.exists():
            raise SiteError(f"scanner app not found: {exe}")
        port = int(env_float("SCANNER_APP_PORT", 9333))
        close_app(exe)  # it must start with the debugging port, so a copy that's already open is closed
        args = [str(exe), f"--remote-debugging-port={port}", *shlex.split(env("SCANNER_APP_ARGS", "") or "",
                                                                            posix=os.name != "nt")]
        kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        self._app = subprocess.Popen(args, cwd=str(exe.parent), stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, **kwargs)
        endpoint = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + env_float("SCANNER_APP_START_TIMEOUT", 60)
        while True:
            try:
                urllib.request.urlopen(endpoint + "/json/version", timeout=2).read()
                break
            except Exception:
                if self._app.poll() is not None:
                    raise SiteError(f"{exe.name} exited right after starting (code {self._app.returncode})")
                if time.monotonic() > deadline:
                    raise SiteError(f"{exe.name} started but its window never became controllable on port {port}")
                time.sleep(1)
        self._pw = sync_playwright().start()
        browser = self._pw.chromium.connect_over_cdp(endpoint)
        self.context = browser.contexts[0] if browser.contexts else browser.new_context()
        deadline = time.monotonic() + 30
        while not [p for p in self.context.pages if not p.url.startswith("devtools://")]:
            if time.monotonic() > deadline:
                raise SiteError(f"{exe.name} opened no window")
            time.sleep(0.5)
        self.page = next(p for p in self.context.pages if not p.url.startswith("devtools://"))
        for page in self.context.pages:
            self._keep_dialogs(page)
        self.context.on("page", self._keep_dialogs)
        title = window_title()
        if title:  # for reloads, and right now for the window that is already open
            self.context.add_init_script(title_js(title))
            self.page.evaluate(title_js(title))
        if env_bool("SCANNER_APP_MAXIMIZE", True):
            time.sleep(0.5)  # let the pinned title reach the window first
            if not self.maximize_window():
                log.warning("browser: couldn't maximise the %s window - add a 'maximize' step", exe.name)
        log.info("browser: driving %s (%s)", exe.name, self.page.url)
        return self

    @staticmethod
    def _keep_dialogs(page) -> None:
        page.on("dialog", lambda dialog: log.info("browser: site asks %r - waiting for you to answer it",
                                                  dialog.message[:80]))

    def close(self) -> None:
        app = getattr(self, "_app", None)
        closers = [getattr(self._pw, "stop", None)] if app else \
            [getattr(self.context, "close", None), getattr(self._pw, "stop", None)]
        for closer in closers:
            try:
                if closer:
                    closer()
            except Exception:
                pass
        if app is not None:
            close_app(app_path(), proc=app)
            self._app = None
        self._pw = self.context = self.page = self.trading_page = None

    # ------------------------------------------------------------------ autopilot window
    def ensure_autopilot(self) -> str:
        """The Autopilot page in its own window ("LIVE BOT - Trading"), opened once and reopened if closed.
        The scanner window stays in front, so the stream never shows it. Never raises: the stream matters more."""
        if not autopilot_wanted() or self.context is None or self.page is None:
            return ""
        try:
            if self.trading_page is not None and not self.trading_page.is_closed():
                return "autopilot open"
            url = autopilot_url(self.page.url if self.page.url.startswith("http") else self.url)
            cdp = self.context.new_cdp_session(self.page)
            cdp.send("Target.createTarget", {"url": url, "newWindow": True, "background": True})
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                found = [p for p in self.context.pages if "bot=trading" in p.url]
                if found:
                    self.trading_page = found[-1]
                    break
                time.sleep(0.25)
            self.page.bring_to_front()
            if self.trading_page is None:
                return "autopilot window didn't open"
            log.info("browser: Autopilot open in its own window (%s)", url)
            return "autopilot opened"
        except Exception as e:  # noqa: BLE001
            log.warning("browser: couldn't open the Autopilot window: %s", e)
            return ""

    def autopilot_status(self) -> dict | None:
        """What the Autopilot window says about itself (state, each trader, today's trades); None when the
        window isn't open or the page is too old to say. Never raises."""
        try:
            if self.trading_page is None or self.trading_page.is_closed():
                return None
            snap = self.trading_page.evaluate("() => window.__aialgoAutopilot || null")
            return snap if isinstance(snap, dict) else None
        except Exception as e:  # noqa: BLE001
            log.debug("autopilot status: %s", e)
            return None

    def reload_autopilot(self) -> str:
        """Reload the Autopilot window (after live data came back), so its traders reconnect. Its books are kept
        in the browser, so open simulated positions carry on. Never raises."""
        try:
            if self.trading_page is not None and not self.trading_page.is_closed():
                self.trading_page.reload(wait_until="domcontentloaded")
                self.page.bring_to_front()
                log.info("browser: reloaded the Autopilot window")
                return "autopilot reloaded"
        except Exception as e:  # noqa: BLE001
            log.warning("browser: couldn't reload the Autopilot window: %s", e)
        return ""

    @property
    def url(self) -> str:
        return env("SCANNER_URL", DEFAULT_URL) or DEFAULT_URL

    # ------------------------------------------------------------------ scanner
    def start_scanner(self, connect_only: bool = False) -> dict:
        steps = load_steps()
        if connect_only:
            steps = connect_steps(steps)
        if steps:
            idx = 0
            while idx < len(steps):
                verb, arg = steps[idx]
                i = idx + 1
                idx += 1
                if verb == "end":
                    continue
                log.info("browser: step %d/%d: %s", i, len(steps), shown(verb, arg))
                if verb == "if":
                    if not self.exists(arg):
                        log.info("browser: %r isn't on screen - skipping to its 'end'", arg)
                        idx = skip_block(steps, i - 1) + 1
                    continue
                if verb == "ifnot":
                    if self.exists(arg, seconds=env_float("SCANNER_IFNOT_SECONDS", 3)):
                        log.info("browser: %r is already on screen - skipping to its 'end'", arg)
                        idx = skip_block(steps, i - 1) + 1
                    continue
                try:
                    try:
                        self.step(verb, arg)
                    except Exception:
                        # A step that fails because the site is asking to sign in: sign in, then try it again.
                        if not self.sign_in_if_needed():
                            raise
                        self.step(verb, arg)
                    self.sign_in_if_needed()  # the step may have landed on the sign-in page
                except Exception as e:
                    if "has been closed" in str(e):
                        raise SiteError(f"scanner step {i} stopped: the browser window was closed "
                                        "(by hand, or by another test started at the same time)") from e
                    seen = self.visible_labels()
                    raise SiteError(f"scanner step {i} '{shown(verb, arg)}' failed on {self.page.url}: "
                                    f"{str(e).splitlines()[0]}. Check the wording in the Scanner site tab; "
                                    "if the site wants you to sign in, use 'Sign in to scanner site'."
                                    + (f"\n  On screen right now: {seen}" if seen else "")) from e
            clicked = f"{len(steps)} steps"
        else:
            clicked = self._legacy_start()
        self.ensure_autopilot()
        self.page.bring_to_front()
        log.info("browser: scanner running at %s (%s)", self.page.url, self.page.title())
        return {"url": self.page.url, "title": self.page.title(), "clicked": clicked}

    # ------------------------------------------------------------------ sign-in
    PASSWORD_BOX = "input[type=password], input#auth-password"
    LOGIN_BOX = "input#auth-email, input[type=email], input[autocomplete=username], input[autocomplete=email]"

    def sign_in_if_needed(self) -> bool:
        """If the page is showing a sign-in form, sign in and press its button.

        Uses SCANNER_EMAIL / SCANNER_PASSWORD (Scanner site tab) when set; otherwise the browser's own
        autofill -- Chrome only hands autofilled values to the page after a real click, so the bot clicks
        into the box first. Returns True when it signed in, False when no sign-in form is showing."""
        page = self.page
        password = page.locator(self.PASSWORD_BOX).first
        try:
            if not password.is_visible():
                return False
        except Exception:
            return False
        login = page.locator(self.LOGIN_BOX).first
        email, secret = env("SCANNER_EMAIL"), env("SCANNER_PASSWORD")
        log.info("browser: the site is asking to sign in - signing in%s",
                 "" if email and secret else " with the browser's saved login")
        if email and secret:
            if login.count() and login.is_visible():
                self.replace_text(login, email)
            self.replace_text(password, secret)
        else:
            # Release Chrome's autofill: values aren't visible to the page until the user interacts.
            (login if login.count() and login.is_visible() else password).click()
            page.wait_for_timeout(800)
            if not password.input_value():
                raise SiteError("the scanner site wants you to sign in, but there's no saved login: fill in "
                                "'Site email' and 'Site password' in the Scanner site tab (or use 'Sign in to "
                                "scanner site' once)")
        form = password.locator("xpath=ancestor::form[1]")
        submit = form.locator("button[type=submit], button:not([type]), input[type=submit]").first \
            if form.count() else page.locator("button[type=submit]").first
        if submit.count():
            submit.click(timeout=self.timeout * 1000)
        else:
            password.press("Enter")
        try:
            password.wait_for(state="hidden", timeout=env_float("SCANNER_SIGNIN_WAIT", 30) * 1000)
        except Exception:
            alert = page.locator("[role=alert]").first
            why = alert.inner_text().strip() if alert.count() and alert.is_visible() else "the form is still showing"
            raise SiteError(f"signing in to the scanner site didn't work: {why}")
        log.info("browser: signed in")
        page.wait_for_timeout(1500)
        return True

    # ------------------------------------------------------------------ steps
    @property
    def timeout(self) -> float:
        return env_float("SCANNER_TIMEOUT", 60)

    def step(self, verb: str, arg: str) -> None:
        page = self.page
        if verb == "goto":
            page.goto(urljoin(self.url, arg), wait_until="domcontentloaded", timeout=self.timeout * 1000)
        elif verb == "click" and AT_POINT.match(arg):
            # A button with no words (an icon): click a spot in the window, counted from its top-left corner.
            x, y = (int(v) for v in AT_POINT.match(arg).groups())
            page.mouse.click(x, y)
        elif verb in ("click", "select"):
            self.click_or_select(arg)
        elif verb == "type":
            label, _, text = arg.partition("=")
            self.replace_text(self.find(label.strip(), field=True), expand(text.strip()))
        elif verb == "wait":
            try:
                page.wait_for_timeout(float(arg) * 1000)
            except ValueError:
                self.find(arg, waiting=True)
        elif verb == "key":
            page.keyboard.press(arg)
        elif verb == "fullscreen":
            self.browser_fullscreen(arg.lower() not in ("off", "no", "false"))
        elif verb == "maximize":
            if not self.maximize_window():
                raise SiteError("couldn't maximise the window")
        elif verb == "hide":
            page.evaluate(HIDE_JS, arg)

    def maximize_window(self) -> bool:
        """Maximise the window (the [] button): Chrome's window API, else Windows itself (desktop apps)."""
        if getattr(self, "_app", None) is not None:
            # Desktop (Electron) apps may never answer Chrome's window API - the call would hang.
            return _win_maximize(os_window_title())
        cdp_ok = False
        try:
            cdp = self.context.new_cdp_session(self.page)
            try:
                window = cdp.send("Browser.getWindowForTarget")["windowId"]
                cdp.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "maximized"}})
                cdp_ok = True
            finally:
                cdp.detach()
        except Exception as e:  # Electron apps often don't offer the window API
            log.debug("CDP maximise failed: %s", e)
        # Some apps accept that request and ignore it, so on Windows also maximise the window directly.
        return _win_maximize(os_window_title()) or cdp_ok

    def restore_window(self) -> bool:
        """Un-minimise the bot's window (a minimised window streams as black). True if it was minimised."""
        if getattr(self, "_app", None) is not None:
            return _win_restore(os_window_title())
        cdp = self.context.new_cdp_session(self.page)
        try:
            window = cdp.send("Browser.getWindowForTarget")
            if window["bounds"].get("windowState") != "minimized":
                return False
            cdp.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "normal"}})
            if self.want_fullscreen:
                cdp.send("Browser.setWindowBounds",
                         {"windowId": window["windowId"], "bounds": {"windowState": "fullscreen"}})
            return True
        finally:
            cdp.detach()

    def browser_fullscreen(self, on: bool = True) -> None:
        """Make the Chrome window itself full screen (like F11) - no site button needed."""
        self.want_fullscreen = on
        if getattr(self, "_app", None) is not None:  # apps: maximise instead (see maximize_window)
            self.maximize_window()
            return
        cdp = self.context.new_cdp_session(self.page)
        try:
            window = cdp.send("Browser.getWindowForTarget")["windowId"]
            if on:  # Chrome only goes full screen from the normal state
                cdp.send("Browser.setWindowBounds", {"windowId": window, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds",
                     {"windowId": window, "bounds": {"windowState": "fullscreen" if on else "maximized"}})
        finally:
            cdp.detach()

    def replace_text(self, box, value: str) -> None:
        """Replace whatever is in the box (e.g. an old secret) with *value*."""
        box.fill(value, timeout=self.timeout * 1000)  # fill() clears the box first
        if box.input_value() == value:
            return
        # Some sites ignore fill(); do it like a person: click, select all, delete, type.
        box.click()
        select_all = "Meta+A" if self.page.evaluate("navigator.platform").startswith("Mac") else "Control+A"
        box.press(select_all)
        box.press("Delete")
        box.press_sequentially(value, delay=20)
        if box.input_value() != value:
            raise SiteError("the box didn't accept the text (it still holds something else)")

    def _candidates(self, scope, text: str, field: bool, waiting: bool = False) -> list:
        if text.startswith("css="):
            return [scope.locator(text[4:])]
        # Exact label first; then the words anywhere, but as whole words, so "Connect"
        # never matches "Connection" and "Connected" never matches "Disconnected".
        words = whole_words(text, negatable=waiting)
        if field:  # a text box, found by its label, placeholder or accessible name ...
            after = "xpath=following::*[self::input or self::textarea][1]"
            return [scope.get_by_label(text, exact=True), scope.get_by_placeholder(text, exact=True),
                    scope.get_by_role("textbox", name=text, exact=True),
                    scope.get_by_label(words), scope.get_by_placeholder(words),
                    scope.get_by_role("textbox", name=words),
                    # ... or the first box after that text, for pages whose label isn't linked to the box
                    scope.get_by_text(text, exact=True).locator(after),
                    scope.get_by_text(words).locator(after)]
        return ([scope.get_by_role(r, name=text, exact=True) for r in CLICK_ROLES]
                + [scope.get_by_text(text, exact=True)]
                + [scope.get_by_role(r, name=words) for r in CLICK_ROLES]
                + [scope.get_by_text(words)])

    def _select_option(self, text: str) -> bool:
        """Pick *text* in any visible drop-down list that has it (exact option text first, then whole words)."""
        boxes = self.page.locator("select")
        words = whole_words(text)
        for k in range(boxes.count()):
            box = boxes.nth(k)
            try:
                if not box.is_visible() or not box.is_enabled():
                    continue
                labels = [t.strip() for t in box.locator("option").all_inner_texts()]
            except Exception:
                continue
            match = next((t for t in labels if t.lower() == text.strip().lower()), None) \
                or next((t for t in labels if words.search(t)), None)
            if match:
                box.select_option(label=match)
                return True
        return False

    def click_or_select(self, arg: str) -> None:
        """Click the thing labelled *arg*; if it is an option in a drop-down list, select it instead."""
        if arg.startswith("css="):
            self.find(arg).click(timeout=self.timeout * 1000)
            return
        deadline = time.monotonic() + self.timeout
        while True:
            if self._select_option(arg):  # an option can't be clicked, it has to be selected
                return
            try:
                self.find(arg, timeout=1).click(timeout=self.timeout * 1000)
                return
            except SiteError:
                if time.monotonic() > deadline:
                    raise SiteError(f"nothing called {arg!r} appeared within {self.timeout:.0f}s")

    def visible_labels(self, limit: int = 40) -> str:
        """The words on visible buttons, links, tabs and menu items - to show what a step could click."""
        try:
            labels = self.page.evaluate("""(limit) => {
              const sel = 'button, a, [role=button], [role=tab], [role=menuitem], [role=link], li, summary, label';
              const out = [];
              for (const el of document.querySelectorAll(sel)) {
                const r = el.getBoundingClientRect();
                if (!r.width || !r.height || getComputedStyle(el).visibility === 'hidden') continue;
                const t = (el.innerText || el.getAttribute('aria-label') || el.title || '').trim().replace(/\\s+/g, ' ');
                if (t && t.length <= 40 && !out.includes(t)) out.push(t);
                if (out.length >= limit) break;
              }
              for (const sel of document.querySelectorAll('select')) {
                const r = sel.getBoundingClientRect();
                if (!r.width || !r.height) continue;
                const opts = [...sel.options].map(o => o.text.trim()).filter(Boolean).slice(0, 8);
                if (opts.length) out.push('list: ' + opts.join(' / '));
              }
              return out;
            }""", limit)
            return " | ".join(labels)
        except Exception:
            return ""

    def exists(self, text: str, seconds: float | None = None) -> bool:
        """For 'if'/'ifnot': does *text* show up within *seconds* (default SCANNER_IF_SECONDS = 10)?"""
        try:
            self.find(text, waiting=True, timeout=env_float("SCANNER_IF_SECONDS", 10) if seconds is None else seconds)
            return True
        except SiteError:
            return False

    def find(self, text: str, field: bool = False, waiting: bool = False, timeout: float | None = None):
        """The first visible match for *text*: inside an open popup first, then the whole page."""
        page = self.page
        timeout = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + timeout
        while True:
            dialogs = page.locator(DIALOGS)
            scopes = ([dialogs.last] if dialogs.count() else []) + [page]
            for scope in scopes:
                for c in self._candidates(scope, text, field, waiting):
                    try:
                        n = c.count()
                    except Exception:
                        continue
                    for k in range(min(n, 10)):
                        if c.nth(k).is_visible():
                            return c.nth(k)
            if time.monotonic() > deadline:
                what = "no box called" if field else "nothing called"
                raise SiteError(f"{what} {text!r} appeared within {timeout:.0f}s")
            page.wait_for_timeout(250)

    def _legacy_start(self) -> str | None:
        page = self.page
        timeout = self.timeout * 1000
        page.goto(self.url, wait_until="domcontentloaded", timeout=timeout)
        clicked = None
        text, selector = env("SCANNER_START_TEXT"), env("SCANNER_START_SELECTOR")
        if text or selector:
            target = page.locator(selector) if selector else page.get_by_text(text, exact=False)
            try:
                target.first.wait_for(state="visible", timeout=timeout)
            except Exception as e:
                raise SiteError(f"couldn't find the start button ({selector or text!r}) on {page.url}. "
                                "If the site asks you to sign in, run `python live.py site-login` once.") from e
            target.first.click()
            clicked = selector or text
        ready = env("SCANNER_READY_SELECTOR")
        if ready:
            try:
                page.locator(ready).first.wait_for(state="visible", timeout=timeout)
            except Exception as e:
                raise SiteError(f"scanner didn't show {ready!r} - is IB Gateway connected to the site?") from e
        return clicked

    def alive(self) -> bool:
        try:
            return self.page is not None and not self.page.is_closed() and bool(self.page.title() is not None)
        except Exception:
            return False

    def wait(self, seconds: float) -> None:
        """Sleep while letting Playwright process browser events."""
        if self.alive():
            self.page.wait_for_timeout(seconds * 1000)


def site_login(profile_dir: Path) -> None:
    """Open the site in the bot's browser profile so you can sign in once by hand."""
    site = ScannerSite(profile_dir).open()
    try:
        site.page.goto(site.url)
        print(f"Sign in to {site.url} in the browser window, check the scanner works, "
              "then close the browser window.", flush=True)
        site.page.wait_for_event("close", timeout=0)
    finally:
        site.close()
