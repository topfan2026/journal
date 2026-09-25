"""YouTube upload agent: YouTube Data API v3.

A vertical video of 3 minutes or less is classified as a Short automatically;
"#Shorts" is also added to the title and description.

.env: YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
(get the refresh token once with `python auth_setup.py youtube`).

meta.json "youtube" options: privacy (public|unlisted|private), publish_at
(ISO 8601, which forces private until then), category_id, made_for_kids,
language, notify_subscribers, title, description.
"""
from __future__ import annotations

import logging

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from common import Post, UploadError, UploadResult
from config import env, require_env

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def service():
    client_id, secret, refresh = require_env("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    creds = Credentials(None, refresh_token=refresh, token_uri=TOKEN_URI,
                        client_id=client_id, client_secret=secret, scopes=SCOPES)
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def check() -> str:
    service()
    return "refresh token OK"


def upload(post: Post) -> UploadResult:
    o, md = post.opts, post.metadata["youtube"]
    privacy = str(o.get("privacy") or env("YOUTUBE_PRIVACY", "public"))
    status = {
        "privacyStatus": privacy,
        "selfDeclaredMadeForKids": bool(o.get("made_for_kids", False)),
        "containsSyntheticMedia": bool(o.get("ai_generated", post.settings.ai_generated)),
    }
    if o.get("publish_at"):
        status.update(privacyStatus="private", publishAt=str(o["publish_at"]))
    snippet = {
        "title": md["title"],
        "description": md["description"],
        "tags": md["tags"],
        "categoryId": str(o.get("category_id") or env("YOUTUBE_CATEGORY_ID", "27")),  # 27 = Education
    }
    if o.get("language"):
        snippet["defaultLanguage"] = snippet["defaultAudioLanguage"] = o["language"]

    yt = service()
    media = MediaFileUpload(str(post.video), mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    request = yt.videos().insert(
        part="snippet,status",
        body={"snippet": snippet, "status": status},
        media_body=media,
        notifySubscribers=bool(o.get("notify_subscribers", True)),
    )
    response = None
    try:
        while response is None:
            progress, response = request.next_chunk(num_retries=5)
            if progress:
                log.info("youtube: %s uploaded %d%%", post.name, int(progress.progress() * 100))
    except HttpError as e:
        raise UploadError(f"YouTube upload failed: {e}") from e

    video_id = response["id"]
    extra = {"privacy": response.get("status", {}).get("privacyStatus")}
    if post.thumbnail:
        try:
            yt.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(post.thumbnail), mimetype="image/jpeg")
            ).execute(num_retries=3)
            extra["thumbnail"] = "set"
        except HttpError as e:
            # Most often the channel isn't phone-verified for custom thumbnails; the video itself is live.
            log.warning("youtube: thumbnail not set for %s: %s", video_id, e)
            extra["thumbnail"] = f"failed: {e.reason if hasattr(e, 'reason') else e}"
    return UploadResult(id=video_id, url=f"https://www.youtube.com/shorts/{video_id}",
                        status=extra["privacy"] or "uploaded", extra=extra)
