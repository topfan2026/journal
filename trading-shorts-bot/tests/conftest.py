import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import Settings  # noqa: E402
from stitch import ffmpeg_exe  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    s = Settings.load(root=tmp_path / "Shorts", dry_run=True, stable_seconds=0, width=270, height=480,
                      metadata_mode="off", platforms=("youtube", "instagram", "tiktok"))
    s.ensure_dirs()
    return s


@pytest.fixture
def make_clip():
    def _make(path: Path, seconds: float = 1.0, size: str = "320x240", audio: bool = True, color: str = "red"):
        cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
               "-f", "lavfi", "-i", f"color=c={color}:s={size}:d={seconds}:r=30"]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
        subprocess.run(cmd, check=True)
        return path
    return _make
