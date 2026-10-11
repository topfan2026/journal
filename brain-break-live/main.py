"""Brain Break Live: a 24/7 study / ambient / music stream overlay with a live-chat trivia show.

    python main.py --demo                 preview with fake viewers (no YouTube needed)
    python main.py                        run with your YouTube live chat
    python main.py --profile sleep        start on a given niche (switch any time on /control)
    python main.py --demo --trivia-now    start a trivia show right away
    python main.py profiles               list the niches in profiles/
    python main.py check                  validate profiles + question packs, test YouTube access
    python main.py auth                   connect YouTube (only if trading-shorts-bot's token isn't reused)

Open http://127.0.0.1:8790/control in your browser and add http://127.0.0.1:8790/ to OBS as a
Browser Source (1920x1080, "Control audio via OBS" ticked).
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from config import ConfigError, Settings, env, load_profiles, save_env

log = logging.getLogger("brainbreak")


def build(args) -> "tuple":
    from app import App
    from chat import DemoChat, YouTubeChat
    from trivia import QuestionBank

    settings = Settings.load(port=args.port, data_root=args.data_dir)
    settings.ensure_dirs()
    profiles = load_profiles(settings)
    bank = QuestionBank(settings.questions_dir)
    chat = DemoChat(settings, rate=args.demo_rate) if args.demo else YouTubeChat(settings)
    app = App(settings, profiles, chat, bank, active=args.profile)
    return settings, app, chat


def run(args) -> int:
    from server import serve

    settings, app, chat = build(args)
    if args.trivia_now:
        app.control("trivia_start", minutes=args.trivia_now)
    httpd = serve(app, args.host, settings.port)
    chat.start()
    base = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{settings.port}"
    log.info("on air: %s (%s)%s", app.profile.name, app.active, " | DEMO chat" if args.demo else "")
    log.info("time zone: %s (set TIMEZONE in .env if this is wrong)", settings.tz)
    log.info("overlay for OBS:  %s/", base)
    log.info("control page:     %s/control", base)
    try:
        while True:
            app.tick()
            time.sleep(0.25)
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        chat.stop()
        app.save()
        httpd.shutdown()
    return 0


def check(args) -> int:
    from trivia import QuestionBank

    ok = True
    settings = Settings.load()
    try:
        profiles = load_profiles(settings)
        for p in profiles.values():
            tracks = p.music_path(settings)
            n = len([f for f in tracks.iterdir() if f.is_file()]) if tracks.is_dir() else 0
            print(f"profile  {p.id:<14} {p.name}  ({p.scene}, {n} music files in {tracks})")
    except ConfigError as e:
        ok = False
        print(f"profile  ERROR {e}")
    try:
        bank = QuestionBank(settings.questions_dir)
        for pack in bank.packs.values():
            print(f"pack     {pack.id:<14} {len(pack.questions)} questions  ({pack.title})")
    except Exception as e:
        ok = False
        print(f"pack     ERROR {e}")
    try:
        from chat import youtube_service
        yt = youtube_service()
        resp = yt.liveBroadcasts().list(part="snippet", broadcastStatus="active", broadcastType="all").execute()
        live = [i["snippet"]["title"] for i in resp.get("items", [])]
        print(f"youtube  OK - live now: {', '.join(live) if live else 'nothing (fine when you are offline)'}")
    except Exception as e:
        ok = False
        print(f"youtube  not ready: {e}\n         (use --demo to preview, or run: python main.py auth)")
    return 0 if ok else 1


def auth(args) -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from chat import SCOPES, TOKEN_URI

    client_id, secret = env("YOUTUBE_CLIENT_ID"), env("YOUTUBE_CLIENT_SECRET")
    if not (client_id and secret):
        print("Put YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET in .env first (the same Google Cloud "
              "OAuth client trading-shorts-bot uses works).")
        return 1
    flow = InstalledAppFlow.from_client_config({"installed": {
        "client_id": client_id, "client_secret": secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"]}}, scopes=SCOPES)
    creds = flow.run_local_server(port=args.auth_port, access_type="offline", prompt="consent",
                                  open_browser=not args.no_browser,
                                  success_message="YouTube connected - you can close this tab.")
    if not creds.refresh_token:
        print("Google returned no refresh token - remove the app at myaccount.google.com/permissions and try again.")
        return 1
    save_env("YOUTUBE_CHAT_REFRESH_TOKEN", creds.refresh_token)
    print("YouTube connected (saved YOUTUBE_CHAT_REFRESH_TOKEN in .env)")
    return 0


def list_profiles(args) -> int:
    settings = Settings.load()
    for p in load_profiles(settings).values():
        t = p.trivia
        show = "24/7 trivia" if t.always_on else (f"trivia {t.start.strftime('%H:%M')} {','.join(t.days)}" if t.enabled else "no trivia")
        print(f"{p.id:<14} {p.name:<34} scene={p.scene:<11} pomodoro={'on' if p.pomodoro else 'off':<4} {show}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="run", choices=["run", "check", "auth", "profiles"])
    ap.add_argument("--demo", action="store_true", help="fake viewers instead of YouTube chat")
    ap.add_argument("--demo-rate", type=float, default=1.0, help="demo chat speed multiplier")
    ap.add_argument("--profile", help="profile (niche) to start on, e.g. study, sleep, trading-music")
    ap.add_argument("--trivia-now", type=float, metavar="MIN", help="start a trivia show of MIN minutes right away")
    ap.add_argument("--host", default=env("OVERLAY_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, help="overlay port (default OVERLAY_PORT or 8790)")
    ap.add_argument("--data-dir", type=lambda p: __import__("pathlib").Path(p).expanduser(),
                    help="where stats and leaderboards are kept (use one per process if you run several)")
    ap.add_argument("--auth-port", type=int, default=8080)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("googleapiclient.discovery_cache", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    try:
        return {"run": run, "check": check, "auth": auth, "profiles": list_profiles}[args.command](args)
    except ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
