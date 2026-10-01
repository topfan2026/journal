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
    type Local connector secret = {SCANNER_SECRET}
                                    fill a text box ({NAME} = a value saved in .env)
    select IBKR Gateway             pick that option in a drop-down list
    wait Connected                  wait until that text shows on the page
    wait 5                          wait 5 seconds
    key F11                         press a key
    fullscreen                      make the browser window full screen (like F11)
    if Gateway Paper                only when that shows up (within 10s), do the steps
      ...                           up to the matching 'end'; otherwise skip them
    end
    # comment                       ignored

Without a steps file it opens SCANNER_URL and, if set, clicks SCANNER_START_TEXT /
SCANNER_START_SELECTOR and waits for SCANNER_READY_SELECTOR.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from config import BOT_DIR, env, env_bool, env_float

log = logging.getLogger(__name__)

DEFAULT_URL = "https://aialgopro.com"


CLICK_ROLES = ("button", "link", "tab", "menuitem", "option", "radio", "checkbox", "switch")
VERBS = ("goto", "click", "select", "type", "wait", "key", "fullscreen", "if", "end")
DIALOGS = "[role=dialog]:visible, [role=alertdialog]:visible, [aria-modal=true]:visible, dialog[open]"

DEFAULT_STEPS = """\
# What the bot does on the site every morning, top to bottom.
# Make the words after click / wait / type / if match the site exactly.
# Steps: goto <address>, click <text>, type <box> = <text>, wait <text or seconds>,
#        fullscreen (the whole browser window, like F11), key <F11>,
#        if <text> ... end   = only do the lines in between when <text> shows up
goto https://aialgopro.com
click Scanner
click Scan Market
if Gateway Paper
  click Gateway Paper
  type Local connector secret = {SCANNER_SECRET}
  click Test Connection
  wait Connected
end
wait 10
click Full screen
"""


class SiteError(Exception):
    pass


def whole_words(text: str, negatable: bool = False) -> re.Pattern:
    """Match *text* as whole words; with negatable, not when it reads "not <text>" (e.g. Not connected)."""
    no = r"(?<!not )(?<!no )" if negatable else ""
    return re.compile(rf"{no}(?<![\w]){re.escape(text.strip())}(?![\w])", re.IGNORECASE)


def steps_file() -> Path:
    return Path(env("SCANNER_STEPS_FILE", str(BOT_DIR / "scanner_steps.txt"))).expanduser()


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
        if verb == "end":
            depth -= 1
            if depth < 0:
                raise SiteError(f"scanner steps line {n}: 'end' without an 'if' above it")
            steps.append((verb, ""))
            continue
        if not arg:
            raise SiteError(f"scanner steps line {n}: {verb!r} needs something after it")
        if verb == "if":
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
        if steps[j][0] == "if":
            depth += 1
        elif steps[j][0] == "end":
            depth -= 1
            if depth == 0:
                return j
    return len(steps)


def expand(text: str) -> str:
    """Replace {SCANNER_SECRET}-style names with values from .env, so secrets stay out of the steps."""
    def value(m):
        v = env(m.group(1))
        if v is None:
            raise SiteError(f"{{{m.group(1)}}} is used in the steps but not set (Scanner site tab)")
        return v
    return re.sub(r"\{([A-Z][A-Z0-9_]*)\}", value, text)


def shown(verb: str, arg: str) -> str:
    """A step as it may appear in logs: what a 'type' step enters is hidden."""
    if verb == "type":
        return f"type {arg.partition('=')[0].strip()} = ******"
    return f"{verb} {arg}"


def load_steps() -> list[tuple[str, str]]:
    path = steps_file()
    return parse_steps(path.read_text(encoding="utf-8")) if path.exists() else []


class ScannerSite:
    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = self.context = self.page = None

    # ------------------------------------------------------------------ browser
    def open(self) -> "ScannerSite":
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs = dict(
            headless=False, no_viewport=True, args=["--start-maximized"],
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
        for page in self.context.pages:
            self._keep_dialogs(page)
        self.context.on("page", self._keep_dialogs)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    @staticmethod
    def _keep_dialogs(page) -> None:
        page.on("dialog", lambda dialog: log.info("browser: site asks %r - waiting for you to answer it",
                                                  dialog.message[:80]))

    def close(self) -> None:
        for closer in (getattr(self.context, "close", None), getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        self._pw = self.context = self.page = None

    @property
    def url(self) -> str:
        return env("SCANNER_URL", DEFAULT_URL) or DEFAULT_URL

    # ------------------------------------------------------------------ scanner
    def start_scanner(self) -> dict:
        steps = load_steps()
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
                try:
                    self.step(verb, arg)
                except Exception as e:
                    if "has been closed" in str(e):
                        raise SiteError(f"scanner step {i} stopped: the browser window was closed "
                                        "(by hand, or by another test started at the same time)") from e
                    raise SiteError(f"scanner step {i} '{shown(verb, arg)}' failed on {self.page.url}: "
                                    f"{str(e).splitlines()[0]}. Check the wording in the Scanner site tab; "
                                    "if the site wants you to sign in, use 'Sign in to scanner site'.") from e
            clicked = f"{len(steps)} steps"
        else:
            clicked = self._legacy_start()
        self.page.bring_to_front()
        log.info("browser: scanner running at %s (%s)", self.page.url, self.page.title())
        return {"url": self.page.url, "title": self.page.title(), "clicked": clicked}

    # ------------------------------------------------------------------ steps
    @property
    def timeout(self) -> float:
        return env_float("SCANNER_TIMEOUT", 60)

    def step(self, verb: str, arg: str) -> None:
        page = self.page
        if verb == "goto":
            page.goto(urljoin(self.url, arg), wait_until="domcontentloaded", timeout=self.timeout * 1000)
        elif verb in ("click", "select"):
            # An option inside a normal drop-down list can't be clicked, it has to be selected.
            box = page.locator("select").filter(has=page.locator("option", has_text=arg))
            if not arg.startswith("css=") and box.count() and box.first.is_visible():
                label = box.first.locator("option", has_text=arg).first.inner_text().strip()
                box.first.select_option(label=label)
            else:
                self.find(arg).click(timeout=self.timeout * 1000)
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

    def browser_fullscreen(self, on: bool = True) -> None:
        """Make the Chrome window itself full screen (like F11) - no site button needed."""
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

    def exists(self, text: str) -> bool:
        """For 'if': does *text* show up within SCANNER_IF_SECONDS (default 10)?"""
        try:
            self.find(text, waiting=True, timeout=env_float("SCANNER_IF_SECONDS", 10))
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
