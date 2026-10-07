"""OBS agent's plumbing: launch OBS, switch to your scene, set the stream key, start/stop streaming.

Talks to OBS through its built-in WebSocket server (OBS 28+): in OBS, open
Tools > WebSocket Server Settings, enable it, and copy the password into
OBS_WS_PASSWORD. Build your scene once by hand (a Window Capture of the scanner
browser window, plus webcam/mic if you like) and put its name in OBS_SCENE.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from config import env, env_float

log = logging.getLogger(__name__)


class OBSError(Exception):
    pass


def _client():
    import obsws_python as obs

    return obs.ReqClient(host=env("OBS_WS_HOST", "localhost"), port=int(env_float("OBS_WS_PORT", 4455)),
                         password=env("OBS_WS_PASSWORD", "") or "", timeout=10)


def launch() -> None:
    path = env("OBS_PATH")
    if not path:
        raise OBSError("OBS is not running and OBS_PATH is not set")
    exe = Path(path).expanduser()
    # On Windows OBS must start from its own folder or it can't find its locale files.
    cmd = ["open", "-a", str(exe), "--args"] if exe.suffix == ".app" else [str(exe)]
    cmd += ["--disable-shutdown-check"]
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    subprocess.Popen(cmd, cwd=str(exe.parent), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)


def ws_port_open() -> bool:
    import socket
    try:
        with socket.create_connection((env("OBS_WS_HOST", "localhost"), int(env_float("OBS_WS_PORT", 4455))), 2):
            return True
    except OSError:
        return False


def obs_running() -> bool:
    """Is an OBS process already up (even hidden in the tray)?"""
    name = Path(env("OBS_PATH") or ("obs64.exe" if os.name == "nt" else "obs")).name
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                                 capture_output=True, text=True).stdout
            return name.lower() in out.lower()
        proc = name.removesuffix(".app") if name.endswith(".app") else name
        return subprocess.run(["pgrep", "-x", proc], capture_output=True).returncode == 0
    except OSError:
        return False


def kill() -> None:
    """Force-close a frozen OBS (its WebSocket stopped answering mid-stream)."""
    name = Path(env("OBS_PATH") or ("obs64.exe" if os.name == "nt" else "obs")).name
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)
    else:
        subprocess.run(["pkill", "-x", name.removesuffix(".app")], capture_output=True)


NOT_READY = 207                # obs-websocket: "OBS is not ready to perform the request" (still starting)
CAPTURE_INPUT = "Scanner window"
PRIORITY_TITLE_MUST_MATCH = 1  # OBS win-capture: 0 = same type, 1 = title must match, 2 = same executable
METHOD_WINDOWS_10 = 2          # 0 = automatic, 1 = BitBlt, 2 = Windows 10 (1903 and up)
CHROMIUM_WINDOW_CLASS = "Chrome_WidgetWin_1"


def capture_target(title: str, exe: str, window_class: str = CHROMIUM_WINDOW_CLASS) -> str:
    """OBS's "title:class:exe" window id, with its escaping of '#' and ':'."""
    esc = lambda text: text.replace("#", "#22").replace(":", "#3A")  # noqa: E731
    return f"{esc(title)}:{esc(window_class)}:{esc(exe)}"


def frame_is_black(data_uri: str) -> bool:
    import base64
    import io

    from PIL import Image, ImageStat
    if "," not in data_uri:
        return False
    with Image.open(io.BytesIO(base64.b64decode(data_uri.split(",", 1)[1]))) as img:
        stat = ImageStat.Stat(img.convert("L"))
    # A dark-themed scanner still has text and coloured rows; a missing capture is one flat colour.
    return stat.mean[0] < 8 and stat.stddev[0] < 2


WS_HELP = ("in OBS open Tools > WebSocket Server Settings, tick 'Enable WebSocket server', "
           "port {port}, click Apply")


class OBS:
    def __init__(self, client):
        self.c = client

    @classmethod
    def connect(cls, start: bool = True) -> "OBS":
        port = int(env_float("OBS_WS_PORT", 4455))
        try:
            return cls(_client())
        except Exception as first:
            if ws_port_open():  # OBS answers, so this is a password/auth problem
                raise OBSError(f"OBS WebSocket refused the login ({first}) - check the password "
                               "(OBS: Tools > WebSocket Server Settings > Show Connect Info)") from first
            if not start or obs_running():
                raise OBSError("OBS is running but its WebSocket server is off - "
                               + WS_HELP.format(port=port)) from first
        log.info("obs: not running - launching")
        launch()
        deadline = time.monotonic() + env_float("OBS_START_TIMEOUT", 60)
        last: Exception | None = None
        while time.monotonic() < deadline:
            time.sleep(3)
            try:
                return cls(_client())
            except Exception as e:
                last = e
        raise OBSError(f"OBS started but its WebSocket never answered ({last}) - " + WS_HELP.format(port=port))

    def req(self, name: str, data: dict | None = None, sleep=time.sleep) -> dict:
        """Send a request; while OBS is still loading (code 207 "not ready") wait and retry."""
        deadline = time.monotonic() + env_float("OBS_READY_TIMEOUT", 45)
        while True:
            try:
                return self.c.send(name, data, raw=True) or {}
            except Exception as e:
                if getattr(e, "code", None) != NOT_READY or time.monotonic() > deadline:
                    raise
                sleep(1)

    def version(self) -> str:
        v = self.req("GetVersion")
        return f"OBS {v.get('obsVersion')} / websocket {v.get('obsWebSocketVersion')}"

    def set_scene(self, scene: str) -> None:
        scenes = {x["sceneName"] for x in self.req("GetSceneList").get("scenes", [])}
        if scene not in scenes:
            raise OBSError(f"OBS has no scene named {scene!r} (have: {', '.join(sorted(scenes))})")
        self.req("SetCurrentProgramScene", {"sceneName": scene})

    def current_scene(self) -> str:
        v = self.req("GetCurrentProgramScene")
        return v.get("sceneName") or v.get("currentProgramSceneName") or ""

    def ensure_window_capture(self, scene: str, title: str, exe: str) -> str:
        """Point the scene's Window Capture at the bot's browser window (or add one).

        "Window title must match" plus the bot's fixed window title means OBS can never fall back
        to another window, e.g. the same site open in your everyday browser on another monitor.
        """
        settings = {"window": capture_target(title, exe), "priority": PRIORITY_TITLE_MUST_MATCH,
                    "method": METHOD_WINDOWS_10, "cursor": False}
        items = self.req("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        captures = [i for i in items if i.get("inputKind") == "window_capture"]
        for item in captures:
            self.req("SetInputSettings", {"inputName": item["sourceName"], "inputSettings": settings, "overlay": True})
            if not item.get("sceneItemEnabled", True):
                self.req("SetSceneItemEnabled", {"sceneName": scene, "sceneItemId": item["sceneItemId"],
                                                 "sceneItemEnabled": True})
        for item in items:
            if item.get("inputKind") == "monitor_capture" and item.get("sceneItemEnabled", True):
                log.warning("obs: scene %r also has a Display Capture (%s) - it shows a whole monitor",
                            scene, item["sourceName"])
        if captures:
            return captures[0]["sourceName"]
        inputs = {i["inputName"] for i in self.req("GetInputList").get("inputs", [])}
        if CAPTURE_INPUT in inputs:
            self.req("SetInputSettings", {"inputName": CAPTURE_INPUT, "inputSettings": settings, "overlay": True})
            item_id = self.req("CreateSceneItem", {"sceneName": scene, "sourceName": CAPTURE_INPUT}).get("sceneItemId")
        else:
            item_id = self.req("CreateInput", {"sceneName": scene, "inputName": CAPTURE_INPUT,
                                               "inputKind": "window_capture", "inputSettings": settings,
                                               "sceneItemEnabled": True}).get("sceneItemId")
        if item_id is not None:  # fit it to the canvas
            video = self.req("GetVideoSettings")
            self.req("SetSceneItemTransform", {"sceneName": scene, "sceneItemId": item_id, "sceneItemTransform": {
                "positionX": 0, "positionY": 0, "boundsType": "OBS_BOUNDS_SCALE_INNER",
                "boundsWidth": video.get("baseWidth", 1920), "boundsHeight": video.get("baseHeight", 1080)}})
        log.info("obs: added Window Capture %r to scene %r", CAPTURE_INPUT, scene)
        return CAPTURE_INPUT

    def remove_input(self, name: str) -> bool:
        """Delete a source (e.g. one an older version of the bot added); False if it isn't there."""
        if name not in {i["inputName"] for i in self.req("GetInputList").get("inputs", [])}:
            return False
        self.req("RemoveInput", {"inputName": name})
        return True

    def picture_is_black(self, scene: str) -> bool:
        """True when what OBS sends is a flat black frame (the window isn't being captured)."""
        data = self.req("GetSourceScreenshot", {"sourceName": scene, "imageFormat": "png", "imageWidth": 96})
        return frame_is_black(data.get("imageData", ""))

    def get_stream(self) -> dict:
        """OBS's current stream service settings, to put back after streaming somewhere else."""
        data = self.req("GetStreamServiceSettings")
        return {"type": data.get("streamServiceType", ""), "settings": data.get("streamServiceSettings") or {}}

    def restore_stream(self, saved: dict) -> None:
        if saved.get("type"):
            self.req("SetStreamServiceSettings", {"streamServiceType": saved["type"],
                                                  "streamServiceSettings": saved.get("settings") or {}})

    def set_stream(self, server: str, key: str) -> None:
        self.req("SetStreamServiceSettings", {"streamServiceType": "rtmp_custom",
                                              "streamServiceSettings": {"server": server, "key": key}})

    def streaming(self) -> bool:
        return bool(self.req("GetStreamStatus").get("outputActive"))

    def start(self) -> None:
        if not self.streaming():
            self.req("StartStream")
        deadline = time.monotonic() + 30
        while not self.streaming():
            if time.monotonic() > deadline:
                raise OBSError("OBS did not start streaming - check the OBS log")
            time.sleep(1)

    def stop(self) -> None:
        if self.streaming():
            self.req("StopStream")
