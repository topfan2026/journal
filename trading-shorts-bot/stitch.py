"""Editor agent: stitch clips (e.g. 6 x 10s) into one 9:16 vertical short with ffmpeg.

Every clip is scaled to VIDEO_WIDTH x VIDEO_HEIGHT (default 1080x1920),
letter-boxed ("pad") or center-cropped ("crop"), set to 30 fps with stereo AAC
audio (silence is added for clips without an audio track), concatenated in
natural filename order (clip2 before clip10), and trimmed to MAX_DURATION.

Standalone:  python stitch.py out.mp4 clip1.mp4 clip2.mp4 ...
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


def ffmpeg_exe() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg  # bundled static ffmpeg, installed via requirements.txt
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        raise RuntimeError("ffmpeg not found - install it (brew/apt install ffmpeg) or `pip install imageio-ffmpeg`") from e


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_audio: bool

    @property
    def vertical(self) -> bool:
        return self.height > self.width


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO = re.compile(r"Stream #.*?Video:.*?(\d{2,5})x(\d{2,5})")
_ROTATE = re.compile(r"rotation of (-?\d+(?:\.\d+)?) degrees|rotate\s*:\s*(-?\d+)")


def probe(path: Path) -> MediaInfo:
    """Read duration / size / audio presence by parsing `ffmpeg -i` output."""
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True, text=True, errors="replace",
    )
    out = proc.stderr
    d, v = _DURATION.search(out), _VIDEO.search(out)
    if not d or not v:
        raise ValueError(f"cannot read video {path.name} (incomplete download or not a video?)")
    duration = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3))
    w, h = int(v.group(1)), int(v.group(2))
    rot = _ROTATE.search(out)
    if rot and abs(round(float(rot.group(1) or rot.group(2)))) % 180 == 90:
        w, h = h, w
    return MediaInfo(duration, w, h, has_audio=bool(re.search(r"Stream #.*?Audio:", out)))


def stitch(
    clips: list[Path],
    out: Path,
    *,
    width: int = 1080,
    height: int = 1920,
    max_duration: float = 60.0,
    fit: str = "pad",
    fps: int = 30,
) -> MediaInfo:
    if not clips:
        raise ValueError("no clips to stitch")
    infos = [probe(c) for c in clips]
    total = sum(i.duration for i in infos)
    if total > max_duration + 0.5:
        log.warning("clips total %.1fs - trimming to %.0fs", total, max_duration)

    if fit == "crop":
        scale = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    else:
        scale = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black")

    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    filters, pairs = [], []
    silence_idx = len(clips)
    for i, info in enumerate(infos):
        filters.append(f"[{i}:v:0]{scale},setsar=1,fps={fps},format=yuv420p[v{i}]")
        if info.has_audio:
            filters.append(f"[{i}:a:0]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
        else:
            cmd += ["-f", "lavfi", "-t", f"{info.duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
            filters.append(f"[{silence_idx}:a]aformat=sample_fmts=fltp:channel_layouts=stereo[a{i}]")
            silence_idx += 1
        pairs.append(f"[v{i}][a{i}]")
    filters.append(f"{''.join(pairs)}concat=n={len(clips)}:v=1:a=1[v][a]")

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".part.mp4")
    cmd += [
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-t", f"{max_duration:.3f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high",
        "-pix_fmt", "yuv420p", "-r", str(fps),
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
        "-movflags", "+faststart", str(tmp),
    ]
    log.info("stitching %d clip(s) -> %s", len(clips), out.name)
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-1500:]}")
    tmp.replace(out)
    return probe(out)


def extract_frame(video: Path, at_seconds: float, out: Path) -> Path:
    proc = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at_seconds:.2f}",
         "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)],
        capture_output=True, text=True, errors="replace",
    )
    if proc.returncode != 0 or not out.exists():
        raise RuntimeError(f"frame extraction failed: {proc.stderr.strip()[-500:]}")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    info = stitch([Path(p) for p in sys.argv[2:]], Path(sys.argv[1]))
    print(f"wrote {sys.argv[1]}: {info.duration:.1f}s {info.width}x{info.height}")
