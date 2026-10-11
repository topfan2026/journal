"""Settings: global ones from environment variables / .env, per-niche ones from profiles/*.json."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv, set_key

BOT_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("BRAINBREAK_ENV_FILE", BOT_DIR / ".env")).expanduser()

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
SCENES = ("study-room", "rain-window", "fireplace", "ocean", "night-city", "space")

load_dotenv(ENV_FILE, override=False)
# Fall back to trading-shorts-bot's .env for the shared YouTube credentials (values above win).
SHORTS_BOT_ENV = BOT_DIR.parent / "trading-shorts-bot" / ".env"
if SHORTS_BOT_ENV.exists():
    from dotenv import dotenv_values
    for _key, _value in dotenv_values(SHORTS_BOT_ENV).items():
        if _key in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN") and _value:
            os.environ.setdefault(_key, _value)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_float(name: str, default: float) -> float:
    value = env(name)
    return float(value) if value is not None else default


def save_env(key: str, value: str) -> None:
    """Persist a token back into .env and the running process."""
    if not ENV_FILE.exists():
        ENV_FILE.touch(mode=0o600)
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value


class ConfigError(Exception):
    """A required setting / credential is missing or invalid."""


def require_env(*names: str) -> list[str]:
    missing = [n for n in names if not env(n)]
    if missing:
        raise ConfigError(f"missing in .env: {', '.join(missing)}")
    return [env(n) for n in names]  # type: ignore[misc]


def parse_hhmm(value: str) -> dtime:
    try:
        hh, mm = value.strip().split(":")
        return dtime(int(hh), int(mm))
    except ValueError as e:
        raise ConfigError(f"expected HH:MM, got {value!r}") from e


# --------------------------------------------------------------------------- global settings

@dataclass(frozen=True)
class Settings:
    tz: ZoneInfo
    port: int
    data_root: Path
    music_root: Path
    questions_dir: Path
    profiles_dir: Path
    study_poll_seconds: float
    trivia_poll_seconds: float
    daily_quota: int
    quota_reserve: int
    list_cost: int
    insert_cost: int
    bot_chat: str  # off | minimal
    blocked_words: tuple[str, ...] = field(default_factory=tuple)

    def ensure_dirs(self) -> None:
        for d in (self.data_root, self.music_root):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, **overrides) -> "Settings":
        tz_name = env("TIMEZONE")
        try:
            tz = ZoneInfo(tz_name) if tz_name else _local_zone()
        except Exception as e:  # ZoneInfoNotFoundError, ValueError
            raise ConfigError(f"unknown TIMEZONE {tz_name!r} (use e.g. America/New_York)") from e
        bot_chat = (env("BOT_CHAT", "minimal") or "minimal").lower()
        if bot_chat not in ("off", "minimal"):
            raise ConfigError("BOT_CHAT must be off or minimal")
        blocked_file = BOT_DIR / "blocked_words.txt"
        lines = blocked_file.read_text(encoding="utf-8").splitlines() if blocked_file.exists() else []
        values = dict(
            tz=tz,
            port=int(env_float("OVERLAY_PORT", 8790)),
            data_root=Path(env("DATA_DIR", str(BOT_DIR / "data"))).expanduser(),
            music_root=Path(env("MUSIC_DIR", str(BOT_DIR / "music"))).expanduser(),
            questions_dir=Path(env("QUESTIONS_DIR", str(BOT_DIR / "questions"))).expanduser(),
            profiles_dir=Path(env("PROFILES_DIR", str(BOT_DIR / "profiles"))).expanduser(),
            study_poll_seconds=env_float("STUDY_POLL_SECONDS", 20),
            trivia_poll_seconds=env_float("TRIVIA_POLL_SECONDS", 5),
            daily_quota=int(env_float("YOUTUBE_DAILY_QUOTA", 10000)),
            quota_reserve=int(env_float("YOUTUBE_QUOTA_RESERVE", 500)),
            list_cost=int(env_float("YOUTUBE_LIST_COST", 5)),
            insert_cost=int(env_float("YOUTUBE_INSERT_COST", 50)),
            bot_chat=bot_chat,
            blocked_words=tuple(w.strip().lower() for w in lines if w.strip() and not w.startswith("#")),
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)


def _local_zone() -> ZoneInfo:
    """Best effort: the machine's IANA zone, else UTC."""
    tz = os.environ.get("TZ")
    if tz:
        try:
            return ZoneInfo(tz)
        except Exception:
            pass
    try:
        link = Path("/etc/localtime").resolve()
        if "zoneinfo" in link.parts:
            return ZoneInfo("/".join(link.parts[link.parts.index("zoneinfo") + 1:]))
    except Exception:
        pass
    return ZoneInfo("UTC")


# --------------------------------------------------------------------------- niche profiles

@dataclass(frozen=True)
class TriviaConfig:
    enabled: bool = False
    always_on: bool = False                 # 24/7 trivia channel instead of a nightly show
    start: dtime = dtime(20, 0)
    minutes: int = 60
    days: tuple[str, ...] = DAYS
    themes: dict = field(default_factory=lambda: {
        "mon": "movies", "tue": "geography", "wed": "science", "thu": "music",
        "fri": "mixed", "sat": "sports", "sun": "general"})
    question_seconds: int = 30
    reveal_seconds: int = 10
    leaderboard_every: int = 10
    leaderboard_seconds: int = 20
    countdown_minutes: int = 15
    points: int = 10
    fastest_bonus: int = 5


@dataclass(frozen=True)
class Profile:
    id: str
    name: str                               # shown on the overlay
    niche: str                              # free text, used in the stats comparison
    scene: str = "study-room"
    headline: str = ""
    broadcast_match: str = ""               # pick the live broadcast whose title contains this
    pomodoro: bool = True
    focus_minutes: int = 25
    break_minutes: int = 5
    tasks: bool = True                      # !task / !done board
    checkin_command: str = ""               # e.g. "!sleep" -> "34 people resting with us"
    checkin_label: str = ""
    goal_hours: float = 0                   # community focus-hours goal (0 = hidden)
    goal_label: str = "community focus hours"
    clock: bool = True
    market_clock: bool = False              # New York / London / Tokyo / Sydney open-closed board
    ticker: tuple[str, ...] = ()
    affiliate_line: str = ""
    music_dir: str = ""                     # relative to MUSIC_DIR (empty = MUSIC_DIR itself)
    music_volume: float = 0.6
    break_question: bool = True             # a practice trivia question during Pomodoro breaks
    trivia: TriviaConfig = field(default_factory=TriviaConfig)

    def music_path(self, settings: Settings) -> Path:
        return (settings.music_root / self.music_dir) if self.music_dir else settings.music_root

    def to_public(self) -> dict:
        """What the overlay needs to know."""
        return {
            "id": self.id, "name": self.name, "niche": self.niche, "scene": self.scene,
            "headline": self.headline, "pomodoro": self.pomodoro, "tasks": self.tasks,
            "checkin_label": self.checkin_label, "checkin_command": self.checkin_command,
            "goal_hours": self.goal_hours, "goal_label": self.goal_label, "clock": self.clock,
            "market_clock": self.market_clock,
            "ticker": list(self.ticker), "affiliate_line": self.affiliate_line,
            "music_volume": self.music_volume, "trivia_enabled": self.trivia.enabled,
        }


def _trivia_from(raw: dict, where: str) -> TriviaConfig:
    known = {f.name for f in fields(TriviaConfig)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{where}: unknown trivia setting(s): {', '.join(sorted(unknown))}")
    values = dict(raw)
    if "start" in values:
        values["start"] = parse_hhmm(values["start"])
    if "days" in values:
        days = tuple(str(d).lower()[:3] for d in values["days"])
        if set(days) - set(DAYS):
            raise ConfigError(f"{where}: bad trivia days {values['days']}")
        values["days"] = days
    if "themes" in values:
        themes = dict(TriviaConfig().themes)
        themes.update({str(k).lower()[:3]: str(v) for k, v in values["themes"].items()})
        values["themes"] = themes
    return TriviaConfig(**values)


def load_profile(path: Path) -> Profile:
    where = path.name
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConfigError(f"{where}: {e}") from e
    raw.pop("_comment", None)
    known = {f.name for f in fields(Profile)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{where}: unknown setting(s): {', '.join(sorted(unknown))}")
    raw["id"] = path.stem
    raw.setdefault("niche", path.stem)
    if "name" not in raw:
        raise ConfigError(f"{where}: missing \"name\"")
    if raw.get("scene", "study-room") not in SCENES:
        raise ConfigError(f"{where}: scene must be one of {', '.join(SCENES)}")
    if "ticker" in raw:
        raw["ticker"] = tuple(raw["ticker"])
    raw["trivia"] = _trivia_from(raw.get("trivia", {}), where)
    profile = Profile(**raw)
    if profile.pomodoro and (profile.focus_minutes < 1 or profile.break_minutes < 1):
        raise ConfigError(f"{where}: focus_minutes and break_minutes must be at least 1")
    return profile


def load_profiles(settings: Settings) -> dict[str, Profile]:
    profiles = {p.stem: load_profile(p) for p in sorted(settings.profiles_dir.glob("*.json"))}
    if not profiles:
        raise ConfigError(f"no profiles found in {settings.profiles_dir}")
    return profiles
