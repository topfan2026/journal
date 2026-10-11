import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Settings, load_profiles  # noqa: E402
from trivia import QuestionBank  # noqa: E402


@pytest.fixture
def settings(tmp_path):
    s = Settings.load(tz=ZoneInfo("America/New_York"), data_root=tmp_path / "data", music_root=tmp_path / "music",
                      backgrounds_dir=tmp_path / "backgrounds", questions_dir=ROOT / "questions", profiles_dir=ROOT / "profiles", port=0,
                      trivia_poll_seconds=5, study_poll_seconds=20, daily_quota=10000, quota_reserve=500,
                      list_cost=5, insert_cost=50, bot_chat="minimal", blocked_words=("badword",))
    s.ensure_dirs()
    return s


@pytest.fixture
def profiles(settings):
    return load_profiles(settings)


@pytest.fixture
def bank():
    return QuestionBank(ROOT / "questions")


class Clock:
    def __init__(self, t: float):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def clock():
    # Monday 2026-10-12 12:00 New York
    from datetime import datetime
    return Clock(datetime(2026, 10, 12, 12, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
