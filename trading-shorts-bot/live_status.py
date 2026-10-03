"""What the live bot is doing right now, for the app's Status tab.

The scheduler / live show write Live/status.json as they go (phase, each step, live stats);
the app reads it every couple of seconds. History comes from the per-day Live/<date>/session.json.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

STEPS = ("gateway", "scanner", "youtube", "obs", "live")
STEP_LABELS = {"gateway": "IB Gateway (paper)", "scanner": "Scanner", "youtube": "YouTube broadcast",
               "obs": "OBS", "live": "Streaming"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status_path(live_root: Path) -> Path:
    return live_root / "status.json"


def read(live_root: Path) -> dict:
    try:
        return json.loads(status_path(live_root).read_text(encoding="utf-8"))
    except Exception:
        return {}


def write(live_root: Path, **fields) -> dict:
    """Merge fields into status.json (steps are merged one level deeper)."""
    state = read(live_root)
    steps = {**state.get("steps", {}), **fields.pop("steps", {})}
    state.update(fields)
    state.update(steps=steps, updated=_now(), pid=os.getpid())
    path = status_path(live_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"status.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # the status screen is a nicety; never let it break the stream
    return state


def step(live_root: Path, name: str, state: str, detail: str = "") -> None:
    """state: waiting | working | ok | failed | off"""
    write(live_root, steps={name: {"state": state, "detail": detail, "at": _now()}})


def reset_steps(live_root: Path) -> dict:
    return {name: {"state": "waiting", "detail": ""} for name in STEPS}


def age_seconds(state: dict, now: datetime | None = None) -> float | None:
    try:
        updated = datetime.fromisoformat(state["updated"])
    except Exception:
        return None
    return ((now or datetime.now(timezone.utc)) - updated).total_seconds()


def history(live_root: Path, days: int = 7) -> list[dict]:
    """Newest first: one row per day folder with what happened."""
    rows = []
    folders = sorted((p for p in live_root.glob("????-??-??") if p.is_dir()), reverse=True)[:days]
    for folder in folders:
        try:
            s = json.loads((folder / "session.json").read_text(encoding="utf-8"))
        except Exception:
            continue
        live = s.get("live") or {}
        fin = s.get("finished") or {}
        minutes = None
        if live.get("at") and fin.get("at"):
            try:
                minutes = (datetime.fromisoformat(fin["at"]) - datetime.fromisoformat(live["at"])).total_seconds() / 60
            except ValueError:
                pass
        if s.get("stop") and live:
            result = "ended by you"
        elif live and fin.get("ok"):
            result = "streamed"
        elif live:
            result = "streamed, with errors"
        elif s.get("error"):
            result = "failed"
        else:
            result = "test / not live"
        rows.append({
            "date": folder.name,
            "result": result,
            "minutes": minutes,
            "url": live.get("url") or (s.get("youtube") or {}).get("url", ""),
            "error": (s.get("error") or {}).get("error", ""),
            "public": bool((s.get("public") or {}).get("done")),
        })
    return rows
