"""Draws the AiAlgobot button icons into assets/icons (run once; the PNGs are committed).

Each icon is a small rounded tile in the AiAlgoPro palette with a white symbol, drawn at 4x and scaled
down for smooth edges.     python make_icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).with_name("assets") / "icons"
SIZE, K = 20, 4
S = SIZE * K
W = (255, 255, 255, 255)

BLUE, CYAN, GREEN, RED, AMBER, VIOLET, SLATE, PINK = (
    (37, 99, 235), (8, 145, 178), (22, 163, 74), (225, 29, 72), (217, 119, 6), (124, 58, 237), (71, 85, 105), (219, 39, 119))


def tile(color):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    top = tuple(min(255, c + 40) for c in color)
    for y in range(S):  # soft vertical gradient
        t = y / (S - 1)
        d.line([(0, y), (S, y)], fill=tuple(round(top[i] + (color[i] - top[i]) * t) for i in range(3)) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=18, fill=255)
    out = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out, ImageDraw.Draw(out)


def p(*xy):  # 0-20 grid to pixels
    return [v * K for v in xy]


def play(d):
    d.polygon(p(7, 5, 15, 10, 7, 15), fill=W)


def stop(d):
    d.rounded_rectangle(p(6, 6, 14, 14), radius=4, fill=W)


def dot(d):
    d.ellipse(p(5, 5, 15, 15), outline=W, width=2 * K)
    d.ellipse(p(8, 8, 12, 12), fill=W)


def note(d):
    d.line(p(12, 4, 12, 13), fill=W, width=2 * K)
    d.line(p(12, 4, 15, 6), fill=W, width=2 * K)
    d.ellipse(p(6, 11, 12, 16), fill=W)


def disk(d):
    d.rounded_rectangle(p(4, 4, 16, 16), radius=6, outline=W, width=2 * K)
    d.rectangle(p(7, 4, 13, 8), fill=W)
    d.rectangle(p(7, 11, 13, 16), fill=W)


def flask(d):
    d.line(p(8, 4, 12, 4), fill=W, width=2 * K)
    d.polygon(p(8.5, 4, 11.5, 4, 11.5, 8, 15.5, 15.5, 4.5, 15.5, 8.5, 8), outline=W, width=2 * K)
    d.polygon(p(6.5, 12, 13.5, 12, 15, 15, 5, 15), fill=W)


def check(d):
    d.line(p(5, 10.5, 8.5, 14, 15, 6), fill=W, width=int(2.4 * K), joint="curve")


def rocket(d):
    d.ellipse(p(7.5, 3, 12.5, 14), fill=W)
    d.polygon(p(7.5, 10, 5, 14, 7.5, 13), fill=W)
    d.polygon(p(12.5, 10, 15, 14, 12.5, 13), fill=W)
    d.polygon(p(9, 14, 11, 14, 10, 17), fill=W)


def download(d):
    d.line(p(10, 4, 10, 12), fill=W, width=2 * K)
    d.polygon(p(6, 10, 14, 10, 10, 14.5), fill=W)
    d.line(p(5, 16, 15, 16), fill=W, width=2 * K)


def desktop(d):
    d.rounded_rectangle(p(4, 5, 16, 13), radius=4, outline=W, width=2 * K)
    d.line(p(10, 13, 10, 15.5), fill=W, width=2 * K)
    d.line(p(7, 16, 13, 16), fill=W, width=2 * K)


def youtube(d):
    d.rounded_rectangle(p(3.5, 5.5, 16.5, 14.5), radius=10, fill=W)


def youtube_glyph(img, color):
    d = ImageDraw.Draw(img)
    youtube(d)
    d.polygon(p(8.5, 7.5, 12.5, 10, 8.5, 12.5), fill=color + (255,))


def globe(d):
    d.ellipse(p(4, 4, 16, 16), outline=W, width=int(1.6 * K))
    d.ellipse(p(7.5, 4, 12.5, 16), outline=W, width=int(1.4 * K))
    d.line(p(4.5, 10, 15.5, 10), fill=W, width=int(1.4 * K))


def key(d):
    d.ellipse(p(4, 6, 10, 12), outline=W, width=2 * K)
    d.line(p(10, 9, 16, 9), fill=W, width=2 * K)
    d.line(p(14, 9, 14, 12), fill=W, width=2 * K)


def steps(d):
    for y in (6, 10, 14):
        d.ellipse(p(4, y - 1.2, 6.4, y + 1.2), fill=W)
        d.line(p(8, y, 16, y), fill=W, width=int(1.8 * K))


def search(d):
    d.ellipse(p(4, 4, 12.5, 12.5), outline=W, width=2 * K)
    d.line(p(11.5, 11.5, 16, 16), fill=W, width=int(2.4 * K))


def window(d):
    d.rounded_rectangle(p(4, 5, 16, 15), radius=4, outline=W, width=2 * K)
    d.line(p(4, 8, 16, 8), fill=W, width=2 * K)


def chat(d):
    d.rounded_rectangle(p(4, 4.5, 16, 12.5), radius=8, fill=W)
    d.polygon(p(7, 12, 10, 12, 6.5, 16), fill=W)


def eye(d):
    d.ellipse(p(3.5, 6.5, 16.5, 13.5), outline=W, width=2 * K)
    d.ellipse(p(8, 8, 12, 12), fill=W)


def plane(d):
    d.polygon(p(4, 9.5, 16, 4.5, 11.5, 16, 9.5, 11), fill=W)


def link(d):
    d.ellipse(p(3, 7, 11.5, 13), outline=W, width=int(1.7 * K))
    d.ellipse(p(8.5, 7, 17, 13), outline=W, width=int(1.7 * K))


def folder(d):
    d.polygon(p(4, 6, 8.5, 6, 10, 7.5, 16, 7.5, 16, 15, 4, 15), fill=W)


ICONS = {
    "play": (GREEN, play), "stop": (RED, stop), "live": (RED, dot), "tiktok": (PINK, note), "save": (BLUE, disk),
    "test": (VIOLET, flask), "check": (GREEN, check), "autopilot": (CYAN, rocket), "update": (BLUE, download),
    "shortcut": (SLATE, desktop), "youtube": (RED, None), "globe": (CYAN, globe), "key": (AMBER, key),
    "steps": (VIOLET, steps), "search": (SLATE, search), "window": (PINK, window), "chat": (CYAN, chat),
    "eye": (SLATE, eye), "send": (CYAN, plane), "link": (RED, link), "folder": (AMBER, folder),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (color, glyph) in ICONS.items():
        img, d = tile(color)
        if name == "youtube":
            youtube_glyph(img, color)
        else:
            glyph(d)
        img.resize((SIZE, SIZE), Image.LANCZOS).save(OUT / f"{name}.png")
    print(f"{len(ICONS)} icons in {OUT}")


if __name__ == "__main__":
    main()
