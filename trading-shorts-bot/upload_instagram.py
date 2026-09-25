"""Instagram upload agent: Instagram Graph API Content Publishing (Reels).

Requires an Instagram Business or Creator account linked to a Facebook Page.

Flow (3 steps; the local file is sent directly, so no public video_url or Drive link is needed):
  1. POST /{ig-user-id}/media  media_type=REELS, upload_type=resumable  -> container id + upload uri
  2. POST https://rupload.facebook.com/ig-api-upload/{ver}/{container}   (raw mp4 bytes)
     then poll GET /{container}?fields=status_code until FINISHED
  3. POST /{ig-user-id}/media_publish  creation_id={container}           -> media id

.env: IG_USER_ID, IG_TOKEN (long-lived; `python auth_setup.py instagram` gets
a non-expiring Page token), optional IG_GRAPH_HOST, IG_API_VERSION.

meta.json "instagram" options: caption, share_to_feed (default true),
audio_name, collaborators (list of usernames), location_id.
"""
from __future__ import annotations

import json
import logging
import time

import requests

from common import Post, UploadError, UploadResult, api_error
from config import env, env_float, require_env

log = logging.getLogger(__name__)

DEFAULT_API_VERSION = "v23.0"


def _cfg():
    user_id, token = require_env("IG_USER_ID", "IG_TOKEN")
    host = env("IG_GRAPH_HOST", "graph.facebook.com")
    version = env("IG_API_VERSION", DEFAULT_API_VERSION)
    return user_id, token, f"https://{host}/{version}", version


def _call(method: str, url: str, **kw) -> dict:
    kw.setdefault("timeout", 60)
    resp = requests.request(method, url, **kw)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or (isinstance(data, dict) and "error" in data):
        raise api_error(resp, "Instagram")
    return data


def check() -> str:
    user_id, token, base, _ = _cfg()
    data = _call("GET", f"{base}/{user_id}", params={"fields": "username", "access_token": token})
    return "@" + data.get("username", "?")


def _wait_until_ready(base: str, container: str, token: str) -> None:
    deadline = time.monotonic() + env_float("IG_PROCESS_TIMEOUT", 900)
    while True:
        data = _call("GET", f"{base}/{container}", params={"fields": "status_code,status", "access_token": token})
        code = data.get("status_code")
        if code in ("FINISHED", "PUBLISHED"):
            return
        if code in ("ERROR", "EXPIRED"):
            raise UploadError(f"Instagram processing {code}: {data.get('status')}")
        if time.monotonic() > deadline:
            raise UploadError(f"Instagram processing timed out (last status {code})")
        time.sleep(10)


def upload(post: Post) -> UploadResult:
    user_id, token, base, version = _cfg()
    o = post.opts
    params = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": post.metadata["instagram"]["caption"],
        "share_to_feed": "true" if o.get("share_to_feed", True) else "false",
        "thumb_offset": str(post.cover_time_ms),
        "access_token": token,
    }
    if o.get("audio_name"):
        params["audio_name"] = str(o["audio_name"])
    if o.get("collaborators"):
        params["collaborators"] = json.dumps(list(o["collaborators"]))
    if o.get("location_id"):
        params["location_id"] = str(o["location_id"])

    container = _call("POST", f"{base}/{user_id}/media", data=params)
    cid = container["id"]
    upload_uri = container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{version}/{cid}"

    size = post.video.stat().st_size
    with open(post.video, "rb") as fh:
        up = _call("POST", upload_uri, data=fh, timeout=900, headers={
            "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)})
    if up.get("success") is False:
        raise UploadError(f"Instagram video upload failed: {up}")
    log.info("instagram: %s uploaded, waiting for processing", post.name)
    _wait_until_ready(base, cid, token)

    for attempt in range(3):
        try:
            media = _call("POST", f"{base}/{user_id}/media_publish",
                          data={"creation_id": cid, "access_token": token})
            break
        except UploadError:
            if attempt == 2:
                raise
            time.sleep(15)
    media_id = media["id"]
    permalink = None
    try:
        permalink = _call("GET", f"{base}/{media_id}",
                          params={"fields": "permalink", "access_token": token}).get("permalink")
    except UploadError as e:
        log.warning("instagram: could not fetch permalink: %s", e)
    return UploadResult(id=media_id, url=permalink, extra={"container_id": cid})
