"""Settings, loaded from environment variables / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv, set_key

BOT_DIR = Path(__file__).resolve().parent
ENV_FILE = Path(os.environ.get("BOT_ENV_FILE", BOT_DIR / ".env")).expanduser()

PLATFORMS = ("youtube", "instagram", "tiktok")

load_dotenv(ENV_FILE, override=False)


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_bool(name: str, default: bool = False) -> bool:
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_float(name: str, default: float) -> float:
    value = env(name)
    return float(value) if value is not None else default


def save_env(key: str, value: str) -> None:
    """Persist a (rotated) token back into .env and the running process."""
    if not ENV_FILE.exists():
        ENV_FILE.touch(mode=0o600)
    set_key(str(ENV_FILE), key, value)
    os.environ[key] = value


class ConfigError(Exception):
    """A required setting / credential is missing."""


def require_env(*names: str) -> list[str]:
    missing = [n for n in names if not env(n)]
    if missing:
        raise ConfigError(f"missing in .env: {', '.join(missing)}")
    return [env(n) for n in names]  # type: ignore[misc]


@dataclass(frozen=True)
class Settings:
    root: Path
    platforms: tuple[str, ...]
    stable_seconds: float
    poll_seconds: float
    max_duration: float
    width: int
    height: int
    dry_run: bool
    ai_generated: bool
    disclaimer: str
    metadata_mode: str  # fill | always | off
    claude_model: str

    @property
    def ready(self) -> Path:
        return self.root / "Ready"

    @property
    def processing(self) -> Path:
        return self.root / "Processing"

    @property
    def done(self) -> Path:
        return self.root / "Done"

    @property
    def failed(self) -> Path:
        return self.root / "Failed"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure_dirs(self) -> None:
        for d in (self.ready, self.processing, self.done, self.failed, self.logs):
            d.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, **overrides) -> "Settings":
        platforms = tuple(
            p.strip().lower()
            for p in (env("PLATFORMS", ",".join(PLATFORMS)) or "").split(",")
            if p.strip()
        )
        unknown = set(platforms) - set(PLATFORMS)
        if unknown:
            raise ConfigError(f"unknown platform(s) in PLATFORMS: {', '.join(sorted(unknown))}")
        values = dict(
            root=Path(env("SHORTS_ROOT", "~/TradingShorts")).expanduser(),
            platforms=platforms,
            stable_seconds=env_float("STABLE_SECONDS", 10),
            poll_seconds=env_float("POLL_SECONDS", 5),
            max_duration=env_float("MAX_DURATION", 60),
            width=int(env_float("VIDEO_WIDTH", 1080)),
            height=int(env_float("VIDEO_HEIGHT", 1920)),
            dry_run=env_bool("DRY_RUN", False),
            ai_generated=env_bool("AI_GENERATED", True),
            disclaimer=env("DISCLAIMER", "") or "",
            metadata_mode=(env("METADATA_MODE", "fill") or "fill").lower(),
            claude_model=env("CLAUDE_MODEL", "claude-opus-5") or "claude-opus-5",
        )
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)
