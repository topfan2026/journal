"""TikTok upload agent: TikTok Content Posting API.

TIKTOK_MODE=inbox  (default; works before app audit, needs scope video.upload)
    POST /v2/post/publish/inbox/video/init/ -> upload chunks -> the video
    arrives in the TikTok app inbox and you tap Post there. The API does not
    accept a caption in this mode; it is saved in job.json for you to paste.

TIKTOK_MODE=direct (needs scope video.publish; posts are private
    (SELF_ONLY) until TikTok audits your app)
    creator_info -> POST /v2/post/publish/video/init/ -> upload chunks -> published

.env: TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REFRESH_TOKEN (from
`python auth_setup.py tiktok`). TIKTOK_TOKEN (access token, 24h) is refreshed
and written back to .env automatically.

meta.json "tiktok" options: mode, caption, privacy_level, disable_comment,
disable_duet, disable_stitch, brand_content, brand_organic.
"""
from __future__ import annotations

import logging
import time

import requests

from common import Post, UploadError, UploadResult, api_error
from config import env, env_float, require_env, save_env

log = logging.getLogger(__name__)

API = "https://open.tiktokapis.com"
MB = 1024 * 1024
SINGLE_CHUNK_MAX = 64 * MB
CHUNK = 10 * MB


class _TokenExpired(Exception):
    pass


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) per TikTok rules: chunks 5-64 MB and the last absorbs the remainder."""
    if size <= SINGLE_CHUNK_MAX:
        return size, 1
    return CHUNK, size // CHUNK


def access_token(force_refresh: bool = False) -> str:
    token = env("TIKTOK_TOKEN")
    expires = float(env("TIKTOK_TOKEN_EXPIRES_AT", "0") or 0)
    refresh = env("TIKTOK_REFRESH_TOKEN")
    if token and not force_refresh and (expires - time.time() > 300 or not refresh):
        return token
    key, secret, refresh = require_env("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN")
    resp = requests.post(f"{API}/v2/oauth/token/", timeout=30, data={
        "client_key": key, "client_secret": secret,
        "grant_type": "refresh_token", "refresh_token": refresh,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    data = resp.json() if resp.content else {}
    if "access_token" not in data:
        raise UploadError(f"TikTok token refresh failed: {data or resp.text[:300]}")
    save_env("TIKTOK_TOKEN", data["access_token"])
    save_env("TIKTOK_TOKEN_EXPIRES_AT", str(int(time.time() + int(data.get("expires_in", 86400)))))
    if data.get("refresh_token"):
        save_env("TIKTOK_REFRESH_TOKEN", data["refresh_token"])
    return data["access_token"]


def _api_once(path: str, body: dict | None, token: str) -> dict:
    resp = requests.post(f"{API}{path}", json=body, timeout=60, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"})
    try:
        data = resp.json()
    except ValueError:
        raise api_error(resp, "TikTok")
    code = (data.get("error") or {}).get("code", "ok")
    if resp.status_code == 401 or code == "access_token_invalid":
        raise _TokenExpired()
    if resp.status_code >= 400 or code != "ok":
        raise UploadError(f"TikTok API {path} HTTP {resp.status_code}: {data.get('error')}")
    return data.get("data") or {}


def _api(path: str, body: dict | None = None) -> dict:
    try:
        return _api_once(path, body, access_token())
    except _TokenExpired:
        return _api_once(path, body, access_token(force_refresh=True))


def check() -> str:
    if (env("TIKTOK_MODE", "inbox") or "inbox").lower() == "inbox":
        access_token()
        return "token OK (inbox mode)"
    info = _api("/v2/post/publish/creator_info/query/")
    return f"@{info.get('creator_username')} privacy options: {info.get('privacy_level_options')}"


def _upload_chunks(url: str, post: Post, size: int, chunk_size: int, count: int) -> None:
    with open(post.video, "rb") as fh:
        for i in range(count):
            start = i * chunk_size
            end = size - 1 if i == count - 1 else start + chunk_size - 1
            fh.seek(start)
            buf = fh.read(end - start + 1)
            for attempt in range(4):
                try:
                    r = requests.put(url, data=buf, timeout=300, headers={
                        "Content-Type": "video/mp4", "Content-Length": str(len(buf)),
                        "Content-Range": f"bytes {start}-{end}/{size}"})
                except requests.RequestException as e:
                    r, err = None, e
                if r is not None and r.status_code in (200, 201, 206):
                    break
                if r is not None and r.status_code < 500 and r.status_code != 429:
                    raise api_error(r, "TikTok upload")
                if attempt == 3:
                    raise UploadError(f"TikTok chunk {i + 1}/{count} failed: "
                                      f"{r.status_code if r is not None else err}")
                time.sleep(2 ** (attempt + 1))
            log.info("tiktok: %s chunk %d/%d uploaded", post.name, i + 1, count)


def upload(post: Post) -> UploadResult:
    o = post.opts
    mode = str(o.get("mode") or env("TIKTOK_MODE", "inbox")).lower()
    size = post.video.stat().st_size
    chunk_size, count = chunk_plan(size)
    source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": count}
    caption = post.metadata["tiktok"]["caption"]
    username = None

    if mode == "inbox":
        init = _api("/v2/post/publish/inbox/video/init/", {"source_info": source})
    elif mode == "direct":
        creator = _api("/v2/post/publish/creator_info/query/")
        username = creator.get("creator_username")
        privacy = str(o.get("privacy_level") or env("TIKTOK_PRIVACY_LEVEL", "SELF_ONLY"))
        options = creator.get("privacy_level_options") or []
        if options and privacy not in options:
            raise UploadError(f"TikTok privacy_level {privacy} not allowed; account allows {options}")
        max_dur = creator.get("max_video_post_duration_sec")
        if max_dur and post.duration > max_dur:
            raise UploadError(f"video is {post.duration:.0f}s; this TikTok account allows {max_dur}s")
        post_info = {
            "title": caption,
            "privacy_level": privacy,
            "disable_comment": bool(o.get("disable_comment", False) or creator.get("comment_disabled", False)),
            "disable_duet": bool(o.get("disable_duet", False) or creator.get("duet_disabled", False)),
            "disable_stitch": bool(o.get("disable_stitch", False) or creator.get("stitch_disabled", False)),
            "video_cover_timestamp_ms": post.cover_time_ms,
            "brand_content_toggle": bool(o.get("brand_content", False)),
            "brand_organic_toggle": bool(o.get("brand_organic", False)),
            "is_aigc": bool(o.get("ai_generated", post.settings.ai_generated)),
        }
        init = _api("/v2/post/publish/video/init/", {"post_info": post_info, "source_info": source})
    else:
        raise UploadError(f"unknown TIKTOK_MODE {mode!r} (use inbox or direct)")

    publish_id, upload_url = init["publish_id"], init["upload_url"]
    _upload_chunks(upload_url, post, size, chunk_size, count)

    deadline = time.monotonic() + env_float("TIKTOK_PROCESS_TIMEOUT", 600)
    status: dict = {}
    while time.monotonic() < deadline:
        status = _api("/v2/post/publish/status/fetch/", {"publish_id": publish_id})
        state = status.get("status")
        if state == "FAILED":
            raise UploadError(f"TikTok processing failed: {status.get('fail_reason')}")
        if state == "PUBLISH_COMPLETE" or (mode == "inbox" and state == "SEND_TO_USER_INBOX"):
            break
        time.sleep(5)
    state = status.get("status") or "PROCESSING"
    # Once the bytes are uploaded, TikTok owns the post; never re-upload it, even if polling times out.
    post_ids = status.get("publicaly_available_post_id") or []  # (sic) TikTok's field name
    url = f"https://www.tiktok.com/@{username}/video/{post_ids[0]}" if username and post_ids else None
    extra = {"mode": mode, "tiktok_status": state}
    if mode == "inbox":
        extra["caption_to_paste"] = caption
    return UploadResult(id=publish_id, url=url,
                        status="in_inbox" if mode == "inbox" else state.lower(), extra=extra)
