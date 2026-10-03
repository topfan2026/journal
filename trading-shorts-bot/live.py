"""Daily live stream: IB Gateway -> scanner website -> OBS -> YouTube Live.

    python live.py daemon        wait, and go live every LIVE_DAYS at LIVE_START (default 06:00)
    python live.py run           go live now, stay live until LIVE_END / LIVE_DURATION_MIN, then end
    python live.py stop          end today's stream (from another terminal)
    python live.py check         check Gateway login, OBS, YouTube and the site's start button
    python live.py site-login    open the bot's browser once so you can sign in to the scanner site
    python live.py site-test     run just the scanner-site steps and leave the window open 60s
    options: --dry-run  (everything except starting the stream / creating the broadcast), -v

    Orchestrator
      1. GatewayAgent   IBC logs IB Gateway into the paper account, waits for the API port
      2. BrowserAgent   opens SCANNER_URL (aialgopro.com) and clicks the scanner's start button
      3. YouTubeAgent   today's broadcast (title, description, thumbnail) bound to a reusable key
      4. OBSAgent       launches OBS, switches to OBS_SCENE, sets the key, starts streaming
      5. Watchdog       every LIVE_CHECK_SECONDS: Gateway up? scanner page open? OBS streaming?
                        restarts whatever dropped, until LIVE_END, then ends the broadcast.

Today's YouTube broadcast id is kept in Live/<date>/session.json, so a re-run after a
crash reuses it instead of creating a second broadcast.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import ibkr
from config import ConfigError, Settings, env, env_bool, env_float, reload_env
from job import now_iso

log = logging.getLogger("live")

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


# --------------------------------------------------------------------------- time

def tz():
    name = env("LIVE_TZ")
    if not name:
        return datetime.now().astimezone().tzinfo  # this computer's clock
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def parse_hhmm(value: str) -> tuple[int, int]:
    h, m = value.strip().split(":")
    if not (0 <= int(h) < 24 and 0 <= int(m) < 60):
        raise ConfigError(f"bad time {value!r} (use HH:MM)")
    return int(h), int(m)


def live_days() -> set[int]:
    raw = (env("LIVE_DAYS", "mon-fri") or "mon-fri").lower().replace(" ", "")
    out: set[int] = set()
    for part in raw.split(","):
        if "-" in part:
            a, b = (DAYS.index(x[:3]) for x in part.split("-"))
            out.update(range(a, b + 1) if a <= b else [*range(a, 7), *range(0, b + 1)])
        elif part:
            out.add(DAYS.index(part[:3]))
    return out


def next_start(now: datetime) -> datetime:
    h, m = parse_hhmm(env("LIVE_START", "06:00") or "06:00")
    days = live_days()
    if not days:
        raise ConfigError("LIVE_DAYS selects no days")
    for add in range(8):
        cand = (now + timedelta(days=add)).replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now and cand.weekday() in days:
            return cand
    raise AssertionError("unreachable")


def end_time(start: datetime) -> datetime:
    end = env("LIVE_END")
    if end:
        h, m = parse_hhmm(end)
        e = start.replace(hour=h, minute=m, second=0, microsecond=0)
        if e > start:
            return e
        # Started at or after today's end time (e.g. "Go live now" in the afternoon): run for
        # LIVE_DURATION_MIN instead of until tomorrow's end time, which would overlap the next show.
    return start + timedelta(minutes=env_float("LIVE_DURATION_MIN", 240))


# --------------------------------------------------------------------------- session state

class Session:
    """Per-day checkpoint file: Live/<date>/session.json."""

    def __init__(self, folder: Path):
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "session.json"
        self.state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @property
    def stop_file(self) -> Path:
        return self.folder / "STOP"

    def get(self, key: str) -> dict:
        return self.state.get(key) or {}

    def set(self, key: str, value: dict) -> None:
        self.state[key] = {**value, "at": now_iso()}
        path = self.folder / "session.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def live_root(settings: Settings) -> Path:
    return settings.root / "Live"


def render(template: str, day: datetime) -> str:
    return template.replace("{date}", day.strftime("%b %d, %Y")).replace("{weekday}", day.strftime("%A"))


# --------------------------------------------------------------------------- agents

class GatewayAgent:
    name = "gateway"

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self) -> dict:
        root = live_root(self.settings)
        result = ibkr.start_gateway(root / ".ibc" / "config.ini", self.settings.logs / "ibgateway.log")
        if env_bool("IB_VERIFY_LOGIN", True):
            result["accounts"] = self.verify_login()
        log.info("[gateway] ready on port %s %s", result["port"], result.get("accounts", ""))
        return result

    @staticmethod
    def verify_login(sleep=time.sleep) -> list[str]:
        """Gateway opens its port before it accepts API logins, so retry for IB_LOGIN_WAIT seconds."""
        deadline = time.monotonic() + env_float("IB_LOGIN_WAIT", 90)
        while True:
            try:
                ib = ibkr.connect()  # also refuses a non-paper account
            except ibkr.IBKRError:
                raise
            except Exception as e:
                if time.monotonic() > deadline:
                    raise ibkr.IBKRError(f"IB Gateway is running but won't accept the API login: {e}") from e
                log.info("[gateway] not accepting connections yet - retrying")
                sleep(5)
                continue
            try:
                return ib.managedAccounts()
            finally:
                ib.disconnect()

    def healthy(self) -> bool:
        return ibkr.port_open(ibkr.host(), ibkr.port())


class BrowserAgent:
    name = "browser"

    def __init__(self, settings: Settings):
        from scanner_site import ScannerSite
        self.site = ScannerSite(live_root(settings) / "browser-profile")

    def run(self) -> dict:
        if not self.site.alive():
            self.site.close()
            self.site.open()
        result = self.site.start_scanner()
        warmup = env_float("SCANNER_WARMUP_SECONDS", 20)
        if warmup:
            self.site.wait(warmup)  # let the first results load before the stream starts
        return result

    def healthy(self) -> bool:
        return self.site.alive()

    def restore(self) -> bool:
        try:
            if self.site.alive() and self.site.restore_window():
                log.warning("[watchdog] the scanner window was minimised - restored it")
                return True
        except Exception as e:
            log.debug("restore failed: %s", e)
        return False

    def wait(self, seconds: float) -> None:
        if self.site.alive():
            self.site.wait(seconds)
        else:
            time.sleep(seconds)

    def close(self) -> None:
        self.site.close()


class YouTubeAgent:
    name = "youtube"

    def __init__(self, settings: Settings, session: Session, start: datetime):
        self.settings, self.session, self.start = settings, session, start
        self.yt = None

    def run(self) -> dict:
        import youtube_live as yl

        self.yt = yl.service()
        stream = yl.ensure_stream(self.yt)
        cached = self.session.get(self.name)
        if cached.get("broadcast_id") and yl.lifecycle(self.yt, cached["broadcast_id"]) not in (
                None, "complete", "revoked"):
            log.info("[youtube] reusing today's broadcast %s", cached["broadcast_id"])
            return {**cached, "stream": stream}
        from metadata import _no_angle, truncate
        title = truncate(_no_angle(render(env("LIVE_TITLE", "LIVE Stock Scanner | {weekday} {date}"), self.start)), 100)
        description = "\n\n".join(p for p in (
            render(env("LIVE_DESCRIPTION", "Live stock scanner, every trading morning.") or "", self.start),
            self.settings.disclaimer) if p)
        scheduled = max(self.start, datetime.now(tz()) + timedelta(minutes=1))
        bid = yl.create_broadcast(self.yt, title=title, description=_no_angle(description),
                                  start_iso=scheduled.isoformat(), privacy=self.start_privacy)
        yl.bind(self.yt, bid, stream["id"])
        tags = [t.strip() for t in (env("LIVE_TAGS", "") or "").split(",") if t.strip()]
        try:
            yl.tag(self.yt, bid, title=title, description=_no_angle(description), tags=tags)
        except Exception as e:
            log.warning("[youtube] couldn't set tags/category: %s", e)
        thumb = env("LIVE_THUMBNAIL")
        if thumb:
            try:
                yl.set_thumbnail(self.yt, bid, Path(thumb).expanduser())
            except Exception as e:
                log.warning("[youtube] thumbnail not set: %s", e)
        result = {"broadcast_id": bid, "url": f"https://www.youtube.com/watch?v={bid}", "title": title}
        self.session.set(self.name, result)
        log.info("[youtube] broadcast %s: %s", result["url"], title)
        return {**result, "stream": stream}

    @property
    def final_privacy(self) -> str:
        return env("LIVE_PRIVACY", "public") or "public"

    @property
    def start_privacy(self) -> str:
        """Start unlisted and go public only once the stream has looked right for a few minutes."""
        if env_float("LIVE_PUBLIC_AFTER_MIN", 3) <= 0:
            return self.final_privacy
        return env("LIVE_START_PRIVACY", "unlisted") or "unlisted"

    def check_go_public(self, result: dict, picture_ok: bool, now: float | None = None) -> bool:
        """Called every watchdog check; switches to the final privacy after LIVE_PUBLIC_AFTER_MIN healthy minutes."""
        import youtube_live as yl
        if self.session.get("public").get("done") or self.start_privacy == self.final_privacy:
            return False
        now = time.monotonic() if now is None else now
        status, health = yl.stream_health(self.yt, result["stream"]["id"])
        healthy = picture_ok and status == "active" and health not in (None, "noData")
        if not healthy:
            if getattr(self, "healthy_since", None) is not None:
                log.warning("[youtube] stream not healthy (picture ok: %s, YouTube: %s/%s) - staying %s",
                            picture_ok, status, health, self.start_privacy)
            self.healthy_since = None
            return False
        if getattr(self, "healthy_since", None) is None:
            self.healthy_since = now
            log.info("[youtube] stream looks healthy - going %s in %.0f min if it stays that way",
                     self.final_privacy, env_float("LIVE_PUBLIC_AFTER_MIN", 3))
        if now - self.healthy_since < env_float("LIVE_PUBLIC_AFTER_MIN", 3) * 60:
            return False
        yl.set_privacy(self.yt, result["broadcast_id"], self.final_privacy)
        self.session.set("public", {"done": True, "privacy": self.final_privacy})
        log.info("=== now %s: %s", self.final_privacy.upper(), result["url"])
        return True

    def go_live(self, result: dict) -> str:
        import youtube_live as yl
        return yl.go_live(self.yt, result["broadcast_id"], result["stream"]["id"])

    def end(self, result: dict) -> None:
        import youtube_live as yl
        yl.end(self.yt, result["broadcast_id"])


class OBSAgent:
    name = "obs"

    def __init__(self):
        self.obs = None
        self.scene = ""
        self.black = 0

    def picture_black(self) -> bool:
        try:
            return bool(self.obs and self.scene and self.obs.picture_is_black(self.scene))
        except Exception as e:
            log.debug("black-frame check failed: %s", e)
            return False

    def run(self, stream: dict | None, start_streaming: bool) -> dict:
        from obs_control import OBS

        self.obs = OBS.connect(start=True)
        scene = env("OBS_SCENE")
        if scene:
            self.obs.set_scene(scene)
        self.scene = scene or self.obs.current_scene()
        if env_bool("OBS_AUTO_CAPTURE", True) and self.scene:
            from scanner_site import browser_exe, os_window_title
            title = os_window_title()
            source = self.obs.ensure_window_capture(self.scene, title, browser_exe())
            log.info("[obs] %r captures the window %r", source, title)
        if stream:
            self.obs.set_stream(stream["server"], stream["key"])
        if start_streaming:
            self.obs.start()
        return {"version": self.obs.version(), "scene": scene, "streaming": self.obs.streaming()}

    def healthy(self) -> bool:
        try:
            return self.obs is not None and self.obs.streaming()
        except Exception:
            return False

    def recover(self, sleep=time.sleep) -> dict:
        """Restart streaming; if OBS is frozen (running but not answering), force-close and reopen it."""
        import obs_control
        try:
            return self.run(None, start_streaming=True)
        except obs_control.OBSError as e:
            if not obs_control.obs_running():
                raise
            log.warning("[watchdog] OBS is frozen (%s) - force-closing and reopening it", e)
            obs_control.kill()
            sleep(5)
            # OBS keeps its stream key and scene in its own settings, so a fresh start streams the same way.
            return self.run(None, start_streaming=True)


# --------------------------------------------------------------------------- orchestrator

class LiveShow:
    def __init__(self, settings: Settings, start: datetime | None = None):
        self.settings = settings
        self.start = start or datetime.now(tz())
        self.session = Session(live_root(settings) / self.start.strftime("%Y-%m-%d"))
        self.use_api = env_bool("YOUTUBE_LIVE_API", True)
        self.youtube, self.yt_result = None, {}

    def run(self) -> int:
        s, session = self.settings, self.session
        session.stop_file.unlink(missing_ok=True)
        end = end_time(self.start)
        log.info("=== live show %s -> %s%s", self.start.strftime("%Y-%m-%d %H:%M"), end.strftime("%H:%M"),
                 " | DRY RUN" if s.dry_run else "")

        import power
        power.stay_awake(screen_on=True)  # a sleeping PC or a blanked/locked screen breaks the stream
        gateway, browser, obs = GatewayAgent(s), BrowserAgent(s), OBSAgent()
        youtube = YouTubeAgent(s, session, self.start) if self.use_api and not s.dry_run else None
        yt_result: dict = {}
        try:
            session.set("gateway", gateway.run())
            session.set("browser", browser.run())
            if youtube:
                yt_result = youtube.run()
            session.set("obs", obs.run(yt_result.get("stream"), start_streaming=False))
            if not s.dry_run:
                wait = (self.start - datetime.now(tz())).total_seconds()
                if wait > 0:
                    log.info("ready - going live at %s", self.start.strftime("%H:%M"))
                    browser.wait(wait)
                obs.obs.start()
            if youtube:
                session.set("live", {"state": youtube.go_live(yt_result), "url": yt_result["url"]})
                log.info("=== LIVE: %s", yt_result["url"])
            elif not s.dry_run:
                log.info("=== LIVE (stream key set in OBS)")
            if not s.dry_run:
                self.start_tiktok()
            self.youtube, self.yt_result = youtube, yt_result
            self.watch(end, gateway, browser, obs, streaming=not s.dry_run)
            return 0
        except KeyboardInterrupt:
            log.info("interrupted - ending the stream")
            raise
        except Exception as e:
            log.error("live show failed: %s", e)
            log.debug("details", exc_info=True)
            session.set("error", {"error": str(e)})
            return 1
        finally:
            self.shutdown(youtube, yt_result, obs, browser)
            power.allow_screen_off()

    def watch(self, end: datetime, gateway, browser, obs, streaming: bool) -> None:
        every = env_float("LIVE_CHECK_SECONDS", 30)
        if self.settings.dry_run:
            log.info("dry run: everything is up; leaving it for %.0fs so you can look", every)
            browser.wait(every)
            return
        while datetime.now(tz()) < end:
            if self.session.stop_file.exists():
                log.info("stop requested")
                return
            browser.wait(every)
            try:
                if not gateway.healthy():
                    log.warning("[watchdog] IB Gateway is down - restarting")
                    gateway.run()
                    browser.run()  # the scanner has to reconnect to the new Gateway
                elif not browser.healthy():
                    log.warning("[watchdog] scanner window closed - reopening")
                    browser.run()
                if streaming and not obs.healthy():
                    log.warning("[watchdog] OBS stopped streaming - restarting")
                    obs.recover()
                if streaming:
                    browser.restore()
                    self.check_picture(browser, obs)
                    if self.youtube is not None:
                        self.youtube.check_go_public(self.yt_result, picture_ok=obs.healthy() and obs.black == 0)
            except Exception as e:  # keep trying until the end time
                log.error("[watchdog] recovery failed: %s", e)

    @staticmethod
    def check_picture(browser, obs) -> None:
        """A black stream means OBS lost the window: re-point the capture, then reload the scanner."""
        if not obs.picture_black():
            obs.black = 0
            return
        obs.black += 1
        log.warning("[watchdog] the stream picture is black (%d check(s) in a row)", obs.black)
        if obs.black == 2:
            from scanner_site import browser_exe, os_window_title
            obs.obs.ensure_window_capture(obs.scene, os_window_title(), browser_exe())
            browser.restore()
        elif obs.black >= 4:
            log.warning("[watchdog] still black - reopening the scanner")
            browser.close()
            browser.run()
            obs.black = 0

    @staticmethod
    def start_tiktok() -> None:
        import tiktok_studio
        if not tiktok_studio.enabled():
            return
        try:
            log.info("[tiktok] %s", tiktok_studio.open_studio())
            tiktok_studio.remind()
        except Exception as e:
            log.warning("[tiktok] couldn't open TikTok LIVE Studio: %s", e)

    def shutdown(self, youtube, yt_result, obs, browser) -> None:
        import tiktok_studio
        if tiktok_studio.enabled() and env_bool("TIKTOK_STUDIO_CLOSE_AT_END", True) and not self.settings.dry_run:
            try:
                log.info("[tiktok] %s", tiktok_studio.close_studio())
            except Exception as e:
                log.warning("[tiktok] close failed: %s", e)
        if obs.obs is not None and not self.settings.dry_run:
            try:
                obs.obs.stop()
                log.info("[obs] stream stopped")
            except Exception as e:
                log.warning("[obs] stop failed: %s", e)
        if youtube and yt_result.get("broadcast_id"):
            try:
                youtube.end(yt_result)
                log.info("[youtube] broadcast ended")
            except Exception as e:
                log.warning("[youtube] end failed: %s", e)
        if env_bool("LIVE_CLOSE_BROWSER", True):
            browser.close()
        self.session.set("finished", {"ok": "error" not in self.session.state})


# --------------------------------------------------------------------------- commands

def single_instance():
    """Hold a localhost port for as long as the scheduler runs; a second scheduler can't bind it."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", int(env_float("LIVE_LOCK_PORT", 47621))))
    except OSError:
        sock.close()
        raise ConfigError("the live-stream scheduler is already running (GUI or autostart)")
    return sock


def scheduler_running() -> bool:
    """Is a scheduler (from the app, autostart or a terminal) already holding the lock?"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", int(env_float("LIVE_LOCK_PORT", 47621))))
        return False
    except OSError:
        return True
    finally:
        sock.close()


def missed_show(settings: Settings, now: datetime) -> datetime | None:
    """Today's start time if it has passed, its end time hasn't, and today's show hasn't run yet.

    Lets a PC that was off (or a scheduler started late) still go live today instead of waiting
    for tomorrow. LIVE_CATCH_UP=false turns this off.
    """
    if not env_bool("LIVE_CATCH_UP", True):
        return None
    h, m = parse_hhmm(env("LIVE_START", "06:00") or "06:00")
    start = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if start.weekday() not in live_days() or not (start <= now):
        return None
    end = env("LIVE_END")
    if end:  # catch up only inside today's window (end_time() would give a late run a full duration)
        eh, em = parse_hhmm(end)
        window_end = start.replace(hour=eh, minute=em)
        if window_end <= start:
            window_end += timedelta(days=1)
    else:
        window_end = start + timedelta(minutes=env_float("LIVE_DURATION_MIN", 240))
    if now >= window_end - timedelta(minutes=env_float("LIVE_CATCH_UP_MIN_LEFT", 10)):
        return None
    state = Session(live_root(settings) / start.strftime("%Y-%m-%d")).state
    if "stop" in state or state.get("finished", {}).get("ok"):
        return None  # already streamed today, or you stopped it
    return start


def scheduler_stop_file(settings: Settings) -> Path:
    return live_root(settings) / "STOP_SCHEDULER"


def request_scheduler_stop(settings: Settings) -> None:
    """Ask a scheduler running elsewhere (autostart, another window) to end today's show and exit."""
    live_root(settings).mkdir(parents=True, exist_ok=True)
    scheduler_stop_file(settings).touch()
    stop(settings)


def daemon(settings: Settings) -> int:
    lock = single_instance()  # noqa: F841  (released when the process exits)
    import power
    if power.stay_awake():
        log.info("keeping this PC awake while the scheduler runs (idle sleep is paused)")
    stop_file = scheduler_stop_file(settings)
    stop_file.unlink(missing_ok=True)
    log.info("daily live stream: %s at %s (%s)", env("LIVE_DAYS", "mon-fri"), env("LIVE_START", "06:00"),
             env("LIVE_TZ") or "this computer's time zone")
    def plan() -> tuple[datetime, timedelta]:
        reload_env()  # the schedule may have been changed in the app since the scheduler started
        lead = timedelta(minutes=env_float("LIVE_PREP_MIN", 10))
        late = missed_show(settings, datetime.now(tz()))
        if late is not None:
            log.info("today's stream (%s) hasn't run yet and it's still before the end time - starting it now",
                     late.strftime("%H:%M"))
            return late, lead
        return next_start(datetime.now(tz())), lead

    while True:
        start, lead = plan()
        log.info("next stream %s (setup starts %s)", start.strftime("%a %Y-%m-%d %H:%M"),
                 (start - lead).strftime("%H:%M"))
        while datetime.now(tz()) < start - lead:
            power.stay_awake()  # renewed after every wake from sleep
            if stop_file.exists():
                stop_file.unlink(missing_ok=True)
                log.info("scheduler stopped")
                return 0
            time.sleep(min(30, max(1, (start - lead - datetime.now(tz())).total_seconds())))
            try:
                new_start, new_lead = plan()
            except ConfigError as e:
                log.warning("ignoring the new schedule: %s", e)
                continue
            if (new_start, new_lead) != (start, lead):
                start, lead = new_start, new_lead
                log.info("schedule changed - next stream %s (setup starts %s)",
                         start.strftime("%a %Y-%m-%d %H:%M"), (start - lead).strftime("%H:%M"))
        retry = env_float("LIVE_RETRY_SECONDS", 120)
        # A failed start (Gateway login, OBS, YouTube...) is retried until today's end time.
        while LiveShow(settings, start=start).run() != 0 and datetime.now(tz()) + timedelta(seconds=retry) < end_time(start):
            if stop_file.exists():
                break
            log.warning("retrying in %.0fs", retry)
            time.sleep(retry)
        if stop_file.exists():
            stop_file.unlink(missing_ok=True)
            log.info("scheduler stopped")
            return 0


def stop(settings: Settings) -> int:
    session = Session(live_root(settings) / datetime.now(tz()).strftime("%Y-%m-%d"))
    session.stop_file.touch()
    session.set("stop", {"by": "you"})  # so a scheduler starting later today doesn't restart it
    log.info("asked today's stream to stop (%s)", session.stop_file)
    return 0


def check(settings: Settings) -> int:
    bad = 0

    def step(name, fn):
        nonlocal bad
        try:
            log.info("[%s] OK: %s", name, fn())
        except Exception as e:
            bad += 1
            log.error("[%s] NOT READY: %s", name, e)

    step("gateway", lambda: GatewayAgent(settings).run())
    step("obs", lambda: __import__("obs_control").OBS.connect(start=True).version())
    if env_bool("YOUTUBE_LIVE_API", True):
        step("youtube", lambda: __import__("youtube_live").check())

    def site():
        agent = BrowserAgent(settings)
        try:
            return agent.run()
        finally:
            agent.close()
    step("scanner site", site)
    return 1 if bad else 0


def _graceful_signals() -> None:
    """SIGTERM / Ctrl+Break (sent by the GUI's Stop button) end the stream cleanly like Ctrl+C."""
    import signal

    def interrupt(*_):
        raise KeyboardInterrupt
    for name in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), interrupt)


def main(argv: list[str] | None = None) -> int:
    from watcher import setup_logging

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["daemon", "run", "stop", "check", "site-login", "site-test"])
    ap.add_argument("--dry-run", action="store_true", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    try:
        settings = Settings.load(dry_run=args.dry_run)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    setup_logging(settings, args.verbose)
    _graceful_signals()
    for noisy in ("ib_async", "websocket"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)  # it logs a traceback on every retry
    try:
        if args.command == "daemon":
            return daemon(settings)
        if args.command == "run":
            return LiveShow(settings).run()
        if args.command == "stop":
            return stop(settings)
        if args.command == "site-test":
            agent = BrowserAgent(settings)
            try:
                log.info("[scanner site] OK: %s", agent.run())
                log.info("leaving the window open for 60s so you can check it")
                agent.wait(60)
            except Exception as e:
                log.error("[scanner site] FAILED: %s", e)
                agent.wait(30)  # leave it on screen to see where it stopped
                return 1
            finally:
                agent.close()
            return 0
        if args.command == "site-login":
            from scanner_site import site_login
            site_login(live_root(settings) / "browser-profile")
            return 0
        return check(settings)
    except (ConfigError, KeyboardInterrupt) as e:
        if isinstance(e, ConfigError):
            print(f"config error: {e}", file=sys.stderr)
            return 2
        return 0


if __name__ == "__main__":
    sys.exit(main())
