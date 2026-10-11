"""Local web server: the overlay (OBS Browser Source), the control page, music files and a JSON API.

    /                  the overlay, 1920x1080
    /control           switch niche, start/stop trivia, send test chat messages, compare niches
    /api/state         everything the overlay draws
    /api/profiles      the niches and which one is on air
    /api/stats?days=7  per-niche comparison
    /api/music         the active niche's tracks
    /music/<file>      a track
    /backgrounds/<file> a background photo or video
    /api/backgrounds   background files + the active niche's chosen background/effects
    POST /api/control  {"action": "switch" | "trivia_start" | "trivia_stop" | "clear_tasks" | "test_message"
                        | "set_background" | "set_effects" | "reset_look" | "update_restart", ...}
    POST /api/background-upload?name=<file>&slot=day|night   raw file body

It listens on 127.0.0.1 only: the control page has no password, so don't expose the port.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from app import App, ControlError

log = logging.getLogger(__name__)

OVERLAY_DIR = Path(__file__).resolve().parent / "overlay"
PAGES = {"/": "index.html", "/control": "control.html"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BrainBreakLive"

        def log_message(self, fmt, *args):  # quiet: the overlay polls several times a second
            log.debug("http: " + fmt, *args)

        def _send(self, code: int, body: bytes, ctype: str, cache: bool = False) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "max-age=3600" if cache else "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, code: int = 200) -> None:
            self._send(code, json.dumps(data).encode(), "application/json")

        def _file(self, path: Path, cache: bool = False) -> None:
            if not path.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            self._send(200, path.read_bytes(), ctype, cache)

        def _media(self, path: Path) -> None:
            """Stream a music/video file with HTTP Range support (browsers need it to loop and seek)."""
            if not path.is_file():
                return self._json({"error": "not found"}, 404)
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            start, end = 0, size - 1
            m = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", "").strip())
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start, end = int(m.group(1)), int(m.group(2) or size - 1)
                else:
                    start = max(0, size - int(m.group(2)))
                end = min(end, size - 1)
                if start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                self.send_response(206)
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            else:
                self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            try:
                with path.open("rb") as f:
                    f.seek(start)
                    left = end - start + 1
                    while left > 0:
                        chunk = f.read(min(1 << 20, left))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass  # the browser stopped reading (normal when seeking)

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            route = url.path.rstrip("/") or "/"
            if route in PAGES:
                return self._file(OVERLAY_DIR / PAGES[route])
            if route == "/api/state":
                return self._json(app.snapshot())
            if route == "/api/profiles":
                return self._json(app.profiles_public())
            if route == "/api/stats":
                days = int((parse_qs(url.query).get("days") or ["7"])[0] or 7)
                return self._json({"days": days, "rows": app.compare(max(1, min(days, 365)))})
            if route == "/api/backgrounds":
                return self._json(app.looks_public())
            if route == "/api/music":
                return self._json({"profile": app.active, "tracks": app.music()})
            if route.startswith("/music/"):
                name = unquote(route[len("/music/"):])
                if "/" in name or "\\" in name or name.startswith(".") or name not in app.music():
                    return self._json({"error": "not found"}, 404)
                return self._media(app.profile.music_path(app.s) / name)
            if route.startswith("/backgrounds/"):
                name = unquote(route[len("/backgrounds/"):])
                if name not in app.backgrounds():
                    return self._json({"error": "not found"}, 404)
                return self._media(app.s.backgrounds_dir / name)
            if route.startswith("/static/"):
                name = route[len("/static/"):]
                target = (OVERLAY_DIR / name).resolve()
                if OVERLAY_DIR not in target.parents:
                    return self._json({"error": "not found"}, 404)
                return self._file(target)
            self._json({"error": "not found"}, 404)

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            # Browsers send Origin on cross-site POSTs: only accept the control page itself.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                return self._json({"error": "forbidden"}, 403)
            if url.path == "/api/background-upload":
                try:
                    name = (parse_qs(url.query).get("name") or [""])[0]
                    saved = app.save_upload(name, self.rfile, int(self.headers.get("Content-Length") or 0))
                    slot = (parse_qs(url.query).get("slot") or ["day"])[0]
                    app.control("set_background", slot=slot, name=saved)
                    return self._json({"ok": True, "name": saved})
                except (ControlError, ValueError) as e:
                    self.close_connection = True  # the rest of the body was not read
                    return self._json({"error": str(e)}, 400)
            if url.path != "/api/control":
                return self._json({"error": "not found"}, 404)
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 10_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                action = body.pop("action", "")
                self._json(app.control(action, **body))
            except (ControlError, ValueError, TypeError) as e:
                self._json({"error": str(e)}, 400)

    return Handler


def serve(app: App, host: str, port: int) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), make_handler(app))
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    return httpd
