"""Go live on YouTube with just your PC screen - no website, no IB Gateway, no scanner.

    python live.py screen          (the app's "Go live now (my screen)" button)

OBS gets its own scene (SCREEN_SCENE) with a Display Capture of one monitor (SCREEN_MONITOR, 1 = Windows display 1,
the 1920x1080 one), the YouTube broadcast is created and started like the daily show, and whatever you open on
that monitor is what viewers see. End it with "End screen stream" (or `live.py stop`) or in YouTube Studio.
Your normal scene in OBS is switched back at the end, so the daily website stream is untouched.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import live
import live_status
from config import ConfigError, Settings, env, env_bool, env_float

log = logging.getLogger(__name__)


class ScreenYouTube(live.YouTubeAgent):
    """The same YouTube broadcast steps as the daily show, with the screen stream's own title and privacy."""
    title_key, title_default = "SCREEN_TITLE", "LIVE | My screen | {weekday} {date}"
    description_key, description_default = "SCREEN_DESCRIPTION", ""
    tags_key, thumbnail_key, privacy_key = "SCREEN_TAGS", "SCREEN_THUMBNAIL", "SCREEN_PRIVACY"

    @property
    def final_privacy(self) -> str:
        return env(self.privacy_key, "unlisted") or "unlisted"

    @property
    def start_privacy(self) -> str:
        return self.final_privacy  # no "unlisted first, public later" dance: you choose once


def busy_with_other_show(state: dict) -> bool:
    """Is the daily (website) show on the air right now? Both would fight over OBS."""
    return (state.get("kind") != "screen" and state.get("phase") in ("setup", "ready", "live", "ending", "retrying")
            and live.age_minutes(state) < 3)


class ScreenShow:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.start = datetime.now(live.tz())
        self.armed = self.start
        self.root = live.live_root(settings)
        # Its own folder, so today's website broadcast is never mistaken for (and reused as) this one.
        self.session = live.Session(self.root / (self.start.strftime("%Y-%m-%d") + "-screen"))
        self.obs = None
        self.saved_scene = ""
        self.youtube: ScreenYouTube | None = None
        self.result: dict = {}

    def status(self, **fields) -> None:
        live_status.write(self.root, kind="screen", **fields)

    def stop_requested(self) -> bool:
        if self.session.stop_file.exists():
            return True
        return live.stopped_since(live.Session(self.session.folder).state, self.armed)

    def end_time(self) -> datetime | None:
        minutes = env_float("SCREEN_DURATION_MIN", 0)
        return self.start + timedelta(minutes=minutes) if minutes > 0 else None

    def run(self) -> int:
        s = self.settings
        state = live_status.read(self.root)
        if busy_with_other_show(state):
            msg = "The daily stream is on the air - end it first (End today's stream), then start the screen stream."
            log.error(msg)
            print(msg)
            return 1
        self.session.stop_file.unlink(missing_ok=True)
        end = self.end_time()
        monitor = int(env_float("SCREEN_MONITOR", 1))
        self.status(phase="test" if s.dry_run else "setup", message="Getting your screen stream ready",
                    show_start=self.start.isoformat(), show_end=end.isoformat() if end else None, live_since=None,
                    url="", viewers=None, fixes=0, last_check=None, error="", steps=live_status.reset_steps(self.root))
        live_status.step(self.root, "gateway", "off", "not needed for a screen stream")
        live_status.step(self.root, "scanner", "off", f"streaming your screen (monitor {monitor})")
        log.info("=== screen stream on monitor %d%s", monitor, " | DRY RUN" if s.dry_run else "")
        import power
        power.stay_awake(screen_on=True)  # a sleeping PC or blanked screen would break the stream
        failed = False
        try:
            use_api = env_bool("YOUTUBE_LIVE_API", True) and not s.dry_run
            if use_api:
                self.youtube = ScreenYouTube(s, self.session, self.start)
                self.result = self.step("youtube", self.youtube.run)
                self.status(url=self.result.get("url", ""), privacy=self.youtube.final_privacy)
            else:
                live_status.step(self.root, "youtube", "off", "dry run" if s.dry_run else "stream key set in OBS")
            self.step("obs", self.setup_obs, monitor)
            if s.dry_run:
                log.info("dry run: OBS shows monitor %d; nothing was streamed", monitor)
                return 0
            live_status.step(self.root, "live", "working", "starting the stream")
            self.obs.start()
            if self.youtube:
                self.session.set("live", {"state": self.youtube.go_live(self.result), "url": self.result["url"]})
                log.info("=== LIVE: %s", self.result["url"])
            else:
                self.session.set("live", {"state": "live", "url": ""})
                log.info("=== LIVE (stream key set in OBS)")
            live_status.step(self.root, "live", "ok", "on air")
            self.status(phase="live", message="Live - your screen", live_since=datetime.now(timezone.utc).isoformat())
            self.watch(end)
            return 0
        except live.StopRequested:
            log.info("stop requested - ending the screen stream")
            return 0
        except KeyboardInterrupt:
            log.info("interrupted - ending the screen stream")
            raise
        except Exception as e:
            failed = True
            log.error("screen stream failed: %s", e)
            log.debug("details", exc_info=True)
            self.session.set("error", {"error": str(e)})
            self.status(error=str(e)[:300])
            return 1
        finally:
            self.status(phase="ending", message="Ending the stream")
            self.shutdown()
            power.allow_screen_off()
            if failed:
                self.status(phase="failed", message="The screen stream failed - see the log")
            else:
                self.status(phase="tested" if s.dry_run else "ended", message="Test finished" if s.dry_run else "Stream ended")

    def step(self, name: str, fn, *args):
        live_status.step(self.root, name, "working")
        try:
            result = fn(*args)
        except Exception as e:
            live_status.step(self.root, name, "failed", str(e)[:200])
            raise
        live_status.step(self.root, name, "ok", live._summary(result))
        if self.stop_requested():
            raise live.StopRequested()
        return result

    def setup_obs(self, monitor: int) -> dict:
        from obs_control import OBS
        self.obs = OBS.connect(start=True)
        self.saved_scene = self.obs.current_scene()
        scene = env("SCREEN_SCENE", "AiAlgobot Screen") or "AiAlgobot Screen"
        shown = self.obs.ensure_screen_capture(scene, monitor)
        self.obs.set_scene(scene)
        if self.result.get("stream"):
            self.obs.set_stream(self.result["stream"]["server"], self.result["stream"]["key"])
        return {"scene": scene, "shows": shown}

    def watch(self, end: datetime | None) -> None:
        every = env_float("LIVE_CHECK_SECONDS", 30)
        stats_every = env_float("LIVE_STATS_SECONDS", 120)
        last_stats = 0.0
        while end is None or datetime.now(live.tz()) < end:
            time.sleep(every)
            if self.stop_requested():
                log.info("stop requested")
                return
            try:
                if self.youtube is not None and time.monotonic() - last_stats >= stats_every:
                    last_stats = time.monotonic()
                    stats = self.youtube.stats(self.result)
                    self.status(viewers=stats.get("viewers"))
                    if stats.get("ended"):
                        log.info("the broadcast was ended on YouTube - ending the screen stream")
                        self.session.set("stop", {"by": "youtube"})
                        return
                if not self.obs.streaming():
                    log.warning("[watchdog] OBS stopped streaming - restarting")
                    self.obs.start()
            except Exception as e:  # keep trying until you end it
                log.error("[watchdog] recovery failed: %s", e)
                self.status(error=f"watchdog: {e}"[:300])
            self.status(last_check=datetime.now(timezone.utc).isoformat())
        log.info("the screen stream's time is up")

    def shutdown(self) -> None:
        if self.obs is not None and not self.settings.dry_run:
            try:
                self.obs.stop()
                log.info("[obs] stream stopped")
            except Exception as e:
                log.warning("[obs] stop failed: %s", e)
        if self.obs is not None and self.saved_scene:
            try:
                self.obs.set_scene(self.saved_scene)
                log.info("[obs] back on scene %r", self.saved_scene)
            except Exception as e:
                log.debug("[obs] couldn't switch the scene back: %s", e)
        if self.youtube and self.result.get("broadcast_id"):
            try:
                self.youtube.end(self.result)
                log.info("[youtube] broadcast ended")
            except Exception as e:
                log.warning("[youtube] end failed: %s", e)
        self.session.set("finished", {"ok": "error" not in self.session.state})


__all__ = ["ScreenShow", "ScreenYouTube", "busy_with_other_show", "ConfigError"]
