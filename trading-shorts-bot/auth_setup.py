"""Connect accounts (one time). Each function saves the resulting tokens into .env.

Used by the desktop app's Accounts screen, and still runnable from a terminal:
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

TIKTOK_REDIRECT_DEFAULT = "https://example.com/tiktok-callback"


class AuthError(Exception):
    pass


# --------------------------------------------------------------------------- YouTube

def youtube_connect(open_browser: bool = True, port: int = 0) -> str:
    """Blocking: opens Google consent in the browser, waits for the redirect, saves the refresh token."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    from upload_youtube import SCOPES, TOKEN_URI

    client_id, secret = require_env("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
    if not client_id.endswith(".apps.googleusercontent.com"):
        raise AuthError("YouTube Client ID looks wrong - it should end with .apps.googleusercontent.com")
    flow = InstalledAppFlow.from_client_config({"installed": {
        "client_id": client_id, "client_secret": secret,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": TOKEN_URI,
        "redirect_uris": ["http://localhost"],
    }}, scopes=SCOPES)
    creds = flow.run_local_server(
        port=port, access_type="offline", prompt="consent", open_browser=open_browser,
        success_message="YouTube connected - you can close this tab and go back to Shorts Bot.")
    if not creds.refresh_token:
        raise AuthError("Google returned no refresh token - remove the app at "
                        "myaccount.google.com/permissions and connect again.")
    save_env("YOUTUBE_REFRESH_TOKEN", creds.refresh_token)
    return "YouTube connected"


# --------------------------------------------------------------------------- TikTok

def tiktok_auth_url() -> tuple[str, str]:
    """Return (url to open, state). The user approves, then pastes the URL they land on into tiktok_finish()."""
    key, _ = require_env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    redirect = env("TIKTOK_REDIRECT_URI") or TIKTOK_REDIRECT_DEFAULT
    scopes = env("TIKTOK_SCOPES", "user.info.basic,video.upload,video.publish")
    state = secrets.token_urlsafe(16)
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": key, "scope": scopes, "response_type": "code",
        "redirect_uri": redirect, "state": state})
    return url, state


def tiktok_finish(redirected_url: str, state: str) -> str:
    key, secret = require_env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    redirect = env("TIKTOK_REDIRECT_URI") or TIKTOK_REDIRECT_DEFAULT
    query = parse_qs(urlparse(redirected_url.strip()).query)
    if query.get("state", [""])[0] != state:
        raise AuthError("That link doesn't match this attempt - click Connect again and paste the new link.")
    if "code" not in query:
        raise AuthError(f"TikTok did not approve: {query.get('error_description') or query or 'no code in link'}")
    resp = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30, data={
        "client_key": key, "client_secret": secret, "code": query["code"][0],
        "grant_type": "authorization_code", "redirect_uri": redirect,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = resp.json()
    if "access_token" not in data:
        raise AuthError(f"TikTok token exchange failed: {data}")
    save_env("TIKTOK_TOKEN", data["access_token"])
    save_env("TIKTOK_TOKEN_EXPIRES_AT", str(int(time.time() + int(data.get("expires_in", 86400)))))
    save_env("TIKTOK_REFRESH_TOKEN", data["refresh_token"])
    return f"TikTok connected (scopes: {data.get('scope')})"


# --------------------------------------------------------------------------- Instagram

def instagram_accounts(short_token: str) -> list[dict]:
    """Exchange a Graph API Explorer user token; return the Pages that have a linked IG account."""
    from upload_instagram import DEFAULT_API_VERSION

    app_id, app_secret = require_env("FB_APP_ID", "FB_APP_SECRET")
    base = f"https://graph.facebook.com/{env('IG_API_VERSION', DEFAULT_API_VERSION)}"
    r = requests.get(f"{base}/oauth/access_token", timeout=30, params={
        "grant_type": "fb_exchange_token", "client_id": app_id,
        "client_secret": app_secret, "fb_exchange_token": short_token.strip()}).json()
    if "access_token" not in r:
        raise AuthError(f"Facebook rejected the token: {r.get('error', {}).get('message', r)}")
    pages = requests.get(f"{base}/me/accounts", timeout=30, params={
        "fields": "name,access_token,instagram_business_account{id,username}",
        "access_token": r["access_token"]}).json().get("data", [])
    linked = [p for p in pages if p.get("instagram_business_account")]
    if not linked:
        raise AuthError("No Facebook Page with a linked Instagram Business/Creator account was found. "
                        "In Instagram: Settings > Account type > switch to Business/Creator and connect a Page.")
    return linked


def instagram_save(page: dict) -> str:
    # A Page token derived from a long-lived user token does not expire.
    save_env("IG_TOKEN", page["access_token"])
    save_env("IG_USER_ID", page["instagram_business_account"]["id"])
    return f"Instagram connected: @{page['instagram_business_account'].get('username')}"


# --------------------------------------------------------------------------- CLI

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("platform", choices=["youtube", "tiktok", "instagram"])
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    ap.add_argument("--port", type=int, default=8080, help="youtube: local redirect port")
    ap.add_argument("--token", help="instagram: short-lived user token")
    args = ap.parse_args()
    try:
        if args.platform == "youtube":
            print(youtube_connect(open_browser=not args.no_browser, port=args.port))
        elif args.platform == "tiktok":
            url, state = tiktok_auth_url()
            print("Open this URL, approve, then copy the FULL URL you are redirected to:\n\n" + url + "\n")
            if not args.no_browser:
                webbrowser.open(url)
            print(tiktok_finish(input("Redirected URL: "), state))
        else:
            pages = instagram_accounts(args.token or input("Paste a short-lived user token: "))
            for i, p in enumerate(pages):
                print(f"[{i}] {p['name']} -> @{p['instagram_business_account'].get('username')}")
            idx = 0 if len(pages) == 1 else int(input("Choose account #: "))
            print(instagram_save(pages[idx]))
    except Exception as e:
        sys.exit(f"error: {e}")
    print(f"Saved to {ENV_FILE}")


if __name__ == "__main__":
    main()
