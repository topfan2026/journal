"""Job discovery in Ready/, claiming into Processing/, and per-job state.

A *job* is one short video.

Two ways to drop a job into Ready/:

  Ready/<any-name>/            (recommended, one folder per video)
      clip1.mp4 ... clip6.mp4  one finished 60s mp4, or several clips to stitch
      caption.txt              optional, the spoken script / caption text
      meta.json                optional, subject, title, tags, overrides
      subject.txt              optional, used if meta.json has no "subject"
      thumbnail.jpg|png        optional custom YouTube thumbnail

  Ready/ (loose files)         mp4(s) + caption.txt and/or meta.json dropped
                               straight into Ready/ become a single job.

A job counts as ready when it has at least one mp4 plus at least one of
caption.txt, meta.json or subject.txt, it contains no in-progress download
(.crdownload, .part, ...), and no file has changed for STABLE_SECONDS.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

VIDEO_EXTS = {".mp4", ".mov", ".m4v"}
TEXT_FILES = ("meta.json", "caption.txt", "subject.txt")
THUMB_NAMES = ("thumbnail.jpg", "thumbnail.jpeg", "thumbnail.png")
PARTIAL_SUFFIXES = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")
STATE_FILE = "job.json"
OUT_DIR = "_out"


class JobError(Exception):
    """The job's input files are unusable, so it cannot proceed."""


def _hidden(p: Path) -> bool:
    return p.name.startswith((".", "~", "_"))


def _partial(p: Path) -> bool:
    return p.name.lower().endswith(PARTIAL_SUFFIXES)


def natural_key(p: Path):
    """Sort clip2 before clip10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]


@dataclass
class Candidate:
    name: str
    files: list[Path]
    folder: Path | None  # set when the job is a sub-folder of Ready/

    @property
    def key(self) -> str:
        return str(self.folder) if self.folder else "<loose>"

    def signature(self) -> tuple:
        sig = []
        for p in sorted(self.files):
            try:
                st = p.stat()
            except FileNotFoundError:
                return ("missing", str(p))
            sig.append((str(p), st.st_size, st.st_mtime_ns))
        return tuple(sig)


def _collect(folder: Path) -> tuple[list[Path], bool]:
    """Return (job files, has_partial_download) for the top level of *folder*."""
    files, partial = [], False
    for p in folder.iterdir():
        if not p.is_file() or _hidden(p):
            continue
        if _partial(p):
            partial = True
            continue
        if p.suffix.lower() in VIDEO_EXTS or p.name.lower() in TEXT_FILES + THUMB_NAMES:
            files.append(p)
    return files, partial


def _is_job(files: list[Path]) -> bool:
    names = {p.name.lower() for p in files}
    has_video = any(p.suffix.lower() in VIDEO_EXTS for p in files)
    return has_video and any(n in names for n in TEXT_FILES)


def discover(ready: Path) -> list[Candidate]:
    if not ready.is_dir():
        return []
    found: list[Candidate] = []
    for d in sorted(p for p in ready.iterdir() if p.is_dir() and not _hidden(p)):
        files, partial = _collect(d)
        if not partial and _is_job(files):
            found.append(Candidate(d.name, files, d))
    files, partial = _collect(ready)
    if not partial and _is_job(files):
        video = min((p for p in files if p.suffix.lower() in VIDEO_EXTS), key=natural_key)
        found.append(Candidate(video.stem, files, None))
    return found


class StabilityTracker:
    """A job is stable once its files have been unchanged for *seconds*."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        self._seen: dict[str, tuple[tuple, float]] = {}

    def is_stable(self, cand: Candidate, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        sig = cand.signature()
        prev = self._seen.get(cand.key)
        if prev is None or prev[0] != sig:
            self._seen[cand.key] = (sig, now)
            return self.seconds <= 0
        return now - prev[1] >= self.seconds

    def forget(self, key: str) -> None:
        self._seen.pop(key, None)

    def prune(self, live_keys: set[str]) -> None:
        for k in list(self._seen):
            if k not in live_keys:
                del self._seen[k]


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"{path.name}-{stamp}")
    n = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.name}-{stamp}-{n}")
        n += 1
    return candidate


def move(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(dest_dir / src.name)
    shutil.move(str(src), str(dest))
    return dest


def claim(cand: Candidate, processing: Path) -> Path:
    """Move the job's files out of Ready/ so they are never picked up twice."""
    if cand.folder is not None:
        return move(cand.folder, processing)
    dest = unique_path(processing / cand.name)
    dest.mkdir(parents=True)
    for f in cand.files:
        shutil.move(str(f), str(dest / f.name))
    return dest


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Job:
    folder: Path
    clips: list[Path]
    caption: str
    meta: dict
    subject: str
    custom_thumbnail: Path | None
    state: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def out_dir(self) -> Path:
        d = self.folder / OUT_DIR
        d.mkdir(exist_ok=True)
        return d

    def opts(self, platform: str) -> dict:
        value = self.meta.get(platform)
        return value if isinstance(value, dict) else {}

    def target_platforms(self, enabled: tuple[str, ...]) -> list[str]:
        wanted = self.meta.get("platforms") or list(enabled)
        if not isinstance(wanted, list):
            raise JobError('meta.json "platforms" must be a list')
        wanted = [str(p).lower() for p in wanted]
        skipped = [p for p in wanted if p not in enabled]
        if skipped:
            log.warning("%s: platform(s) %s not enabled in PLATFORMS - skipping", self.name, skipped)
        return [p for p in enabled if p in wanted]

    # state -------------------------------------------------------------
    def stage(self, name: str) -> dict | None:
        return self.state.setdefault("stages", {}).get(name)

    def set_stage(self, name: str, data: dict) -> None:
        self.state.setdefault("stages", {})[name] = {**data, "at": now_iso()}
        self.save_state()

    def platform_state(self, name: str) -> dict:
        return self.state.setdefault("platforms", {}).get(name, {})

    def set_platform_state(self, name: str, data: dict) -> None:
        self.state.setdefault("platforms", {})[name] = {**data, "at": now_iso()}
        self.save_state()

    def save_state(self) -> None:
        path = self.folder / STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)


def load_job(folder: Path) -> Job:
    state_path = folder / STATE_FILE
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    clips = sorted(
        (p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not _hidden(p)),
        key=natural_key,
    )
    if not clips:
        raise JobError("no video file found")

    meta: dict = {}
    meta_path = folder / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig") or "{}")
        except json.JSONDecodeError as e:
            raise JobError(f"meta.json is not valid JSON: {e}") from e
        if not isinstance(meta, dict):
            raise JobError("meta.json must contain a JSON object")

    caption_path = folder / "caption.txt"
    caption = caption_path.read_text(encoding="utf-8-sig").strip() if caption_path.exists() else ""
    subject_path = folder / "subject.txt"
    subject_file = subject_path.read_text(encoding="utf-8-sig").strip() if subject_path.exists() else ""

    first_caption_line = next((ln.strip() for ln in caption.splitlines() if ln.strip()), "")
    subject = str(meta.get("subject") or subject_file or meta.get("title") or first_caption_line or folder.name)

    thumb = next((folder / n for n in THUMB_NAMES if (folder / n).exists()), None)
    return Job(folder, clips, caption, meta, subject.strip(), thumb, state)
