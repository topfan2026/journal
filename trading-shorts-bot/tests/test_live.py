import json
import os
import stat
import sys
from datetime import datetime, timedelta, timezone

import pytest

import ibkr
import live
import live_gui
import live_status
import youtube_live
from obs_control import OBS, OBSError

UTC = timezone.utc


# --------------------------------------------------------------------------- schedule

def test_next_start_skips_weekend(monkeypatch):
    monkeypatch.setenv("LIVE_START", "06:00")
    monkeypatch.setenv("LIVE_DAYS", "mon-fri")
    fri_after = datetime(2026, 10, 2, 7, 0, tzinfo=UTC)  # Friday, after today's start
    assert live.next_start(fri_after) == datetime(2026, 10, 5, 6, 0, tzinfo=UTC)  # Monday
    fri_before = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    assert live.next_start(fri_before) == datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


def test_live_days_parsing(monkeypatch):
    monkeypatch.setenv("LIVE_DAYS", "fri-mon")
    assert live.live_days() == {4, 5, 6, 0}
    monkeypatch.setenv("LIVE_DAYS", "Mon, Wed,friday")
    assert live.live_days() == {0, 2, 4}


def test_end_time(monkeypatch):
    start = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    monkeypatch.setenv("LIVE_END", "10:30")
    assert live.end_time(start) == start.replace(hour=10, minute=30)
    monkeypatch.delenv("LIVE_END")
    monkeypatch.setenv("LIVE_DURATION_MIN", "90")
    assert live.end_time(start) == start + timedelta(minutes=90)


def test_bad_time_rejected():
    with pytest.raises(live.ConfigError):
        live.parse_hhmm("25:00")


# --------------------------------------------------------------------------- IB Gateway

def test_ibc_ini_is_private_and_paper(tmp_path, monkeypatch):
    monkeypatch.setenv("IB_USERNAME", "paperuser")
    monkeypatch.setenv("IB_PASSWORD", "s3cret")
    ini = ibkr.write_ibc_ini(tmp_path / ".ibc" / "config.ini")
    text = ini.read_text()
    assert "TradingMode=paper" in text and "IbLoginId=paperuser" in text and "IbPassword=s3cret" in text
    if os.name != "nt":
        assert stat.S_IMODE(ini.stat().st_mode) == 0o600


def test_gateway_command(tmp_path, monkeypatch):
    monkeypatch.setenv("IBC_PATH", "/opt/ibc")
    monkeypatch.setenv("TWS_MAJOR_VRSN", "1030")
    cmd = ibkr.gateway_command(tmp_path / "config.ini")
    if os.name != "nt":
        assert cmd[:3] == ["/opt/ibc/scripts/ibcstart.sh", "1030", "--gateway"]
    assert any("paper" in c.lower() for c in cmd)
    monkeypatch.setenv("IBC_START_CMD", "/home/me/gatewaystart.sh -inline")
    assert ibkr.gateway_command(tmp_path / "config.ini") == ["/home/me/gatewaystart.sh", "-inline"]


def test_gateway_already_running(tmp_path, monkeypatch):
    monkeypatch.setattr(ibkr, "port_open", lambda h, p, timeout=1.0: True)
    assert ibkr.start_gateway(tmp_path / "c.ini", tmp_path / "g.log")["started"] is False
    assert not (tmp_path / "c.ini").exists()  # no credentials written when not needed


def test_paper_guard(monkeypatch):
    ibkr.check_paper(["DU1234567"])
    with pytest.raises(ibkr.IBKRError):
        ibkr.check_paper(["U1234567"])
    with pytest.raises(ibkr.IBKRError):
        ibkr.check_paper([])
    monkeypatch.setenv("IB_REQUIRE_PAPER", "false")
    ibkr.check_paper(["U1234567"])


# --------------------------------------------------------------------------- YouTube

class FakeYT:
    """Minimal stand-in for the googleapiclient resource."""

    def __init__(self, lifecycle="ready", stream="inactive"):
        self.lifecycle, self.stream_state, self.calls = lifecycle, stream, []

    def _req(self, result):
        return type("R", (), {"execute": lambda _self: result})()

    def liveBroadcasts(self):
        yt = self

        class B:
            def list(self, **kw):
                return yt._req({"items": [{"status": {"lifeCycleStatus": yt.lifecycle}}]})

            def transition(self, **kw):
                yt.calls.append(("transition", kw["broadcastStatus"]))
                yt.lifecycle = kw["broadcastStatus"]
                return yt._req({})
        return B()

    def liveStreams(self):
        yt = self

        class S:
            def list(self, **kw):
                if "cdn" in kw.get("part", ""):
                    return yt._req({"items": []})
                return yt._req({"items": [{"status": {"streamStatus": yt.stream_state}}]})

            def insert(self, **kw):
                yt.calls.append(("insert_stream", kw["body"]["contentDetails"]["isReusable"]))
                return yt._req({"id": "S1", "cdn": {"ingestionInfo": {
                    "ingestionAddress": "rtmp://a.rtmp.youtube.com/live2", "streamName": "key-123"}}})
        return S()


def test_go_live_transitions_when_stream_active():
    yt = FakeYT(lifecycle="ready", stream="active")
    assert youtube_live.go_live(yt, "B1", "S1", sleep=lambda s: None) == "live"
    assert ("transition", "live") in yt.calls


def test_go_live_uses_auto_start():
    yt = FakeYT(lifecycle="liveStarting")
    assert youtube_live.go_live(yt, "B1", "S1", sleep=lambda s: None) == "liveStarting"
    assert yt.calls == []


def test_ensure_stream_creates_reusable_key(monkeypatch):
    saved = {}
    monkeypatch.setattr(youtube_live, "save_env", lambda k, v: saved.update({k: v}))
    monkeypatch.delenv("YOUTUBE_LIVE_STREAM_ID", raising=False)
    yt = FakeYT()
    s = youtube_live.ensure_stream(yt)
    assert s == {"id": "S1", "server": "rtmp://a.rtmp.youtube.com/live2", "key": "key-123"}
    assert saved == {"YOUTUBE_LIVE_STREAM_ID": "S1"} and ("insert_stream", True) in yt.calls


# --------------------------------------------------------------------------- OBS

class FakeOBSClient:
    def __init__(self):
        self.sent, self.active = [], False

    def send(self, name, data=None, raw=False):
        self.sent.append((name, data))
        if name == "GetSceneList":
            return {"scenes": [{"sceneName": "Scanner"}]}
        if name == "GetStreamStatus":
            return {"outputActive": self.active}
        if name == "StartStream":
            self.active = True
        return None


def test_obs_scene_key_and_start():
    c = FakeOBSClient()
    obs = OBS(c)
    obs.set_scene("Scanner")
    obs.set_stream("rtmp://x/live2", "k")
    obs.start()
    names = [n for n, _ in c.sent]
    assert ("SetCurrentProgramScene", {"sceneName": "Scanner"}) in c.sent
    assert c.sent[names.index("SetStreamServiceSettings")][1]["streamServiceSettings"] == {
        "server": "rtmp://x/live2", "key": "k"}
    assert "StartStream" in names and obs.streaming()
    with pytest.raises(OBSError):
        obs.set_scene("Missing")


# --------------------------------------------------------------------------- orchestrator

@pytest.fixture
def fake_agents(monkeypatch):
    events = []

    class Gateway:
        def __init__(self, s): pass
        def run(self):
            events.append("gateway")
            return {"port": 4002}
        def healthy(self): return True

    class Browser:
        def __init__(self, s): pass
        def run(self):
            events.append("browser")
            return {"url": "https://aialgopro.com"}
        def healthy(self): return True
        def wait(self, seconds): pass
        def close(self): events.append("browser_close")

    class FakeOBS:
        def __init__(self): self.active = False
        def start(self):
            events.append("obs_start")
            self.active = True
        def stop(self): events.append("obs_stop")
        def streaming(self): return self.active

    class OBSAgent:
        def __init__(self): self.obs = None
        def run(self, stream, start_streaming):
            self.obs = FakeOBS()
            events.append(("obs_setup", stream["key"] if stream else None))
            return {"streaming": False}
        def healthy(self): return True

    class YouTube:
        def __init__(self, s, session, start): self.session = session
        def run(self):
            events.append("youtube")
            r = {"broadcast_id": "B1", "url": "https://youtu.be/B1"}
            self.session.set("youtube", r)
            return {**r, "stream": {"id": "S1", "server": "rtmp://x", "key": "K"}}
        def go_live(self, r):
            events.append("go_live")
            return "live"
        def end(self, r): events.append("yt_end")

    monkeypatch.setattr(live, "GatewayAgent", Gateway)
    monkeypatch.setattr(live, "BrowserAgent", Browser)
    monkeypatch.setattr(live, "OBSAgent", OBSAgent)
    monkeypatch.setattr(live, "YouTubeAgent", YouTube)
    return events


def test_live_show_runs_agents_in_order(settings, fake_agents, monkeypatch):
    settings = type(settings).load(root=settings.root, dry_run=False, platforms=settings.platforms)
    monkeypatch.setenv("LIVE_DURATION_MIN", "0")
    monkeypatch.delenv("LIVE_END", raising=False)
    start = datetime.now(live.tz()) - timedelta(seconds=1)
    assert live.LiveShow(settings, start=start).run() == 0
    assert fake_agents == ["gateway", "browser", "youtube", ("obs_setup", "K"), "obs_start", "go_live",
                           "obs_stop", "yt_end", "browser_close"]
    state = json.loads((settings.root / "Live" / start.strftime("%Y-%m-%d") / "session.json").read_text())
    assert state["live"]["url"] == "https://youtu.be/B1" and state["finished"]["ok"] is True


def test_dry_run_never_streams(settings, fake_agents, monkeypatch):
    monkeypatch.setenv("LIVE_CHECK_SECONDS", "0")
    assert live.LiveShow(settings).run() == 0
    assert "youtube" not in fake_agents and "obs_start" not in fake_agents
    assert ("obs_setup", None) in fake_agents


def test_failure_still_shuts_down(settings, fake_agents, monkeypatch):
    settings = type(settings).load(root=settings.root, dry_run=False, platforms=settings.platforms)

    def boom(self, r):
        raise youtube_live.LiveError("no signal")
    monkeypatch.setattr(live.YouTubeAgent, "go_live", boom)
    assert live.LiveShow(settings, start=datetime.now(live.tz())).run() == 1
    assert fake_agents[-3:] == ["obs_stop", "yt_end", "browser_close"]


def test_stop_file_ends_stream(settings, fake_agents, monkeypatch):
    settings = type(settings).load(root=settings.root, dry_run=False, platforms=settings.platforms)
    monkeypatch.setenv("LIVE_DURATION_MIN", "600")
    monkeypatch.setenv("LIVE_CHECK_SECONDS", "0")
    show = live.LiveShow(settings, start=datetime.now(live.tz()))
    orig = show.watch

    def watch(*a, **kw):
        show.session.stop_file.touch()
        return orig(*a, **kw)
    show.watch = watch
    assert show.run() == 0
    assert "yt_end" in fake_agents


def test_single_instance(monkeypatch):
    monkeypatch.setenv("LIVE_LOCK_PORT", "47699")
    lock = live.single_instance()
    try:
        with pytest.raises(live.ConfigError):
            live.single_instance()
    finally:
        lock.close()


# --------------------------------------------------------------------------- GUI helpers

def test_gui_days_round_trip():
    assert live_gui.days_to_list("mon-fri") == ["mon", "tue", "wed", "thu", "fri"]
    assert live_gui.days_to_list("sat-mon") == ["mon", "sat", "sun"]
    assert live_gui.list_to_days(["fri", "mon"]) == "mon,fri"


def test_gui_validate():
    assert live_gui.validate({"LIVE_START": "06:00", "LIVE_DAYS": "mon-fri", "IB_PORT": "4002"}) == []
    problems = live_gui.validate({"LIVE_START": "6am", "LIVE_DAYS": "", "IB_PORT": "x", "LIVE_TZ": "Mars/Base"})
    assert len(problems) == 4


def test_gui_fields_cover_required_settings():
    keys = {f.key for fields in live_gui.TABS.values() for f in fields}
    assert {"LIVE_START", "LIVE_DAYS", "IB_USERNAME", "IB_PASSWORD", "SCANNER_URL", "OBS_PATH",
            "OBS_SCENE", "LIVE_TITLE"} <= keys


def test_gateway_failure_shows_log_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(ibkr, "port_open", lambda h, p, timeout=1.0: False)
    monkeypatch.setenv("IB_USERNAME", "u")
    monkeypatch.setenv("IB_PASSWORD", "p")
    script = tmp_path / "fail.py"
    script.write_text("import sys; print('Error: TWS version 9999 not found'); sys.exit(1)")
    monkeypatch.setenv("IBC_START_CMD", f'"{sys.executable}" "{script}"')
    with pytest.raises(ibkr.IBKRError, match="version 9999 not found"):
        ibkr.start_gateway(tmp_path / "c.ini", tmp_path / "g.log")


def test_obs_not_relaunched_when_already_running(monkeypatch):
    import obs_control

    def refuse():
        raise ConnectionRefusedError("refused")
    launched = []
    monkeypatch.setattr(obs_control, "_client", refuse)
    monkeypatch.setattr(obs_control, "ws_port_open", lambda: False)
    monkeypatch.setattr(obs_control, "obs_running", lambda: True)
    monkeypatch.setattr(obs_control, "launch", lambda: launched.append(1))
    with pytest.raises(OBSError, match="WebSocket server is off"):
        OBS.connect(start=True)
    assert launched == []
    monkeypatch.setattr(obs_control, "ws_port_open", lambda: True)
    with pytest.raises(OBSError, match="password"):
        OBS.connect(start=True)
    assert launched == []


def test_scanner_steps_parse():
    import scanner_site
    steps = scanner_site.parse_steps(scanner_site.DEFAULT_STEPS)
    assert steps[0] == ("goto", "https://aialgopro.com")
    assert ("click", "Gateway Paper") in steps and ("wait", "Connected") in steps
    assert scanner_site.parse_steps("# note\n\n  CLICK  Wall Scan \n") == [("click", "Wall Scan")]
    with pytest.raises(scanner_site.SiteError, match="line 2"):
        scanner_site.parse_steps("click A\njump B\n")
    with pytest.raises(scanner_site.SiteError, match="needs something"):
        scanner_site.parse_steps("click\n")


def test_whole_word_matching():
    import scanner_site
    assert not scanner_site.whole_words("Connected").search("Disconnected")
    assert scanner_site.whole_words("Connected").search("Status: connected")
    assert not scanner_site.whole_words("Connect").search("Connection")
    assert scanner_site.whole_words("Wall Scan").search("Run Wall Scan now")


def test_type_step_and_secret_expansion(monkeypatch):
    import scanner_site
    steps = scanner_site.parse_steps("type Local connector secret = {SCANNER_SECRET}\n")
    assert steps == [("type", "Local connector secret = {SCANNER_SECRET}")]
    with pytest.raises(scanner_site.SiteError, match="type <box name> = <text>"):
        scanner_site.parse_steps("type just a box\n")
    monkeypatch.setenv("SCANNER_SECRET", "abc123")
    assert scanner_site.expand("{SCANNER_SECRET}") == "abc123"
    monkeypatch.delenv("SCANNER_SECRET")
    with pytest.raises(scanner_site.SiteError, match="not set"):
        scanner_site.expand("{SCANNER_SECRET}")


def test_wait_ignores_negated_status():
    import scanner_site
    p = scanner_site.whole_words("Connected", negatable=True)
    assert not p.search("Not connected") and not p.search("Not Connected - check secret")
    assert p.search("Connected") and p.search("Status: connected")


def test_type_values_hidden_in_logs():
    import scanner_site
    assert scanner_site.shown("type", "Local connector secret = abc+123") == "type Local connector secret = ******"
    assert scanner_site.shown("click", "Scan Market") == "click Scan Market"


def test_gui_browser_jobs_are_exclusive():
    assert live_gui.uses_browser(("live.py", "site-test")) and live_gui.uses_browser(("live.py", "daemon"))
    assert not live_gui.uses_browser(("live.py", "stop")) and not live_gui.uses_browser(("auth_setup.py", "youtube"))


def test_if_end_blocks():
    import scanner_site
    steps = scanner_site.parse_steps(scanner_site.DEFAULT_STEPS)
    i = steps.index(("if", "Gateway Paper"))
    end = scanner_site.skip_block(steps, i)
    assert steps[end] == ("end", "") and steps[end + 1:] == [
        ("if", "Private IBKR Gateway setup"), ("key", "Escape"), ("end", ""),
        ("if", "Private IBKR Gateway setup"), ("click", "Close"), ("end", ""),
        ("select", "Stream Mode"), ("wait", "5"), ("select", "YouTube"),
        ("wait", "10"), ("click", "Full screen"), ("hide", "A row is tinted")]
    with pytest.raises(scanner_site.SiteError, match="missing its 'end'"):
        scanner_site.parse_steps("if A\nclick B\n")
    with pytest.raises(scanner_site.SiteError, match="without an 'if'"):
        scanner_site.parse_steps("click B\nend\n")


def test_fullscreen_step_parses_without_argument():
    import scanner_site
    assert scanner_site.parse_steps("fullscreen\nfullscreen off\n") == [("fullscreen", "on"), ("fullscreen", "off")]


def test_gateway_login_retries_until_ready(monkeypatch):
    attempts = []

    class FakeIB:
        def managedAccounts(self):
            return ["DU617561"]

        def disconnect(self):
            attempts.append("disconnect")

    def connect():
        attempts.append("try")
        if attempts.count("try") < 3:
            raise ConnectionRefusedError("refused")
        return FakeIB()
    monkeypatch.setattr(ibkr, "connect", connect)
    assert live.GatewayAgent.verify_login(sleep=lambda s: None) == ["DU617561"]
    assert attempts == ["try", "try", "try", "disconnect"]

    def live_account():
        raise ibkr.IBKRError("not a paper account")
    monkeypatch.setattr(ibkr, "connect", live_account)
    with pytest.raises(ibkr.IBKRError, match="paper"):
        live.GatewayAgent.verify_login(sleep=lambda s: None)  # never retried


def test_frozen_obs_is_force_restarted(monkeypatch):
    import obs_control
    calls = []
    agent = live.OBSAgent()

    def run(stream, start_streaming):
        calls.append("run")
        if calls.count("run") == 1:
            raise obs_control.OBSError("OBS is running but its WebSocket server is off")
        return {"streaming": True}
    monkeypatch.setattr(agent, "run", run)
    monkeypatch.setattr(obs_control, "obs_running", lambda: True)
    monkeypatch.setattr(obs_control, "kill", lambda: calls.append("kill"))
    assert agent.recover(sleep=lambda s: None) == {"streaming": True}
    assert calls == ["run", "kill", "run"]

    calls.clear()
    monkeypatch.setattr(obs_control, "obs_running", lambda: False)  # not frozen, just gone: no kill
    monkeypatch.setattr(agent, "run", lambda *a, **k: (_ for _ in ()).throw(obs_control.OBSError("x")))
    with pytest.raises(obs_control.OBSError):
        agent.recover(sleep=lambda s: None)
    assert calls == []


def _png_data_uri(img):
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def test_black_frame_detection():
    from PIL import Image, ImageDraw
    import obs_control
    assert obs_control.frame_is_black(_png_data_uri(Image.new("RGB", (96, 54), (0, 0, 0))))
    dark_ui = Image.new("RGB", (96, 54), (11, 15, 23))  # the scanner's dark theme, with rows of text
    d = ImageDraw.Draw(dark_ui)
    for y in range(4, 54, 6):
        d.rectangle([2, y, 90, y + 2], fill=(34, 197, 94) if y % 12 else (239, 68, 68))
    assert not obs_control.frame_is_black(_png_data_uri(dark_ui))
    assert not obs_control.frame_is_black("")


def test_capture_target_escaping():
    import obs_control
    assert obs_control.capture_target("LIVE BOT - Scanner", "chrome.exe") == "LIVE BOT - Scanner:Chrome_WidgetWin_1:chrome.exe"
    assert obs_control.capture_target("a:b#c", "x.exe").startswith("a#3Ab#22c:")


class CaptureClient:
    def __init__(self, items, inputs=()):
        self.items, self.inputs, self.sent = items, list(inputs), []

    def send(self, name, data=None, raw=False):
        self.sent.append((name, data))
        if name == "GetSceneItemList":
            return {"sceneItems": self.items}
        if name == "GetInputList":
            return {"inputs": [{"inputName": n} for n in self.inputs]}
        if name in ("CreateInput", "CreateSceneItem"):
            return {"sceneItemId": 7}
        if name == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        return None


def test_window_capture_is_repointed_or_created():
    import obs_control
    c = CaptureClient([{"sourceName": "Window Capture", "inputKind": "window_capture", "sceneItemId": 3,
                        "sceneItemEnabled": False}])
    obs_control.OBS(c).ensure_window_capture("Scanner", "LIVE BOT - Scanner", "chrome.exe")
    settings = next(d for n, d in c.sent if n == "SetInputSettings")
    assert settings["inputName"] == "Window Capture"
    assert settings["inputSettings"]["window"] == "LIVE BOT - Scanner:Chrome_WidgetWin_1:chrome.exe"
    assert settings["inputSettings"]["priority"] == 1 and settings["inputSettings"]["method"] == 2
    assert ("SetSceneItemEnabled", {"sceneName": "Scanner", "sceneItemId": 3, "sceneItemEnabled": True}) in c.sent

    c = CaptureClient([])  # scene without a capture: one is created and fitted to the canvas
    obs_control.OBS(c).ensure_window_capture("Scanner", "LIVE BOT - Scanner", "chrome.exe")
    names = [n for n, _ in c.sent]
    assert "CreateInput" in names and "SetSceneItemTransform" in names


def test_black_picture_escalation():
    events = []

    class Browser:
        def restore(self): events.append("restore")
        def close(self): events.append("close")
        def run(self): events.append("reload")

    class FakeOBS:
        def ensure_window_capture(self, *a): events.append("repoint")

    class Agent:
        obs, scene, black = FakeOBS(), "Scanner", 0
        def picture_black(self): return True

    agent = Agent()
    for _ in range(4):
        live.LiveShow.check_picture(Browser(), agent)
    assert events == ["repoint", "restore", "close", "reload"] and agent.black == 0
    agent.picture_black = lambda: False
    agent.black = 3
    live.LiveShow.check_picture(Browser(), agent)
    assert agent.black == 0


def test_goes_public_only_after_healthy_minutes(tmp_path, monkeypatch):
    calls = []
    health = {"value": ("active", "good")}
    monkeypatch.setattr(youtube_live, "stream_health", lambda yt, sid: health["value"])
    monkeypatch.setattr(youtube_live, "set_privacy", lambda yt, bid, p: calls.append((bid, p)))
    monkeypatch.setenv("LIVE_PUBLIC_AFTER_MIN", "3")
    monkeypatch.setenv("LIVE_PRIVACY", "public")
    monkeypatch.setenv("LIVE_START_PRIVACY", "unlisted")
    session = live.Session(tmp_path / "day")
    agent = live.YouTubeAgent(None, session, datetime.now(UTC))
    agent.yt = object()
    assert agent.start_privacy == "unlisted"
    result = {"broadcast_id": "B1", "stream": {"id": "S1"}, "url": "u"}

    assert not agent.check_go_public(result, True, now=0)        # healthy: clock starts
    assert not agent.check_go_public(result, False, now=100)     # black picture: clock resets
    assert not agent.check_go_public(result, True, now=120)
    health["value"] = ("active", "noData")
    assert not agent.check_go_public(result, True, now=200)      # YouTube not receiving: resets
    health["value"] = ("active", "good")
    assert not agent.check_go_public(result, True, now=300)
    assert not agent.check_go_public(result, True, now=300 + 179)
    assert agent.check_go_public(result, True, now=300 + 180)    # 3 healthy minutes
    assert calls == [("B1", "public")]
    assert not agent.check_go_public(result, True, now=1000)     # once only
    assert calls == [("B1", "public")] and session.get("public")["done"]

    monkeypatch.setenv("LIVE_PUBLIC_AFTER_MIN", "0")
    assert live.YouTubeAgent(None, live.Session(tmp_path / "d2"), datetime.now(UTC)).start_privacy == "public"


def test_os_window_title_has_browser_suffix(monkeypatch):
    import scanner_site
    monkeypatch.delenv("BROWSER_PATH", raising=False)
    monkeypatch.setenv("BROWSER_CHANNEL", "chrome")
    assert scanner_site.os_window_title() == "LIVE BOT - Scanner - Google Chrome"
    monkeypatch.setenv("BROWSER_CHANNEL", "msedge")
    assert scanner_site.os_window_title() == "LIVE BOT - Scanner - Microsoft​ Edge"


def test_late_manual_start_does_not_run_until_tomorrow(monkeypatch):
    monkeypatch.setenv("LIVE_END", "10:00")
    monkeypatch.setenv("LIVE_DURATION_MIN", "60")
    late = datetime(2026, 10, 1, 10, 25, tzinfo=UTC)
    assert live.end_time(late) == late + timedelta(minutes=60)
    early = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
    assert live.end_time(early) == early.replace(hour=10)


def test_scheduler_running_detects_the_lock(monkeypatch):
    monkeypatch.setenv("LIVE_LOCK_PORT", "47698")
    assert not live.scheduler_running()
    lock = live.single_instance()
    try:
        assert live.scheduler_running()
    finally:
        lock.close()


def test_windows_startup_launcher(tmp_path, monkeypatch):
    import autostart
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert autostart.startup_file() == tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "LiveStreamBot.cmd"
    cmd = autostart.windows_startup_cmd(tmp_path / "live_daemon.bat")
    assert cmd.startswith("@echo off") and '/min "' in cmd and "live_daemon.bat" in cmd


def test_background_scheduler_can_be_stopped(settings, monkeypatch):
    monkeypatch.setenv("LIVE_LOCK_PORT", "47696")
    monkeypatch.setenv("LIVE_START", "06:00")
    monkeypatch.setenv("LIVE_DAYS", "mon-sun")
    stop_file = live.scheduler_stop_file(settings)
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    started = []
    monkeypatch.setattr(live, "LiveShow", lambda *a, **k: started.append(1))
    # the first wait sees the stop request (as if the app's Stop button was pressed meanwhile)
    monkeypatch.setattr(live.time, "sleep", lambda s: stop_file.touch())
    monkeypatch.setattr(live, "next_start", lambda now: now + timedelta(hours=5))
    assert live.daemon(settings) == 0
    assert not stop_file.exists() and started == []


def test_running_scheduler_picks_up_new_time(settings, monkeypatch, tmp_path):
    import config
    env_file = tmp_path / ".env"
    env_file.write_text("LIVE_START=06:00\n")
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setenv("LIVE_LOCK_PORT", "47695")
    monkeypatch.setenv("LIVE_START", "06:00")
    monkeypatch.setenv("LIVE_DAYS", "mon-sun")
    monkeypatch.setenv("LIVE_PREP_MIN", "10")
    seen, sleeps = [], []
    live.scheduler_stop_file(settings).parent.mkdir(parents=True, exist_ok=True)
    fixed_now = datetime(2026, 10, 1, 22, 0, tzinfo=UTC)
    monkeypatch.setattr(live, "tz", lambda: UTC)
    monkeypatch.setattr(live, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: fixed_now)}))

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 1:
            env_file.write_text("LIVE_START=06:15\n")  # changed in the app while waiting
        else:
            live.scheduler_stop_file(settings).touch()
    monkeypatch.setattr(live.time, "sleep", fake_sleep)
    monkeypatch.setattr(live.log, "info", lambda msg, *a: seen.append(msg % a if a else msg))
    assert live.daemon(settings) == 0
    assert any("schedule changed - next stream Fri 2026-10-02 06:15" in m for m in seen)


def test_tiktok_studio_find_and_messages(tmp_path, monkeypatch):
    import tiktok_studio
    app_dir = tmp_path / "Programs" / "TikTok LIVE Studio"
    app_dir.mkdir(parents=True)
    (app_dir / "Uninstall TikTok LIVE Studio.exe").write_text("")
    (app_dir / "TikTok LIVE Studio.exe").write_text("")
    for key in ("ProgramFiles", "ProgramFiles(x86)", "APPDATA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert tiktok_studio.find_exe() == app_dir / "TikTok LIVE Studio.exe"
    monkeypatch.delenv("TIKTOK_STUDIO_PATH", raising=False)
    assert "not set" in tiktok_studio.open_studio()
    monkeypatch.setenv("TIKTOK_STUDIO_PATH", str(tmp_path / "missing.exe"))
    assert "not found" in tiktok_studio.open_studio()


def test_tiktok_off_by_default(monkeypatch):
    import tiktok_studio
    monkeypatch.delenv("TIKTOK_STUDIO", raising=False)
    opened = []
    monkeypatch.setattr(tiktok_studio, "open_studio", lambda: opened.append(1) or "x")
    live.LiveShow.start_tiktok()
    assert opened == []
    monkeypatch.setenv("TIKTOK_STUDIO", "true")
    monkeypatch.setattr(tiktok_studio, "remind", lambda *a: opened.append("remind"))
    live.LiveShow.start_tiktok()
    assert opened == [1, "remind"]


def test_obs_waits_while_loading():
    from obsws_python.error import OBSSDKRequestError
    import obs_control

    class Loading:
        def __init__(self): self.calls = 0
        def send(self, name, data=None, raw=False):
            self.calls += 1
            if self.calls < 3:
                raise OBSSDKRequestError(name, 207, "OBS is not ready to perform the request.")
            return {"scenes": [{"sceneName": "Scanner"}]}
    c = Loading()
    assert obs_control.OBS(c).req("GetSceneList", sleep=lambda s: None)["scenes"]
    assert c.calls == 3

    class Broken:
        def send(self, name, data=None, raw=False):
            raise OBSSDKRequestError(name, 600, "No source")
    with pytest.raises(OBSSDKRequestError):
        obs_control.OBS(Broken()).req("GetSceneList", sleep=lambda s: None)


def test_leftover_bot_browser_is_closed(tmp_path):
    import subprocess as sp
    import time as _t
    import scanner_site
    if os.name == "nt":
        pytest.skip("posix process check")
    profile = tmp_path / "browser-profile"
    profile.mkdir()
    proc = sp.Popen(["sleep", "30", f"--user-data-dir={profile.resolve()}"]) if False else \
        sp.Popen([sys.executable, "-c", "import time; time.sleep(30)", f"--user-data-dir={profile.resolve()}"])
    _t.sleep(0.3)
    assert scanner_site.close_stale_browsers(profile) == 1
    assert proc.wait(timeout=5) != 0
    assert scanner_site.close_stale_browsers(profile) == 0


def test_power_flags(monkeypatch):
    import power
    seen = []
    monkeypatch.setattr(power, "_set", lambda flags: seen.append(flags) or True)
    power.stay_awake()
    power.stay_awake(screen_on=True)
    power.allow_screen_off()
    assert seen == [0x80000001, 0x80000003, 0x80000001]


def test_website_and_app_have_separate_steps(tmp_path, monkeypatch):
    import scanner_site
    monkeypatch.delenv("SCANNER_STEPS_FILE", raising=False)
    monkeypatch.delenv("SCANNER_APP_STEPS_FILE", raising=False)
    monkeypatch.setenv("SCANNER_APP", str(tmp_path / "Farhad AI Scanner.exe"))
    monkeypatch.setenv("SCANNER_SOURCE", "website")
    assert scanner_site.steps_file().name == "scanner_steps.txt" and scanner_site.app_path() is None
    assert "aialgopro" in scanner_site.default_steps()
    monkeypatch.setenv("SCANNER_SOURCE", "app")
    assert scanner_site.steps_file().name == "scanner_steps_app.txt"
    assert scanner_site.app_path().name == "Farhad AI Scanner.exe"
    assert scanner_site.browser_exe() == "Farhad AI Scanner.exe"
    assert scanner_site.os_window_title() == "LIVE BOT - Scanner"  # Electron: no browser suffix
    assert scanner_site.parse_steps(scanner_site.default_steps())[1] == ("ifnot", "◧")


def test_click_at_point_and_app_default_steps():
    import scanner_site
    assert scanner_site.AT_POINT.match("at 16,14").groups() == ("16", "14")
    assert scanner_site.AT_POINT.match("AT 5 , 9")
    assert not scanner_site.AT_POINT.match("Attach file")
    steps = scanner_site.parse_steps(scanner_site.DEFAULT_APP_STEPS)
    assert ("click", "◧") in steps and ("if", "DISCONNECTED") in steps and ("ifnot", "◧") in steps
    assert ("type", "Port = 4002") in steps and ("click", "Clean view") in steps


def test_ifnot_block_parses_and_skips():
    import scanner_site
    steps = scanner_site.parse_steps("ifnot Terminal / Connection\n  click Scanner\nend\nclick Terminal / Connection\n")
    assert steps[0] == ("ifnot", "Terminal / Connection")
    assert scanner_site.skip_block(steps, 0) == 2
    assert ("ifnot", "Terminal / Connection") in scanner_site.parse_steps(scanner_site.DEFAULT_APP_STEPS)


def test_maximize_step_parses():
    import scanner_site
    assert scanner_site.parse_steps("maximize\n") == [("maximize", "window")]


def test_missed_show_catch_up(settings, monkeypatch):
    monkeypatch.setenv("LIVE_START", "06:15")
    monkeypatch.setenv("LIVE_END", "10:00")
    monkeypatch.setenv("LIVE_DAYS", "mon-fri")
    monkeypatch.delenv("LIVE_CATCH_UP", raising=False)
    mon = lambda h, m: datetime(2026, 10, 5, h, m, tzinfo=UTC)  # a Monday
    assert live.missed_show(settings, mon(6, 0)) is None             # not started yet: normal schedule
    assert live.missed_show(settings, mon(6, 40)) == mon(6, 15)      # PC came on late: go now
    assert live.missed_show(settings, mon(9, 55)) is None            # under 10 min left: skip
    assert live.missed_show(settings, mon(10, 30)) is None           # after the end time
    assert live.missed_show(settings, datetime(2026, 10, 4, 7, 0, tzinfo=UTC)) is None  # Sunday
    day = live.Session(live.live_root(settings) / "2026-10-05")
    day.set("finished", {"ok": False})
    assert live.missed_show(settings, mon(6, 40)) == mon(6, 15)      # a failed run is retried
    day.set("finished", {"ok": True})
    assert live.missed_show(settings, mon(7, 0)) is None             # already streamed today
    monkeypatch.setenv("LIVE_CATCH_UP", "false")
    assert live.missed_show(settings, mon(6, 40)) is None


def test_wake_task_xml_and_days():
    from datetime import datetime, timezone, timedelta
    import wake
    pt = timezone(timedelta(hours=-7))
    start = datetime(2026, 10, 5, 6, 15, tzinfo=pt)  # Monday
    at, days = wake.wake_plan(start.astimezone(), 10, {0, 1, 2, 3, 4})
    assert at == start - timedelta(minutes=20)
    xml = wake.task_xml(at, days)
    assert "<WakeToRun>true</WakeToRun>" in xml
    assert "<Monday />" in xml and "<Friday />" in xml and "<Saturday />" not in xml
    assert "power.py&quot; hold" in xml or 'power.py" hold' in xml


def test_wake_before_midnight_moves_days_back():
    from datetime import datetime, timedelta
    import wake
    start = datetime(2026, 10, 5, 0, 5).astimezone()  # Monday 00:05 local
    at, days = wake.wake_plan(start, 10, {0, 4})
    assert at.weekday() == 6 and days == {6, 3}


def test_end_today_is_final_for_scheduled_retries(settings, fake_agents, monkeypatch):
    """End today's stream must stop the scheduler's retries; Go live now still works afterwards."""
    settings = type(settings).load(root=settings.root, dry_run=False, platforms=settings.platforms)
    monkeypatch.setenv("LIVE_DURATION_MIN", "600")
    monkeypatch.delenv("LIVE_END", raising=False)
    runs = []

    def boom(self, r):
        runs.append(1)
        live.stop(settings)  # you press End today's stream while it is failing
        raise youtube_live.LiveError("no signal")
    monkeypatch.setattr(live.YouTubeAgent, "go_live", boom)
    start = datetime.now(live.tz())
    assert live.run_show(settings, start, armed=start - timedelta(minutes=10), sleep=lambda s: None) == 0
    assert len(runs) == 1                                   # not retried
    assert live.LiveShow(settings, start=start, armed=start - timedelta(minutes=10)).run() == 0
    assert len(runs) == 1                                   # a scheduled re-run today won't start it
    status = live_status.read(live.live_root(settings))
    assert status["phase"] in ("ended", "failed")


def test_retry_after_failure_without_stop(settings, fake_agents, monkeypatch):
    settings = type(settings).load(root=settings.root, dry_run=False, platforms=settings.platforms)
    monkeypatch.setenv("LIVE_DURATION_MIN", "600")
    monkeypatch.setenv("LIVE_RETRY_SECONDS", "0.01")
    monkeypatch.setenv("LIVE_CHECK_SECONDS", "0")
    monkeypatch.delenv("LIVE_END", raising=False)
    calls = []

    def flaky(self, r):
        calls.append(1)
        if len(calls) == 1:
            raise youtube_live.LiveError("no signal")
        live.stop(settings)  # second try works; then you end it
        return "live"
    monkeypatch.setattr(live.YouTubeAgent, "go_live", flaky)
    start = datetime.now(live.tz())
    assert live.run_show(settings, start, armed=start - timedelta(minutes=10), sleep=lambda s: None) == 0
    assert len(calls) == 2


def test_stop_before_this_show_does_not_block_it():
    from datetime import timezone
    state = {"stop": {"by": "you", "at": "2026-10-02T01:50:00+00:00"}}
    assert live.stopped_since(state, datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc))
    assert not live.stopped_since(state, datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc))
    assert not live.stopped_since({}, datetime(2026, 10, 2, 3, 0, tzinfo=timezone.utc))


def test_status_file_and_history(tmp_path):
    live_status.write(tmp_path, phase="setup", steps=live_status.reset_steps(tmp_path))
    live_status.step(tmp_path, "gateway", "ok", "logged in: DU1")
    st = live_status.read(tmp_path)
    assert st["phase"] == "setup" and st["steps"]["gateway"]["state"] == "ok"
    assert st["steps"]["obs"]["state"] == "waiting"
    day = live.Session(tmp_path / "2026-10-02")
    day.set("live", {"url": "https://youtu.be/x"})
    day.set("stop", {"by": "you"})
    day.set("finished", {"ok": True})
    rows = live_status.history(tmp_path)
    assert rows[0]["date"] == "2026-10-02" and rows[0]["result"] == "ended by you"


def test_local_connector_starts_missing_helpers(monkeypatch):
    import local_connector
    started, up = [], {"port": False}
    monkeypatch.setenv("SCANNER_CONNECTOR_CMD", "python connector.py")
    monkeypatch.setenv("SCANNER_TUNNEL_CMD", "cloudflared tunnel run ibkr")
    monkeypatch.setattr(local_connector, "connector_up", lambda: up["port"])
    monkeypatch.setattr(local_connector, "tunnel_up", lambda cmd: False)

    def start(cmd, title):
        started.append(cmd)
        up["port"] = True
    monkeypatch.setattr(local_connector, "_start", start)
    msg = local_connector.ensure(sleep=lambda s: None)
    assert started == ["python connector.py", "cloudflared tunnel run ibkr"]
    assert "connector started" in msg and "tunnel started" in msg
    monkeypatch.delenv("SCANNER_CONNECTOR_CMD")
    monkeypatch.delenv("SCANNER_TUNNEL_CMD")
    assert not local_connector.enabled()


def test_daemon_does_not_replan_a_finished_show(settings, monkeypatch):
    """After today's show is done/ended, the scheduler waits for the next one instead of looping on it."""
    now = datetime.now(live.tz())
    start = now + timedelta(minutes=3)  # setup time (10 min early) has already passed
    monkeypatch.setenv("LIVE_START", start.strftime("%H:%M"))
    monkeypatch.setenv("LIVE_DAYS", "mon-sun")
    monkeypatch.setenv("LIVE_PREP_MIN", "10")
    monkeypatch.setenv("LIVE_LOCK_PORT", "47698")
    monkeypatch.setattr(live, "reload_env", lambda: None)
    calls = []

    def fake_run_show(settings, start, armed, scheduler_stop=None):
        calls.append(start)
        if len(calls) > 3:
            raise AssertionError("re-planned the same show")
        return 0
    monkeypatch.setattr(live, "run_show", fake_run_show)
    stop_file = live.scheduler_stop_file(settings)
    monkeypatch.setattr(live.time, "sleep", lambda s: stop_file.touch())  # first wait: ask it to stop
    assert live.daemon(settings) == 0
    assert len(calls) == 1


def test_streams_start_public_by_default(tmp_path, monkeypatch):
    """YouTube only notifies subscribers for a stream that starts public."""
    monkeypatch.delenv("LIVE_START_PRIVACY", raising=False)
    monkeypatch.setenv("LIVE_PRIVACY", "public")
    monkeypatch.setenv("LIVE_PUBLIC_AFTER_MIN", "3")
    agent = live.YouTubeAgent(None, live.Session(tmp_path / "d"), datetime.now(UTC))
    assert agent.start_privacy == "public"
    assert agent.check_go_public({"broadcast_id": "B", "stream": {"id": "S"}}, True, now=0) is False  # nothing to switch
