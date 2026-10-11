"""Local web server: the overlay (OBS Browser Source), the control page, music files and a JSON API.

    /                  the overlay, 1920x1080
    /control           switch niche, start/stop trivia, send test chat messages, compare niches
    /api/state         everything the overlay draws
    /api/profiles      the niches and which one is on air
    /api/stats?days=7  per-niche comparison
    /api/music         the active niche's tracks
    /music/<file>      a track
    POST /api/control  {"action": "switch" | "trivia_start" | "trivia_stop" | "clear_tasks" | "test_message", ...}

It listens on 127.0.0.1 only: the control page has no password, so don't expose the port.
"""
from __future__ import annotations

import json
import logging
import mimetypes
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
            if route == "/api/music":
                return self._json({"profile": app.active, "tracks": app.music()})
            if route.startswith("/music/"):
                name = unquote(route[len("/music/"):])
                if "/" in name or "\\" in name or name.startswith(".") or name not in app.music():
                    return self._json({"error": "not found"}, 404)
                return self._file(app.profile.music_path(app.s) / name, cache=True)
            if route.startswith("/static/"):
                name = route[len("/static/"):]
                target = (OVERLAY_DIR / name).resolve()
                if OVERLAY_DIR not in target.parents:
                    return self._json({"error": "not found"}, 404)
                return self._file(target)
            self._json({"error": "not found"}, 404)

        def do_POST(self):  # noqa: N802
            if urlparse(self.path).path != "/api/control":
                return self._json({"error": "not found"}, 404)
            # Browsers send Origin on cross-site POSTs: only accept the control page itself.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
                return self._json({"error": "forbidden"}, 403)
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
