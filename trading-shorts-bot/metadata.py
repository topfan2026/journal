"""Copywriter agent: title / description / tags / hashtags / captions / thumbnail text.

Sources, highest priority first:
  1. values you put in meta.json (title, description, tags, hashtags,
     thumbnail_text, youtube.title, instagram.caption, tiktok.caption, ...)
  2. Claude, which writes anything missing from the subject + caption.txt
  3. a plain template fallback (no API key / API error)

METADATA_MODE=fill   (default) call Claude only if something is missing
METADATA_MODE=always always call Claude, but meta.json values still win
METADATA_MODE=off    never call Claude
"""
from __future__ import annotations

import json
import logging
import re

from config import Settings, env
from job import Job

log = logging.getLogger(__name__)

YT_TITLE_MAX = 100
YT_DESC_MAX = 5000
YT_TAGS_MAX_CHARS = 500
IG_CAPTION_MAX = 2200
IG_MAX_HASHTAGS = 30
TIKTOK_CAPTION_MAX = 2200  # UTF-16 code units

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "hashtags": {"type": "array", "items": {"type": "string"}},
        "instagram_caption": {"type": "string"},
        "tiktok_caption": {"type": "string"},
        "thumbnail_text": {"type": "string"},
    },
    "required": ["title", "description", "tags", "hashtags", "instagram_caption",
                 "tiktok_caption", "thumbnail_text"],
    "additionalProperties": False,
}

SYSTEM = """You write publishing metadata for vertical short-form videos (YouTube Shorts, \
Instagram Reels, TikTok) that are about 60 seconds long.

You get the video's subject, its script or caption when available, and any fields the \
creator already fixed. Write metadata that accurately reflects what the video says. Viewers \
who click should get what the title promised, so no invented claims, numbers or results.

Field guidance:
- title: at most 70 characters, specific and curiosity-driven, no hashtags, no emoji spam.
- description: 2-4 short sentences for YouTube summarising the video's value, with a soft \
call to action (follow/subscribe). No hashtags; they are appended separately.
- tags: 10-15 YouTube search keywords/phrases, lowercase, no '#'.
- hashtags: 5-8 relevant hashtags without the '#', mixing broad and niche.
- instagram_caption: hook line, 1-3 short lines of value, CTA. No hashtags.
- tiktok_caption: one or two punchy lines, at most 150 characters, no hashtags.
- thumbnail_text: 2-5 word, high-contrast hook for the thumbnail, uppercase.

If the subject involves trading, investing or money, never promise profits or guaranteed \
returns and keep the tone educational."""


# ---------------------------------------------------------------------------
# helpers

def clean_hashtag(tag: str) -> str:
    return re.sub(r"[^\w]", "", str(tag).lstrip("#"), flags=re.UNICODE)


def truncate(text: str, limit: int, measure=len) -> str:
    text = text.strip()
    if measure(text) <= limit:
        return text
    cut = text
    while cut and measure(cut + "…") > limit:
        # every character costs at least one unit, so dropping `overflow` chars never overshoots
        overflow = measure(cut + "…") - limit
        cut = cut[: len(cut) - overflow]
    space = cut.rfind(" ")
    if space > len(cut) * 0.6:
        cut = cut[:space]
    return cut.rstrip(" ,.;:-") + "…"


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def hashtag_line(tags: list[str], existing_text: str = "", limit: int | None = None) -> str:
    present = {t.lower() for t in re.findall(r"#(\w+)", existing_text, flags=re.UNICODE)}
    out = []
    for t in tags:
        t = clean_hashtag(t)
        if t and t.lower() not in present:
            present.add(t.lower())
            out.append("#" + t)
    if limit is not None:
        out = out[: max(0, limit - len(re.findall(r"#\w+", existing_text)))]
    return " ".join(out)


def _join(*parts: str) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def _no_angle(s: str) -> str:
    return s.replace("<", "").replace(">", "")  # YouTube rejects < and > in snippet text


# ---------------------------------------------------------------------------
# Claude

def _user_fields(job: Job) -> dict:
    m = job.meta
    fields = {
        "title": m.get("title"),
        "description": m.get("description"),
        "tags": m.get("tags"),
        "hashtags": m.get("hashtags"),
        "thumbnail_text": m.get("thumbnail_text"),
        "instagram_caption": job.opts("instagram").get("caption"),
        "tiktok_caption": job.opts("tiktok").get("caption"),
    }
    return {k: v for k, v in fields.items() if v}


def _ask_claude(job: Job, settings: Settings, duration: float | None) -> dict:
    import anthropic

    brief = {
        "subject": job.subject,
        "script_or_caption": job.caption or None,
        "duration_seconds": round(duration) if duration else None,
        "creator_notes": job.meta.get("notes"),
        "channel_style": env("CHANNEL_STYLE"),
        "fields_already_fixed_by_creator": _user_fields(job) or None,
    }
    brief = {k: v for k, v in brief.items() if v}
    client = anthropic.Anthropic(max_retries=3)
    kwargs = dict(
        model=settings.claude_model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM,
        messages=[{"role": "user", "content": "Write the metadata for this video.\n\n"
                   + json.dumps(brief, indent=2, ensure_ascii=False)}],
    )
    if settings.claude_model == "claude-opus-5":
        # Server-side fallback: if the request is declined, it re-runs on the recommended model.
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    resp = client.beta.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude declined to write metadata for this video")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("Claude response was cut off (max_tokens)")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


def _template(job: Job) -> dict:
    first = next((ln.strip() for ln in job.caption.splitlines() if ln.strip()), "")
    words = [w for w in re.findall(r"[A-Za-z0-9]+", job.subject) if len(w) > 2][:8]
    return {
        "title": truncate(job.subject, 70),
        "description": job.caption or job.subject,
        "tags": [w.lower() for w in words],
        "hashtags": words[:5],
        "instagram_caption": job.caption or job.subject,
        "tiktok_caption": first or job.subject,
        "thumbnail_text": " ".join(job.subject.split()[:4]).upper(),
    }


# ---------------------------------------------------------------------------
# public

def generate(job: Job, settings: Settings, duration: float | None = None) -> dict:
    """Return the final per-platform metadata (all limits applied)."""
    user = _user_fields(job)
    needs_ai = any(k not in user for k in ("title", "description", "tags", "hashtags", "thumbnail_text"))
    base: dict = {}
    source = "meta.json"
    if settings.metadata_mode == "always" or (settings.metadata_mode == "fill" and needs_ai):
        try:
            base = _ask_claude(job, settings, duration)
            source = f"claude ({settings.claude_model})"
        except Exception as e:
            log.warning("%s: Claude metadata failed (%s) - using template fallback", job.name, e)
    if not base:
        base = _template(job)
        if needs_ai:
            source = "template"
    data = {**base, **user}

    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",")]
    hashtags = data.get("hashtags") or []
    if isinstance(hashtags, str):
        hashtags = hashtags.split()
    hashtags = [clean_hashtag(h) for h in hashtags if clean_hashtag(h)]
    disclaimer = str(job.meta.get("disclaimer", settings.disclaimer) or "")

    # YouTube
    yt = job.opts("youtube")
    title = _no_angle(str(yt.get("title") or data["title"])).strip()
    if "#shorts" not in title.lower() and len(title) + 8 <= YT_TITLE_MAX:
        title += " #Shorts"
    title = truncate(title, YT_TITLE_MAX)
    yt_desc_body = _no_angle(str(yt.get("description") or data["description"]))
    yt_tags_line = hashtag_line(["Shorts", *hashtags], yt_desc_body)
    yt_description = truncate(_join(yt_desc_body, disclaimer, yt_tags_line), YT_DESC_MAX,
                              measure=lambda s: len(s.encode("utf-8")))
    yt_tags, used = [], 0
    for t in [*(str(t).strip().lstrip("#") for t in tags), *hashtags]:
        cost = len(t) + (2 if " " in t else 0) + (1 if yt_tags else 0)
        if t and t.lower() not in {x.lower() for x in yt_tags} and used + cost <= YT_TAGS_MAX_CHARS:
            yt_tags.append(_no_angle(t))
            used += cost

    # Instagram
    ig_body = str(data.get("instagram_caption") or data["description"])
    ig_caption = truncate(
        _join(ig_body, disclaimer, hashtag_line(hashtags, ig_body, IG_MAX_HASHTAGS)), IG_CAPTION_MAX)

    # TikTok
    tt_body = str(data.get("tiktok_caption") or data["title"])
    tt_caption = truncate(_join(tt_body, disclaimer, hashtag_line(hashtags, tt_body)),
                          TIKTOK_CAPTION_MAX, measure=utf16_len)

    return {
        "source": source,
        "title": str(data["title"]),
        "hashtags": hashtags,
        "thumbnail_text": str(data.get("thumbnail_text") or "").strip(),
        "youtube": {"title": title, "description": yt_description, "tags": yt_tags},
        "instagram": {"caption": ig_caption},
        "tiktok": {"caption": tt_caption},
    }
