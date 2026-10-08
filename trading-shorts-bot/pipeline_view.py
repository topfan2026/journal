"""Animated flow diagram of the live bot for the app's Status tab (Tk canvas, no extra packages).

    Trigger            Market data          Broadcast            Audience
    Scheduler  ─────▶  IB Gateway           YouTube broadcast ─┐
    Wake timer         Scanner      ─────▶  OBS  ──────────────┴▶ YouTube Live
                                    ───────────────────────────▶ TikTok LIVE
                       Autopilot (simulated traders on the website)

Each node is grey (idle), orange and pulsing (working), green (ok) or red (failed); dots flow
along a connection while the node it feeds is working or running.
"""
from __future__ import annotations

import math

BG = "#0d1117"
PANEL = "#11161f"
GROUP = "#2d3644"
TEXT = "#e6edf3"
MUTED = "#7d8590"
STATE_COLORS = {"ok": "#3fb950", "working": "#f0883e", "failed": "#f85149", "waiting": "#484f58", "off": "#30363d"}

GROUPS = [("Trigger", 0.02, 0.22), ("Market data", 0.27, 0.48), ("Broadcast", 0.53, 0.74), ("Audience", 0.79, 0.98)]
# key: (label, icon, group index, y fraction)
NODES = {
    "scheduler": ("Scheduler", "⏱", 0, 0.26),
    "wake": ("Wake timer", "☾", 0, 0.74),
    "gateway": ("IB Gateway", "⇄", 1, 0.14),
    "scanner": ("Scanner", "▦", 1, 0.5),
    "autopilot": ("Autopilot", "⚙", 1, 0.86),
    "youtube": ("YouTube broadcast", "✎", 2, 0.26),
    "obs": ("OBS", "◉", 2, 0.74),
    "live": ("YouTube Live", "▶", 3, 0.26),
    "tiktok": ("TikTok LIVE", "♪", 3, 0.74),
}
EDGES = [("wake", "scheduler"), ("scheduler", "gateway"), ("gateway", "scanner"), ("scanner", "autopilot"), ("scanner", "youtube"),
         ("scanner", "obs"), ("youtube", "obs"), ("obs", "live"), ("scanner", "tiktok")]
R = 24


def bezier(p0, p1, n=40, c1=None, c2=None):
    """Smooth curve from p0 to p1 (horizontal tangents unless control points are given)."""
    (x0, y0), (x3, y3) = p0, p1
    dx = (x3 - x0) * 0.5
    x1, y1 = c1 or (x0 + dx, y0)
    x2, y2 = c2 or (x3 - dx, y3)
    pts = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
        pts.append((a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3))
    return pts


class PipelineView:
    def __init__(self, parent, height: int = 320):
        import tkinter as tk
        self.c = tk.Canvas(parent, height=height, bg=BG, highlightthickness=0)
        self.states: dict[str, tuple[str, str]] = {k: ("waiting", "") for k in NODES}
        self.tick = 0
        self.c.bind("<Configure>", lambda e: self.draw())
        self._animate()

    def grid(self, **kw):
        self.c.grid(**kw)

    # ------------------------------------------------------------------ geometry
    def pos(self, key):
        w, h = max(self.c.winfo_width(), 400), max(self.c.winfo_height(), 200)
        _, _, g, fy = NODES[key]
        _, a, b = GROUPS[g]
        return (a + b) / 2 * w, 30 + fy * (h - 60)

    def edge_points(self, a, b):
        (x0, y0), (x1, y1) = self.pos(a), self.pos(b)
        if abs(x1 - x0) < 5:  # inside a group: loop round the left side, clear of the labels
            lx = x0 - R - 2
            return bezier((lx, y0), (lx, y1), c1=(lx - 45, y0), c2=(lx - 45, y1))
        sign = 1 if x1 > x0 else -1
        p0, p1 = (x0 + sign * (R + 2), y0), (x1 - sign * (R + 2), y1)
        if any(self.pos(k)[1] == y0 and min(x0, x1) < self.pos(k)[0] < max(x0, x1) for k in NODES):
            dip = 70  # a node sits in the way: pass underneath it
            return bezier(p0, p1, c1=(p0[0] + 60, y0 + dip), c2=(p1[0] - 60, y1 + dip))
        return bezier(p0, p1)

    # ------------------------------------------------------------------ drawing
    def set_states(self, states: dict[str, tuple[str, str]]) -> None:
        if states != self.states:
            self.states = dict(states)
            self.draw()

    def draw(self):
        c = self.c
        c.delete("all")
        w, h = max(c.winfo_width(), 400), max(c.winfo_height(), 200)
        for title, a, b in GROUPS:
            x0, x1 = a * w, b * w
            c.create_rectangle(x0, 8, x1, h - 8, outline=GROUP, dash=(4, 4), fill=PANEL)
            c.create_text((x0 + x1) / 2, 24, text=title, fill=TEXT, font=("Segoe UI", 11, "bold"))
        for a, b in EDGES:
            pts = self.edge_points(a, b)
            active = self.flowing(a, b)
            color = STATE_COLORS[self.states[b][0]] if active else "#3a4250"
            c.create_line(*[v for p in pts for v in p], fill=color, width=2 if active else 1, smooth=True,
                          tags=("edge",))
            c.create_oval(pts[0][0] - 3, pts[0][1] - 3, pts[0][0] + 3, pts[0][1] + 3, fill=color, outline="")
            c.create_oval(pts[-1][0] - 3, pts[-1][1] - 3, pts[-1][0] + 3, pts[-1][1] + 3, fill=color, outline="")
        for key, (label, icon, _, _) in NODES.items():
            x, y = self.pos(key)
            state, detail = self.states.get(key, ("waiting", ""))
            color = STATE_COLORS.get(state, STATE_COLORS["waiting"])
            if state == "working":
                c.create_oval(x - R - 6, y - R - 6, x + R + 6, y + R + 6, outline=color, width=2,
                              tags=("pulse",))
            c.create_oval(x - R, y - R, x + R, y + R, fill="#161b22", outline=color, width=3)
            c.create_text(x, y, text=icon, fill=TEXT if state != "off" else MUTED, font=("Segoe UI Symbol", 15))
            c.create_text(x, y + R + 12, text=label, fill=TEXT if state != "off" else MUTED,
                          font=("Segoe UI", 10, "bold"))
            if detail:
                c.create_text(x, y + R + 28, text=detail if len(detail) <= 26 else detail[:25] + "…", fill=color if state != "waiting" else MUTED,
                              font=("Segoe UI", 9))
        self.dots = []

    def flowing(self, a, b) -> bool:
        return self.states[a][0] == "ok" and self.states[b][0] in ("ok", "working")

    # ------------------------------------------------------------------ animation
    def _animate(self):
        c = self.c
        try:
            c.delete("dot")
            self.tick += 1
            for a, b in EDGES:
                if not self.flowing(a, b):
                    continue
                pts = self.edge_points(a, b)
                color = STATE_COLORS[self.states[b][0]]
                for k in range(3):
                    t = ((self.tick * 0.015) + k / 3) % 1
                    x, y = pts[int(t * (len(pts) - 1))]
                    c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline="", tags=("dot",))
            pulse = 4 + 3 * math.sin(self.tick / 4)
            for item in c.find_withtag("pulse"):
                x0, y0, x1, y1 = c.coords(item)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                c.coords(item, cx - R - pulse, cy - R - pulse, cx + R + pulse, cy + R + pulse)
            c.after(50, self._animate)
        except Exception:
            pass  # window closed
