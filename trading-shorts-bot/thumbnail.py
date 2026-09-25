"""Thumbnail agent: build the YouTube thumbnail and pick the cover frame.

- If the job folder has thumbnail.jpg/png, that image is used as-is (converted to JPEG under 2 MB).
- Otherwise a frame is grabbed at meta.json "thumbnail_time" (seconds, default 1.5)
  and the thumbnail_text hook is drawn on it.

Instagram and TikTok can't take a custom image from a local file through
their APIs, so both use the same frame time as their cover.
"""
from __future__ import annotations

import logging
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from config import env
from stitch import extract_frame

log = logging.getLogger(__name__)

YT_THUMB_MAX_BYTES = 2 * 1024 * 1024
FONT_CANDIDATES = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "Arial Bold.ttf",
)


def _font(size: int) -> ImageFont.ImageFont:
    for name in filter(None, (env("THUMB_FONT"), *FONT_CANDIDATES)):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def draw_hook(img: Image.Image, text: str) -> Image.Image:
    text = text.strip().upper()
    if not text:
        return img
    img = img.convert("RGB")
    w, h = img.size
    size = int(w * 0.12)
    draw = ImageDraw.Draw(img)
    while True:
        font = _font(size)
        chars = max(6, int(w * 0.9 / (size * 0.6)))
        lines = textwrap.wrap(text, width=chars)[:4]
        widths = [draw.textlength(ln, font=font) for ln in lines]
        if max(widths) <= w * 0.92 or size <= 24:
            break
        size = int(size * 0.9)
    stroke = max(2, size // 12)
    line_h = int(size * 1.15)
    block_h = line_h * len(lines)
    top = int(h * 0.12)

    band = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(band).rectangle(
        [0, top - size // 3, w, top + block_h + size // 3], fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), band).convert("RGB")
    draw = ImageDraw.Draw(img)
    for i, (ln, lw) in enumerate(zip(lines, widths)):
        draw.text(((w - lw) / 2, top + i * line_h), ln, font=font, fill=(255, 221, 0),
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
    return img


def save_jpeg(img: Image.Image, out: Path) -> Path:
    img = img.convert("RGB")
    for quality in (92, 85, 75, 65, 55):
        img.save(out, "JPEG", quality=quality, optimize=True)
        if out.stat().st_size <= YT_THUMB_MAX_BYTES:
            return out
    img.thumbnail((1080, 1920))
    img.save(out, "JPEG", quality=70, optimize=True)
    return out


def make_thumbnail(video: Path, out_dir: Path, *, text: str, custom: Path | None,
                   at_seconds: float, duration: float, base: Path | None = None) -> dict:
    """Returns {"path": thumbnail (relative to *base* if given), "cover_time_ms": int}."""
    at = min(max(0.0, at_seconds), max(0.0, duration - 0.1))
    out = out_dir / "thumbnail.jpg"
    if custom is not None:
        with Image.open(custom) as im:
            save_jpeg(im, out)
        log.info("using custom thumbnail %s", custom.name)
    else:
        frame = extract_frame(video, at, out_dir / "frame.jpg")
        with Image.open(frame) as im:
            save_jpeg(draw_hook(im, text), out)
    return {"path": str(out.relative_to(base) if base else out), "cover_time_ms": int(at * 1000)}
