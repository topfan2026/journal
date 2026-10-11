import json
import urllib.error
import urllib.request

import pytest

from app import App
from chat import DemoChat
from server import serve


@pytest.fixture
def base(settings, profiles, bank, clock, tmp_path):
    (settings.music_root / "study").mkdir(parents=True)
    (settings.music_root / "study" / "rain_lofi.mp3").write_bytes(b"ID3fake")
    (settings.music_root / "secret.txt").write_text("nope")
    app = App(settings, profiles, DemoChat(settings, clock=clock, rate=0), bank, active="study", clock=clock)
    httpd = serve(app, "127.0.0.1", 0)
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def post(url, body, origin=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if origin:
        req.add_header("Origin", origin)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_pages_and_api(base):
    assert b"<canvas" in get(base + "/")[1]
    assert b"Compare niches" in get(base + "/control")[1]
    assert json.loads(get(base + "/api/state")[1])["profile"]["id"] == "study"
    assert len(json.loads(get(base + "/api/profiles")[1])["profiles"]) == 5
    assert json.loads(get(base + "/api/music")[1])["tracks"] == ["rain_lofi.mp3"]
    assert get(base + "/music/rain_lofi.mp3")[1] == b"ID3fake"


@pytest.mark.parametrize("path", ["/music/..%2Fsecret.txt", "/music/../secret.txt", "/static/../app.py",
                                  "/static/%2e%2e/app.py", "/music/secret.txt"])
def test_no_path_traversal(base, path):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(base + path)
    assert e.value.code == 404


def test_control_and_cross_site_block(base):
    assert post(base + "/api/control", {"action": "switch", "profile": "sleep"})[0] == 200
    assert post(base + "/api/control", {"action": "switch", "profile": "study"}, origin="https://evil.example")[0] == 403
    code, body = post(base + "/api/control", {"action": "explode"})
    assert code == 400 and "unknown action" in body["error"]


def test_background_video_supports_range(settings, profiles, bank, clock):
    from dataclasses import replace
    (settings.backgrounds_dir / "loop.webm").write_bytes(bytes(range(256)) * 4)
    profiles = dict(profiles)
    profiles["study"] = replace(profiles["study"], background="loop.webm", background_night="missing.webm")
    app = App(settings, profiles, DemoChat(settings, clock=clock, rate=0), bank, active="study", clock=clock)
    assert app.snapshot()["background"] == {"day": "/backgrounds/loop.webm"}   # missing night file is skipped
    httpd = serve(app, "127.0.0.1", 0)
    try:
        url = f"http://127.0.0.1:{httpd.server_address[1]}/backgrounds/loop.webm"
        req = urllib.request.Request(url, headers={"Range": "bytes=10-19"})
        with urllib.request.urlopen(req) as r:
            assert r.status == 206 and r.headers["Content-Range"] == "bytes 10-19/1024"
            assert r.read() == bytes(range(10, 20))
        assert len(get(url)[1]) == 1024
        with pytest.raises(urllib.error.HTTPError):
            get(url.replace("loop.webm", "..%2F..%2Fapp.py"))
    finally:
        httpd.shutdown()


def test_bad_profile_background_rejected(tmp_path):
    from config import ConfigError, load_profile
    p = tmp_path / "x.json"
    p.write_text('{"name": "X", "background": "../secret.mp4"}')
    with pytest.raises(ConfigError):
        load_profile(p)
    p.write_text('{"name": "X", "effects": ["sparkles"]}')
    with pytest.raises(ConfigError):
        load_profile(p)
