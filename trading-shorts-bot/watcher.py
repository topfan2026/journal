"""Watch ~/TradingShorts/Ready/ and hand every new job to the agent pipeline.

    python watcher.py            watch forever (watchdog events + polling fallback)
    python watcher.py once       process whatever is in Ready/ now, then exit
    python watcher.py check      verify credentials for every enabled platform
    python watcher.py retry [NAME ...] [--fresh]
                                 move Failed/ jobs back to Ready/ (all if no NAME);
                                 --fresh also redoes the edit/metadata/thumbnail steps
    options: --dry-run  (run everything except the real uploads), --root PATH
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from agents import Orchestrator, UploadAgent
from config import ConfigError, Settings
from job import STATE_FILE, StabilityTracker, claim, discover, move

log = logging.getLogger("watcher")


def setup_logging(settings: Settings, verbose: bool) -> None:
    settings.logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    file = RotatingFileHandler(settings.logs / "bot.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    file.setFormatter(fmt)
    root.handlers[:] = [console, file]
    for noisy in ("googleapiclient", "urllib3", "httpx", "httpx2", "anthropic", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def recover_interrupted(settings: Settings) -> None:
    """A crash mid-job leaves it in Processing/. Park it in Failed/ so a human can `retry` it."""
    for folder in sorted(p for p in settings.processing.iterdir() if p.is_dir()):
        log.warning("found interrupted job %s - moving to Failed/ (use `retry` to resume)", folder.name)
        move(folder, settings.failed)


def _start_observer(settings: Settings, wake: threading.Event):
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        log.warning("watchdog not installed - polling every %.0fs", settings.poll_seconds)
        return None

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event):
            wake.set()

    observer = Observer()
    observer.schedule(Handler(), str(settings.ready), recursive=True)
    observer.start()
    return observer


def run(settings: Settings, once: bool = False) -> int:
    settings.ensure_dirs()
    recover_interrupted(settings)
    orchestrator = Orchestrator(settings)
    tracker = StabilityTracker(settings.stable_seconds)
    wake = threading.Event()
    observer = None if once else _start_observer(settings, wake)
    log.info("watching %s | platforms: %s%s", settings.ready, ", ".join(settings.platforms),
             " | DRY RUN" if settings.dry_run else "")
    failures = 0
    idle_rounds = 0
    try:
        while True:
            try:
                candidates = discover(settings.ready)
            except OSError as e:
                log.error("cannot scan %s: %s", settings.ready, e)
                candidates = []
            tracker.prune({c.key for c in candidates})
            waiting = False
            for cand in candidates:
                if not tracker.is_stable(cand):
                    waiting = True
                    continue
                tracker.forget(cand.key)
                try:
                    folder = claim(cand, settings.processing)
                except OSError as e:
                    log.error("cannot claim %s: %s", cand.name, e)
                    continue
                if not orchestrator.process(folder):
                    failures += 1
            if once:
                if not candidates:
                    break
                idle_rounds = idle_rounds + 1 if waiting else 0
                if idle_rounds > settings.stable_seconds + 30:  # something is still being written
                    log.warning("giving up waiting for files still changing: %s",
                                ", ".join(c.name for c in candidates))
                    break
                time.sleep(1)
                continue
            # While a job is settling, re-check every second; otherwise sleep until an event or the poll interval.
            wake.wait(1.0 if waiting else settings.poll_seconds)
            wake.clear()
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        if observer:
            observer.stop()
            observer.join(timeout=5)
    return 1 if failures else 0


def check(settings: Settings) -> int:
    bad = 0
    for platform in settings.platforms:
        try:
            log.info("[%s] OK: %s", platform, UploadAgent(platform, settings).check())
        except (ConfigError, Exception) as e:
            bad += 1
            log.error("[%s] NOT READY: %s", platform, e)
    import os
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        log.warning("[claude] ANTHROPIC_API_KEY not set - metadata will use meta.json / template only")
    return 1 if bad else 0


def retry(settings: Settings, names: list[str], fresh: bool) -> int:
    settings.ensure_dirs()
    folders = [p for p in sorted(settings.failed.iterdir()) if p.is_dir() and (not names or p.name in names)]
    if not folders:
        log.info("nothing to retry in %s", settings.failed)
        return 0
    for folder in folders:
        (folder / "error.txt").unlink(missing_ok=True)
        state_path = folder / STATE_FILE
        if fresh and state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.pop("stages", None)  # platforms already posted stay recorded, so they are not re-posted
            state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        dest = move(folder, settings.ready)
        log.info("re-queued %s", dest.name)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="watch", choices=["watch", "once", "check", "retry"])
    ap.add_argument("names", nargs="*", help="job names for retry")
    ap.add_argument("--dry-run", action="store_true", default=None)
    ap.add_argument("--fresh", action="store_true", help="retry: redo edit/metadata/thumbnail")
    ap.add_argument("--root", help="override SHORTS_ROOT")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    from pathlib import Path
    try:
        settings = Settings.load(dry_run=args.dry_run, root=Path(args.root).expanduser() if args.root else None)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2
    setup_logging(settings, args.verbose)

    if args.command == "check":
        return check(settings)
    if args.command == "retry":
        return retry(settings, args.names, args.fresh)
    return run(settings, once=args.command == "once")


if __name__ == "__main__":
    sys.exit(main())
