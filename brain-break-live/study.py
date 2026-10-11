"""Study stream: wall-clock Pomodoro, the !task board, check-ins and the community focus goal.

The Pomodoro runs on the wall clock (with 25/5, focus is :00-:25 and :30-:55), so a viewer who
joins at any moment sees the same timer as everyone else and the stream needs no state to resume.
Anyone who chats or sets a task during a focus block is credited that block's minutes when it ends.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

from chat import ChatMessage

URL_RE = re.compile(r"(https?://|www\.)\S+|\S+\.(com|net|org|gg|ly|io|co)\b\S*", re.IGNORECASE)
TASK_TTL = 6 * 3600
DONE_TTL = 15 * 60
MAX_TASKS = 8


def clean_text(text: str, blocked: tuple[str, ...], limit: int = 48) -> str | None:
    """Text safe to show on stream, or None to reject it."""
    text = URL_RE.sub("", text)
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return None
    lowered = text.lower()
    if any(w in lowered for w in blocked):
        return None
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def pomodoro(now: float, tz, focus_min: int, break_min: int) -> dict:
    local = datetime.fromtimestamp(now, tz)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    since = (local - midnight).total_seconds()
    cycle = (focus_min + break_min) * 60
    pos = since % cycle
    block_start = now - pos
    if pos < focus_min * 60:
        phase, ends = "focus", block_start + focus_min * 60
    else:
        phase, ends = "break", block_start + cycle
    return {"phase": phase, "ends": ends, "remaining": ends - now, "session": int(since // cycle) + 1,
            "block_id": f"{midnight.date()}#{int(since // cycle)}"}


@dataclass
class StudyEngine:
    profile: object                  # config.Profile
    tz: object
    blocked: tuple[str, ...] = ()
    bank: object | None = None       # trivia.QuestionBank for break questions
    rng: random.Random = field(default_factory=random.Random)

    tasks: dict[str, dict] = field(default_factory=dict)          # author_id -> task
    minutes: dict[str, float] = field(default_factory=dict)       # author_id -> focus minutes
    names: dict[str, str] = field(default_factory=dict)
    community_minutes: float = 0.0
    checkins: dict[str, list[str]] = field(default_factory=dict)  # date -> author_ids
    active: set[str] = field(default_factory=set)                 # chatted this focus block
    current_block: str = ""
    current_phase: str = ""
    break_q: dict | None = None
    events: list[dict] = field(default_factory=list)
    replies: list[str] = field(default_factory=list)              # for the bot to post (sparingly)

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {"tasks": self.tasks, "minutes": self.minutes, "names": self.names,
                "community_minutes": self.community_minutes,
                "checkins": {d: ids for d, ids in self.checkins.items()}}

    def load(self, data: dict) -> None:
        self.tasks = data.get("tasks", {})
        self.minutes = data.get("minutes", {})
        self.names = data.get("names", {})
        self.community_minutes = float(data.get("community_minutes", 0))
        self.checkins = data.get("checkins", {})

    # ------------------------------------------------------------------ input
    def handle(self, msg: ChatMessage, now: float) -> None:
        p = self.profile
        self.names[msg.author_id] = msg.author
        if msg.kind == "superchat":
            note = clean_text(msg.text, self.blocked) if msg.text else None
            self._event(f"{msg.author} sent {msg.amount}" + (f": \"{note}\"" if note else "") + " · thank you!",
                        "superchat", now)
            return
        if msg.kind == "member":
            self._event(f"Welcome to the study club, {msg.author}!", "member", now)
            return
        if self.current_phase == "focus":
            self.active.add(msg.author_id)
        text = msg.text.strip()
        cmd, _, arg = text.partition(" ")
        cmd = cmd.lower()
        if p.tasks and cmd == "!task":
            task = clean_text(arg, self.blocked)
            if task:
                self.tasks[msg.author_id] = {"name": msg.author, "text": task, "done": False, "at": now}
                self.active.add(msg.author_id)
                self._event(f"{msg.author} is working on: {task}", "task", now)
        elif p.tasks and cmd == "!done":
            task = self.tasks.get(msg.author_id)
            if task and not task["done"]:
                task.update(done=True, at=now)
                self._event(f"{msg.author} finished: {task['text']}  ✓", "done", now)
        elif cmd in ("!hours", "!stats"):
            hours = self.minutes.get(msg.author_id, 0) / 60
            self._event(f"{msg.author}: {hours:.1f} focus hours with us", "info", now)
        elif cmd == "!focus":
            self.active.add(msg.author_id)
            self._event(f"{msg.author} is locked in", "info", now)
        elif p.checkin_command and cmd == p.checkin_command.lower():
            today = self._today(now)
            ids = self.checkins.setdefault(today, [])
            if msg.author_id not in ids:
                ids.append(msg.author_id)
                self._event(f"{msg.author} checked in · {len(ids)} today", "checkin", now)
        elif cmd == "!clear" and msg.is_mod:
            self.tasks.clear()
            self._event("Task board cleared", "info", now)

    # ------------------------------------------------------------------ clock
    def tick(self, now: float) -> None:
        p = self.profile
        if p.pomodoro:
            pomo = pomodoro(now, self.tz, p.focus_minutes, p.break_minutes)
            if self.current_phase == "focus" and pomo["phase"] == "break":
                self._credit(now)
                self._new_break_question()
            if pomo["block_id"] != self.current_block and pomo["phase"] == "focus":
                self.active = set()
            self.current_block, self.current_phase = pomo["block_id"], pomo["phase"]
        for aid in [a for a, t in self.tasks.items()
                    if now - t["at"] > (DONE_TTL if t["done"] else TASK_TTL)]:
            del self.tasks[aid]
        today = self._today(now)
        for day in [d for d in self.checkins if d != today]:
            del self.checkins[day]

    def _credit(self, now: float) -> None:
        if not self.active:
            return
        mins = self.profile.focus_minutes
        for aid in self.active:
            self.minutes[aid] = self.minutes.get(aid, 0) + mins
        self.community_minutes += mins * len(self.active)
        self._event(f"Focus block done! +{mins * len(self.active) / 60:.1f} hours from {len(self.active)} of you",
                    "goal", now)
        self.active = set()

    def _new_break_question(self) -> None:
        if not (self.profile.break_question and self.bank):
            self.break_q = None
            return
        q = self.bank.random_question(self.rng)
        options, correct = q.shuffled(self.rng)
        self.break_q = {"question": q.text, "options": options, "correct": correct}

    def _event(self, text: str, kind: str, now: float) -> None:
        self.events.append({"text": text, "kind": kind, "at": now})
        del self.events[:-12]

    def _today(self, now: float) -> str:
        return str(datetime.fromtimestamp(now, self.tz).date())

    # ------------------------------------------------------------------ output
    def snapshot(self, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        p = self.profile
        snap: dict = {}
        if p.pomodoro:
            pomo = pomodoro(now, self.tz, p.focus_minutes, p.break_minutes)
            snap["pomodoro"] = {**pomo, "focus_minutes": p.focus_minutes, "break_minutes": p.break_minutes,
                                "active": len(self.active)}
            if pomo["phase"] == "break" and self.break_q:
                reveal = pomo["remaining"] < 60
                snap["break_question"] = {**self.break_q, "correct": self.break_q["correct"] if reveal else None}
        if p.tasks:
            ordered = sorted(self.tasks.values(), key=lambda t: (t["done"], -t["at"]))
            snap["tasks"] = [{"name": t["name"], "text": t["text"], "done": t["done"]} for t in ordered[:MAX_TASKS]]
        if p.checkin_command:
            snap["checkins"] = len(self.checkins.get(self._today(now), []))
        if p.goal_hours:
            snap["goal"] = {"hours": round(self.community_minutes / 60, 1), "target": p.goal_hours,
                            "label": p.goal_label}
        return snap
