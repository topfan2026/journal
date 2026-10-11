from datetime import datetime, timezone

import live
import live_status
import screen_live
from obs_control import OBS, pick_monitor

UTC = timezone.utc


def test_pick_monitor_is_one_based():
    items = [{"itemName": "Display 1", "itemValue": "a"}, {"itemName": "Display 2", "itemValue": "b"}]
    assert pick_monitor(items, 1)["itemValue"] == "a"
    assert pick_monitor(items, 2)["itemValue"] == "b"
    assert pick_monitor(items, 3) is None and pick_monitor(items, 0) is None


class FakeClient:
    """Just enough of OBS's WebSocket to follow what ensure_screen_capture asks for."""
    def __init__(self, monitors=True):
        self.scenes, self.inputs, self.calls, self.monitors = ["Daily"], [], [], monitors

    def send(self, name, data=None, raw=False):
        self.calls.append((name, data))
        if name == "GetSceneList":
            return {"scenes": [{"sceneName": s} for s in self.scenes]}
        if name == "CreateScene":
            self.scenes.append(data["sceneName"]); return {}
        if name == "GetSceneItemList":
            return {"sceneItems": []}
        if name == "GetInputList":
            return {"inputs": [{"inputName": n} for n in self.inputs]}
        if name == "CreateInput":
            self.inputs.append(data["inputName"]); return {"sceneItemId": 7}
        if name == "GetInputPropertiesListPropertyItems":
            if not self.monitors:
                raise RuntimeError("no such property")
            return {"propertyItems": [{"itemName": "Display 1: 1920x1080 (Primary)", "itemValue": "id-1"},
                                      {"itemName": "Display 2: 3440x1440", "itemValue": "id-2"}]}
        if name == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        return {}


def settings_of(client):
    return [d for n, d in client.calls if n == "SetInputSettings"][-1]["inputSettings"]


def test_screen_capture_picks_the_numbered_display():
    c = FakeClient()
    label = OBS(c).ensure_screen_capture("AiAlgobot Screen", 1)
    assert "AiAlgobot Screen" in c.scenes and "Screen capture" in c.inputs
    assert settings_of(c)["monitor_id"] == "id-1" and settings_of(c)["monitor"] == 0
    assert "1920x1080" in label
    c2 = FakeClient()
    OBS(c2).ensure_screen_capture("AiAlgobot Screen", 2)
    assert settings_of(c2)["monitor_id"] == "id-2"
    transform = [d for n, d in c.calls if n == "SetSceneItemTransform"][0]["sceneItemTransform"]
    assert (transform["boundsWidth"], transform["boundsHeight"]) == (1920, 1080)


def test_older_obs_without_a_monitor_list_still_works():
    c = FakeClient(monitors=False)
    label = OBS(c).ensure_screen_capture("AiAlgobot Screen", 1)
    assert settings_of(c) == {"monitor": 0, "capture_cursor": True} and label == "monitor 1"


def test_does_not_start_while_the_daily_stream_is_on_air():
    fresh = {"phase": "live", "updated": datetime.now(UTC).isoformat(timespec="seconds")}
    assert screen_live.busy_with_other_show(fresh)
    assert not screen_live.busy_with_other_show({**fresh, "kind": "screen"})
    assert not screen_live.busy_with_other_show({**fresh, "phase": "ended"})
    assert not screen_live.busy_with_other_show({"phase": "live", "updated": "2020-01-01T00:00:00+00:00"})  # old leftover


def test_screen_youtube_uses_its_own_title_and_privacy(monkeypatch):
    monkeypatch.setenv("SCREEN_PRIVACY", "")
    yt = screen_live.ScreenYouTube(None, None, datetime.now(UTC))
    assert yt.final_privacy == "unlisted" and yt.start_privacy == "unlisted"
    monkeypatch.setenv("SCREEN_PRIVACY", "public")
    assert yt.final_privacy == "public"
    assert yt.title_key == "SCREEN_TITLE"


def test_stop_ends_the_screen_stream(settings, monkeypatch):
    show = screen_live.ScreenShow(settings)
    assert not show.stop_requested()
    live.stop(settings)
    assert show.stop_requested()
    import time
    time.sleep(1.1)  # the recorded stop time has whole-second precision
    show2 = screen_live.ScreenShow(settings)  # a stream started after the stop is not affected by it
    show2.session.stop_file.unlink(missing_ok=True)  # (run() clears the old STOP file the same way)
    assert not show2.stop_requested()


def test_dry_run_sets_up_obs_but_never_streams(settings, monkeypatch):
    streamed = []

    class FakeOBS:
        def current_scene(self): return "Daily"
        def ensure_screen_capture(self, scene, monitor): return f"Display {monitor}"
        def set_scene(self, scene): streamed.append(("scene", scene))
        def start(self): streamed.append("START")
        def stop(self): streamed.append("STOP")

    import obs_control
    monkeypatch.setattr(obs_control.OBS, "connect", classmethod(lambda cls, start=True: FakeOBS()))
    monkeypatch.setenv("SCREEN_MONITOR", "1")
    assert screen_live.ScreenShow(settings).run() == 0
    assert "START" not in streamed and ("scene", "AiAlgobot Screen") in streamed and ("scene", "Daily") in streamed
    assert live_status.read(live.live_root(settings)).get("phase") == "tested"
