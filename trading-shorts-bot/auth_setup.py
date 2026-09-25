"""One-time OAuth helpers. Each one writes the resulting tokens into .env.

    python auth_setup.py youtube     browser consent -> YOUTUBE_REFRESH_TOKEN
    python auth_setup.py tiktok      browser consent -> TIKTOK_TOKEN / TIKTOK_REFRESH_TOKEN
    python auth_setup.py instagram   short-lived user token -> non-expiring Page token + IG_USER_ID
"""
from __future__ import annotations

import argparse
import secrets
import sys
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from config import ENV_FILE, env, require_env, save_env


def youtube(args) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    from upload_youtube import SCOPES, TOKEN_URI

    client_id, secret = require_env("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
    flow = InstalledAppFlow.from_client_config({"installed": {
        "client_id": client_id, "client_secret": secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}, scopes=SCOPES)
    creds = flow.run_local_server(port=args.port, access_type="offline", prompt="consent",
                                  open_browser=not args.no_browser)
    if not creds.refresh_token:
        sys.exit("Google returned no refresh token - revoke the app at myaccount.google.com/permissions and retry.")
    save_env("YOUTUBE_REFRESH_TOKEN", creds.refresh_token)
    print(f"Saved YOUTUBE_REFRESH_TOKEN to {ENV_FILE}")


def tiktok(args) -> None:
    key, secret, redirect = require_env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REDIRECT_URI")
    scopes = env("TIKTOK_SCOPES", "user.info.basic,video.upload,video.publish")
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": key, "scope": scopes, "response_type": "code",
        "redirect_uri": redirect, "state": state})
    print("Open this URL, approve, then copy the FULL URL you are redirected to:\n\n" + url + "\n")
    if not args.no_browser:
        webbrowser.open(url)
    redirected = input("Redirected URL: ").strip()
    query = parse_qs(urlparse(redirected).query)
    if query.get("state", [""])[0] != state:
        sys.exit("state mismatch - start again")
    if "code" not in query:
        sys.exit(f"no code in URL: {query.get('error_description') or query}")
    resp = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": key, "client_secret": secret, "code": query["code"][0],
        "grant_type": "authorization_code", "redirect_uri": redirect,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = resp.json()
    if "access_token" not in data:
        sys.exit(f"token exchange failed: {data}")
    save_env("TIKTOK_TOKEN", data["access_token"])
    save_env("TIKTOK_TOKEN_EXPIRES_AT", str(int(time.time() + int(data.get("expires_in", 86400)))))
    save_env("TIKTOK_REFRESH_TOKEN", data["refresh_token"])
    print(f"Saved TikTok tokens (scopes: {data.get('scope')}) to {ENV_FILE}")


def instagram(args) -> None:
    from upload_instagram import DEFAULT_API_VERSION

    app_id, app_secret = require_env("FB_APP_ID", "FB_APP_SECRET")
    base = f"https://graph.facebook.com/{env('IG_API_VERSION', DEFAULT_API_VERSION)}"
    short = args.token or input(
        "Paste a short-lived USER token from Graph API Explorer with permissions\n"
        "instagram_basic, instagram_content_publish, pages_show_list, pages_read_engagement, business_management:\n> "
    ).strip()
    r = requests.get(f"{base}/oauth/access_token", timeout=30, params={
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": short}).json()
    if "access_token" not in r:
        sys.exit(f"token exchange failed: {r}")
    long_user = r["access_token"]
    pages = requests.get(f"{base}/me/accounts", timeout=30, params={
        "fields": "name,access_token,instagram_business_account{id,username}",
        "access_token": long_user}).json().get("data", [])
    linked = [p for p in pages if p.get("instagram_business_account")]
    if not linked:
        sys.exit("No Facebook Page with a linked Instagram Business/Creator account was found for this user.")
    for i, p in enumerate(linked):
        print(f"[{i}] {p['name']} -> @{p['instagram_business_account'].get('username')}")
    idx = 0 if len(linked) == 1 else int(input("Choose account #: "))
    page = linked[idx]
    # A Page token derived from a long-lived user token does not expire.
    save_env("IG_TOKEN", page["access_token"])
    save_env("IG_USER_ID", page["instagram_business_account"]["id"])
    print(f"Saved IG_TOKEN + IG_USER_ID for @{page['instagram_business_account'].get('username')} to {ENV_FILE}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("platform", choices=["youtube", "tiktok", "instagram"])
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    ap.add_argument("--port", type=int, default=8080, help="youtube: local redirect port")
    ap.add_argument("--token", help="instagram: short-lived user token")
    args = ap.parse_args()
    {"youtube": youtube, "tiktok": tiktok, "instagram": instagram}[args.platform](args)


if __name__ == "__main__":
    main()
