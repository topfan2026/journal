"""Guided setup: opens each site, tells you what to click, saves what you paste into .env.

    python setup_wizard.py              all steps
    python setup_wizard.py youtube      just one (claude | youtube | instagram | tiktok)

Press Enter to skip any step; run it again later to finish it.
"""
from __future__ import annotations

import subprocess
import sys
import webbrowser

from config import ENV_FILE, env, save_env

BOT = [sys.executable]


def say(text: str) -> None:
    print(text.strip("\n"))


def ask(key: str, label: str, secret: bool = False) -> bool:
    current = env(key)
    hint = f" [already set: {'•' * 6 if secret else current}]" if current else ""
    value = input(f"  Paste {label}{hint}: ").strip()
    if value:
        save_env(key, value)
    return bool(value or current)


def open_page(url: str) -> None:
    print(f"  → opening {url}")
    webbrowser.open(url)


def pause(msg: str = "Press Enter when done (or type s to skip this platform)") -> bool:
    return input(f"  {msg}: ").strip().lower() != "s"


def run(*args: str) -> bool:
    return subprocess.call([*BOT, *args]) == 0


def step_claude() -> None:
    say("""
== Claude (writes your titles, descriptions, tags) ==
  1. Sign in, then create an API key and copy it.""")
    open_page("https://platform.claude.com/settings/keys")
    ask("ANTHROPIC_API_KEY", "API key (starts with sk-ant-)", secret=True)


def step_youtube() -> None:
    say("""
== YouTube ==
  1. Sign in with the Google account that owns your channel.
  2. Create a project (top-left project picker > New project), then click ENABLE.""")
    open_page("https://console.cloud.google.com/apis/library/youtube.googleapis.com")
    if not pause():
        return
    say("""
  3. Consent screen: User type External. Enter an app name + your email, and save.
     Under Audience: add your own email as a test user, then click PUBLISH APP.
     (Without PUBLISH APP your login expires every 7 days.)""")
    open_page("https://console.cloud.google.com/auth/overview")
    if not pause():
        return
    say("""
  4. Create client > Application type: Desktop app > Create.
     Copy the Client ID and Client secret it shows.""")
    open_page("https://console.cloud.google.com/auth/clients")
    ok = ask("YOUTUBE_CLIENT_ID", "Client ID") & ask("YOUTUBE_CLIENT_SECRET", "Client secret", secret=True)
    if ok:
        say("\n  5. A browser will open: pick your channel's account and click Allow.\n"
            "     (If it warns 'Google hasn't verified this app': Advanced > Go to app.)")
        run("auth_setup.py", "youtube")


def step_instagram() -> None:
    say("""
== Instagram ==
  Before starting, check in the Instagram app: Settings > Account type must be
  Business or Creator, linked to a Facebook Page (Accounts Center > connect Page).

  1. Create app > use case 'Other' > type Business. Then in the app dashboard
     add the product 'Instagram' (API setup with Facebook login).
  2. App settings > Basic: copy the App ID and App secret.""")
    open_page("https://developers.facebook.com/apps/")
    ok = ask("FB_APP_ID", "App ID") & ask("FB_APP_SECRET", "App secret", secret=True)
    if not ok:
        return
    say("""
  3. Graph API Explorer: choose your app (right side), then under Permissions add:
       instagram_basic, instagram_content_publish, pages_show_list,
       pages_read_engagement, business_management
     Click 'Generate Access Token', approve, and copy the token.""")
    open_page("https://developers.facebook.com/tools/explorer/")
    token = input("  Paste the token: ").strip()
    if token:
        run("auth_setup.py", "instagram", "--token", token)


def step_tiktok() -> None:
    say("""
== TikTok ==
  1. Log in > Manage apps > Connect an app. Fill in the app details.
  2. Add products: Login Kit and Content Posting API.
  3. In Login Kit, add Redirect URI:  https://example.com/tiktok-callback
  4. Scopes: user.info.basic, video.upload, video.publish. Submit for review.
  5. Copy the Client key and Client secret (top of the app page).""")
    open_page("https://developers.tiktok.com/apps/")
    ok = ask("TIKTOK_CLIENT_KEY", "Client key") & ask("TIKTOK_CLIENT_SECRET", "Client secret", secret=True)
    if not env("TIKTOK_REDIRECT_URI"):
        save_env("TIKTOK_REDIRECT_URI", "https://example.com/tiktok-callback")
    if not ok:
        return
    if input("  Is the app approved already? (y/N): ").strip().lower() == "y":
        say("  A link will open: click Authorize. The page you land on may show an error;\n"
            "  that's fine. Copy the whole address-bar URL and paste it back here.")
        run("auth_setup.py", "tiktok")
    else:
        say("  OK. When TikTok approves the app (1-2 days), run:  python setup_wizard.py tiktok")


STEPS = {"claude": step_claude, "youtube": step_youtube, "instagram": step_instagram, "tiktok": step_tiktok}


def main() -> None:
    if not ENV_FILE.exists():
        example = ENV_FILE.with_name(".env.example")
        ENV_FILE.write_text(example.read_text() if example.exists() else "")
    chosen = sys.argv[1:] or list(STEPS)
    for name in chosen:
        if name not in STEPS:
            sys.exit(f"unknown step {name}; choose from {', '.join(STEPS)}")
        STEPS[name]()
    say("\n== Checking everything ==")
    run("watcher.py", "check")
    say(f"\nSaved to {ENV_FILE}. Next:  python watcher.py once --dry-run   then   python watcher.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nstopped - run it again any time to continue")
