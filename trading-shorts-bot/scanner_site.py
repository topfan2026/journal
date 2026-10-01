"""Browser agent's plumbing: open your scanner website (aialgopro.com) and start the scanner.

Runs a real, visible browser window through Playwright with its own profile folder
(~/TradingShorts/Live/browser-profile), so you log in to the site once with
`python live.py site-login` and the login is remembered every morning after that.
OBS shows this window with a Window Capture source that you add once.

How the "start" click is found (.env, all optional):
  SCANNER_START_TEXT      visible text of the button that starts the scanner, e.g. Start Scanner
  SCANNER_START_SELECTOR  or a CSS selector for it
  SCANNER_READY_SELECTOR  something that only shows once the scanner is running (waited for)
If none is set, the agent just opens SCANNER_URL (for pages that start scanning on load).
"""
from __future__ import annotations

import logging
from pathlib import Path

from config import env, env_float

log = logging.getLogger(__name__)

DEFAULT_URL = "https://aialgopro.com"


class SiteError(Exception):
    pass


class ScannerSite:
    def __init__(self, profile_dir: Path):
        self.profile_dir = profile_dir
        self._pw = self.context = self.page = None

    # ------------------------------------------------------------------ browser
    def open(self) -> "ScannerSite":
        from playwright.sync_api import sync_playwright

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs = dict(headless=False, no_viewport=True, args=["--start-maximized"])
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
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

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
        page = self.page
        timeout = env_float("SCANNER_TIMEOUT", 60) * 1000
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
        page.bring_to_front()
        log.info("browser: scanner running at %s (%s)", page.url, page.title())
        return {"url": page.url, "title": page.title(), "clicked": clicked}

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
