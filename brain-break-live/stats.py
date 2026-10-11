"""Per-niche stats so different profiles can be compared: hours live, chat, viewers, support.

Stored as data/stats.json: {profile_id: {"YYYY-MM-DD": {...counters}}}. Unique chatters are kept
as hashed ids for the current day only.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from chat import ChatMessage

MIN_HOURS_FOR_RATES = 0.25
RANK_MIN_HOURS = 1.0
COUNTERS = ("seconds_live", "messages", "commands", "superchats", "members", "trivia_answers",
            "trivia_shows", "viewer_sum", "viewer_samples", "viewer_peak")


def _blank() -> dict:
    return {**{k: 0 for k in COUNTERS}, "chatters": [], "amounts": []}


class Stats:
    def __init__(self, path: Path, tz):
        self.path, self.tz = Path(path), tz
        self.data: dict[str, dict[str, dict]] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.data = {}

    def _day(self, profile_id: str, now: float) -> dict:
        day = str(datetime.fromtimestamp(now, self.tz).date())
        days = self.data.setdefault(profile_id, {})
        if day not in days:
            for old in days.values():  # only today's chatter ids are needed
                if isinstance(old.get("chatters"), list):
                    old["chatters"] = len(old["chatters"])
            days[day] = _blank()
        return days[day]

    def live(self, profile_id: str, now: float, seconds: float) -> None:
        self._day(profile_id, now)["seconds_live"] += seconds

    def message(self, profile_id: str, msg: ChatMessage, now: float) -> None:
        d = self._day(profile_id, now)
        d["messages"] += 1
        if msg.text.strip().startswith("!"):
            d["commands"] += 1
        if msg.kind == "superchat":
            d["superchats"] += 1
            if msg.amount:
                d["amounts"].append(msg.amount)
        elif msg.kind == "member":
            d["members"] += 1
        h = hashlib.sha1(msg.author_id.encode()).hexdigest()[:12]
        if h not in d["chatters"]:
            d["chatters"].append(h)

    def viewers(self, profile_id: str, now: float, count: int) -> None:
        d = self._day(profile_id, now)
        d["viewer_sum"] += count
        d["viewer_samples"] += 1
        d["viewer_peak"] = max(d["viewer_peak"], count)

    def trivia(self, profile_id: str, now: float, answers: int) -> None:
        d = self._day(profile_id, now)
        d["trivia_shows"] += 1
        d["trivia_answers"] += answers

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def compare(self, days: int, today: date | None = None, names: dict[str, str] | None = None) -> list[dict]:
        """One row per profile over the last `days` days, best first by chatters per live hour."""
        today = today or datetime.now(self.tz).date()
        wanted = {str(today - timedelta(days=i)) for i in range(days)}
        rows = []
        for pid, by_day in self.data.items():
            picked = [v for k, v in by_day.items() if k in wanted]
            if not picked:
                continue
            total = {k: sum(d.get(k, 0) for d in picked) for k in COUNTERS if k != "viewer_peak"}
            hours = total["seconds_live"] / 3600
            chatters = sum(len(d["chatters"]) if isinstance(d["chatters"], list) else d["chatters"] for d in picked)
            rows.append({
                "profile": pid, "name": (names or {}).get(pid, pid), "days": len(picked),
                "hours_live": round(hours, 2 if hours < 1 else 1),
                "avg_viewers": round(total["viewer_sum"] / total["viewer_samples"], 1) if total["viewer_samples"] else None,
                "peak_viewers": max((d.get("viewer_peak", 0) for d in picked), default=0),
                "messages": total["messages"],
                "messages_per_hour": round(total["messages"] / hours, 1) if hours >= MIN_HOURS_FOR_RATES else None,
                "chatters": chatters,
                "chatters_per_hour": round(chatters / hours, 2) if hours >= MIN_HOURS_FOR_RATES else None,
                "superchats": total["superchats"],
                "amounts": [a for d in picked for a in d.get("amounts", [])][-20:],
                "members": total["members"],
                "trivia_shows": total["trivia_shows"],
                "trivia_answers": total["trivia_answers"],
            })
        rows.sort(key=lambda r: (r["hours_live"] >= RANK_MIN_HOURS, r["chatters_per_hour"] or 0, r["avg_viewers"] or 0),
                  reverse=True)
        return rows
