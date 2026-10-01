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

    def req(self, name: str, data: dict | None = None) -> dict:
        return self.c.send(name, data, raw=True) or {}

    def version(self) -> str:
        v = self.req("GetVersion")
        return f"OBS {v.get('obsVersion')} / websocket {v.get('obsWebSocketVersion')}"

    def set_scene(self, scene: str) -> None:
        scenes = {x["sceneName"] for x in self.req("GetSceneList").get("scenes", [])}
        if scene not in scenes:
            raise OBSError(f"OBS has no scene named {scene!r} (have: {', '.join(sorted(scenes))})")
        self.req("SetCurrentProgramScene", {"sceneName": scene})

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
