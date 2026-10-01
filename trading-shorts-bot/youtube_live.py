"""YouTube Live agent's plumbing: broadcast + reusable stream key, go live, end.

Needs the full "youtube" OAuth scope (uploads only need youtube.upload), so run
`python auth_setup.py youtube` once more after updating. The channel must also
have live streaming enabled (youtube.com/features); the first time takes up to 24 hours.

The stream (server URL + key) is created once and reused every day; its id is
saved as YOUTUBE_LIVE_STREAM_ID. Each day gets its own broadcast (the video page).
"""
from __future__ import annotations

import logging
import time

from config import env, env_float, require_env, save_env

log = logging.getLogger(__name__)

LIVE_SCOPES = ["https://www.googleapis.com/auth/youtube"]


class LiveError(Exception):
    pass


def service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from upload_youtube import TOKEN_URI

    client_id, secret, refresh = require_env("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    creds = Credentials(None, refresh_token=refresh, token_uri=TOKEN_URI,
                        client_id=client_id, client_secret=secret, scopes=LIVE_SCOPES)
    try:
        creds.refresh(Request())
    except Exception as e:
        raise LiveError(f"{e} - run `python auth_setup.py youtube` again to grant live-streaming access") from e
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def check() -> str:
    yt = service()
    yt.liveStreams().list(part="id", mine=True, maxResults=1).execute()
    return "live-streaming access OK"


def ensure_stream(yt) -> dict:
    """Return {"id", "server", "key"} for the reusable RTMP stream, creating it on first use."""
    sid = env("YOUTUBE_LIVE_STREAM_ID")
    items = yt.liveStreams().list(part="id,cdn", id=sid).execute().get("items", []) if sid else []
    if not items:
        body = {"snippet": {"title": "Stock scanner (bot)"},
                "cdn": {"ingestionType": "rtmp", "resolution": "variable", "frameRate": "variable"},
                "contentDetails": {"isReusable": True}}
        items = [yt.liveStreams().insert(part="snippet,cdn,contentDetails", body=body).execute()]
        save_env("YOUTUBE_LIVE_STREAM_ID", items[0]["id"])
        log.info("youtube: created reusable live stream %s", items[0]["id"])
    info = items[0]["cdn"]["ingestionInfo"]
    return {"id": items[0]["id"], "server": info["ingestionAddress"], "key": info["streamName"]}


def create_broadcast(yt, *, title: str, description: str, start_iso: str, privacy: str) -> str:
    body = {
        "snippet": {"title": title, "description": description, "scheduledStartTime": start_iso},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        "contentDetails": {"enableAutoStart": True, "enableAutoStop": True, "enableDvr": True,
                           "latencyPreference": env("YOUTUBE_LIVE_LATENCY", "low"),
                           "monitorStream": {"enableMonitorStream": False}},
    }
    return yt.liveBroadcasts().insert(part="snippet,status,contentDetails", body=body).execute()["id"]


def bind(yt, broadcast_id: str, stream_id: str) -> None:
    yt.liveBroadcasts().bind(id=broadcast_id, streamId=stream_id, part="id,contentDetails").execute()


def tag(yt, broadcast_id: str, *, title: str, description: str, tags: list[str]) -> None:
    """Broadcasts can't take tags/category at insert time; set them on the video afterwards."""
    snippet = {"title": title, "description": description, "tags": tags,
               "categoryId": env("YOUTUBE_CATEGORY_ID", "27") or "27"}
    yt.videos().update(part="snippet", body={"id": broadcast_id, "snippet": snippet}).execute()


def set_thumbnail(yt, broadcast_id: str, path) -> None:
    from googleapiclient.http import MediaFileUpload

    yt.thumbnails().set(videoId=broadcast_id, media_body=MediaFileUpload(str(path), mimetype="image/jpeg")).execute()


def lifecycle(yt, broadcast_id: str) -> str | None:
    items = yt.liveBroadcasts().list(part="status", id=broadcast_id).execute().get("items", [])
    return items[0]["status"]["lifeCycleStatus"] if items else None


def stream_status(yt, stream_id: str) -> str | None:
    items = yt.liveStreams().list(part="status", id=stream_id).execute().get("items", [])
    return items[0]["status"]["streamStatus"] if items else None


def go_live(yt, broadcast_id: str, stream_id: str, sleep=time.sleep) -> str:
    """Wait for OBS's signal to arrive, then make sure the broadcast is live (auto-start usually does it)."""
    deadline = time.monotonic() + env_float("YOUTUBE_LIVE_TIMEOUT", 180)
    while time.monotonic() < deadline:
        state = lifecycle(yt, broadcast_id)
        if state in ("live", "liveStarting"):
            return state
        if state in ("complete", "revoked", None):
            raise LiveError(f"broadcast {broadcast_id} is {state or 'gone'}")
        if stream_status(yt, stream_id) == "active" and state in ("ready", "testing"):
            yt.liveBroadcasts().transition(broadcastStatus="live", id=broadcast_id, part="status").execute()
        sleep(5)
    raise LiveError("YouTube never received the stream - is OBS streaming? Check the YouTube Studio live page")


def end(yt, broadcast_id: str) -> None:
    if lifecycle(yt, broadcast_id) in ("live", "liveStarting"):
        yt.liveBroadcasts().transition(broadcastStatus="complete", id=broadcast_id, part="status").execute()
