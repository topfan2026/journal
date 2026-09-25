"""Types shared by the upload agents."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import requests

from config import Settings


class UploadError(Exception):
    pass


@dataclass
class Post:
    """Everything an upload agent needs, prepared by the earlier agents."""
    name: str
    video: Path
    duration: float
    metadata: dict        # output of metadata.generate()
    thumbnail: Path | None
    cover_time_ms: int
    opts: dict            # meta.json section for this platform ({} if none)
    settings: Settings


@dataclass
class UploadResult:
    id: str
    url: str | None = None
    status: str = "published"
    extra: dict = field(default_factory=dict)


def api_error(resp: requests.Response, platform: str) -> UploadError:
    try:
        body = resp.json()
    except ValueError:
        body = resp.text[:800]
    return UploadError(f"{platform} API HTTP {resp.status_code}: {body}")
