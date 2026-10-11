"""The running stream: active profile, trivia scheduler, chat routing, stats and control actions.

Everything goes through App.tick(now) (called a few times a second by main.py) and the HTTP
server reads App.snapshot() / calls App.control(). One lock guards both.
"""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from chat import ChatMessage, ChatSource, DemoChat
from config import DAYS, MEDIA_EXT, Profile, Settings
from stats import Stats
from study import StudyEngine
from trivia import QuestionBank, TriviaGame

log = logging.getLogger(__name__)

MUSIC_EXT = {".mp3", ".ogg", ".m4a", ".wav", ".flac", ".opus", ".webm"}


class ControlError(Exception):
    pass


class App:
    def __init__(self, settings: Settings, profiles: dict[str, Profile], chat: ChatSource,
                 bank: QuestionBank, active: str | None = None, clock=time.time, seed: int | None = None):
        self.s, self.profiles, self.chat, self.bank, self.clock = settings, profiles, chat, bank, clock
        self.rng = random.Random(seed)
        self.lock = threading.RLock()
        self.app_file = settings.data_root / "app.json"
        saved = self._read(self.app_file)
        self.active = active or saved.get("active") or ("study" if "study" in profiles else next(iter(profiles)))
        if self.active not in profiles:
            raise ControlError(f"unknown profile {self.active!r} (have: {', '.join(profiles)})")
        self.used: dict[str, set[str]] = {k: set(v) for k, v in saved.get("used", {}).items()}
        self.alltime: dict[str, dict] = saved.get("alltime", {})
        self.history: list[dict] = saved.get("history", [])[-50:]
        self.studies: dict[str, StudyEngine] = {}
        self.stats = Stats(settings.data_root / "stats.json", settings.tz)
        self.game: TriviaGame | None = None
        self.game_window: tuple[float, float] | None = None
        self.force: tuple[str, float] | None = None   # ("start"|"stop", until)
        self.events: list[dict] = []
        self.announced: set[str] = set()
        self.last_tick = clock()
        self.last_save = clock()
        self.last_viewers = 0.0
        self.last_affiliate = clock()
        if isinstance(chat, DemoChat):
            chat.correct_letter = lambda: self.game.correct_letter() if self.game else None
            chat.profile = self.profile
        chat.set_target(self.profile.broadcast_match)

    # ------------------------------------------------------------------ helpers
    @property
    def profile(self) -> Profile:
        return self.profiles[self.active]

    def study(self, pid: str | None = None) -> StudyEngine:
        pid = pid or self.active
        if pid not in self.studies:
            eng = StudyEngine(self.profiles[pid], self.s.tz, self.s.blocked_words, self.bank, self.rng)
            eng.load(self._read(self._study_file(pid)))
            self.studies[pid] = eng
        return self.studies[pid]

    def _study_file(self, pid: str) -> Path:
        return self.s.data_root / "profiles" / f"{pid}.json"

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        tmp.replace(path)

    def save(self) -> None:
        with self.lock:
            self._write(self.app_file, {"active": self.active, "used": {k: sorted(v) for k, v in self.used.items()},
                                        "alltime": self.alltime, "history": self.history[-50:]})
            for pid, eng in self.studies.items():
                self._write(self._study_file(pid), eng.to_dict())
            self.stats.save()

    def _event(self, text: str, kind: str, now: float) -> None:
        self.events.append({"text": text, "kind": kind, "at": now})
        del self.events[:-12]

    # ------------------------------------------------------------------ schedule
    def next_window(self, now: float) -> tuple[float, float] | None:
        """The trivia window that is running now, or the next one (epoch start, end)."""
        t = self.profile.trivia
        if not t.enabled or t.always_on:
            return None
        today = datetime.fromtimestamp(now, self.s.tz).date()
        for offset in range(-1, 8):
            day = today + timedelta(days=offset)
            if DAYS[day.weekday()] not in t.days:
                continue
            start = datetime.combine(day, t.start, self.s.tz).timestamp()
            end = start + t.minutes * 60
            if end > now:
                return start, end
        return None

    def mode(self, now: float) -> str:
        """study | countdown | trivia (what the stream should be doing right now)."""
        t = self.profile.trivia
        if self.force and now < self.force[1]:
            return "trivia" if self.force[0] == "start" else "study"
        if not t.enabled:
            return "study"
        if t.always_on:
            return "trivia"
        win = self.next_window(now)
        if win and win[0] <= now < win[1]:
            return "trivia"
        if win and win[0] - t.countdown_minutes * 60 <= now < win[0]:
            return "countdown"
        return "study"

    def theme_for(self, start: float) -> str:
        day = DAYS[datetime.fromtimestamp(start, self.s.tz).weekday()]
        pack = self.profile.trivia.themes.get(day, "mixed")
        return pack if pack in self.bank.packs else "mixed"

    def trivia_units_needed(self, now: float) -> int:
        """API units to hold back for the next show's fast chat polling."""
        win = self.next_window(now)
        if not win or win[0] - now > 24 * 3600:
            return 0
        seconds = win[1] - max(now, win[0])
        return int(seconds / self.s.trivia_poll_seconds) * self.s.list_cost

    # ------------------------------------------------------------------ main loop
    def tick(self, now: float | None = None) -> None:
        with self.lock:
            now = self.clock() if now is None else now
            dt, self.last_tick = max(0.0, min(now - self.last_tick, 5.0)), now
            p = self.profile
            mode = self.mode(now)
            self.chat.set_mode("trivia" if self.game else "study", self.trivia_units_needed(now))

            if mode == "trivia" and self.game is None:
                self._start_game(now)
            if mode == "countdown":
                win = self.next_window(now)
                key = f"countdown:{p.id}:{int(win[0])}" if win else ""
                if win and key not in self.announced:
                    self.announced.add(key)
                    mins = round((win[0] - now) / 60)
                    self.chat.send(f"🎬 {self.bank.title(self.theme_for(win[0]))} trivia starts in {mins} minutes! "
                                   "Answer A/B/C/D in chat to play.")

            for msg in self.chat.drain():
                self.stats.message(p.id, msg, now)
                if self.game and self.game.phase != "done":
                    self.game.handle(msg)
                    if msg.kind == "text":
                        self.study().handle(msg, now)  # !task etc. still work during the show
                else:
                    self.study().handle(msg, now)

            if self.game:
                self.game.tick(now)
                for e in self.game.events:
                    self._event(e["text"], e["kind"], now)
                self.game.events.clear()
                if self.game.phase == "done":  # the game stops asking at its end time, then shows the final board
                    self._end_game(now)
            eng = self.study()
            eng.tick(now)
            for e in eng.events:
                self._event(e["text"], e["kind"], now)
            eng.events.clear()

            self.stats.live(p.id, now, dt)
            st = self.chat.status()
            if st.get("viewers") is not None and now - self.last_viewers >= 300:
                self.last_viewers = now
                self.stats.viewers(p.id, now, int(st["viewers"]))
            if p.affiliate_line and now - self.last_affiliate >= 4 * 3600:
                self.last_affiliate = now
                self.chat.send(p.affiliate_line)
            if now - self.last_save >= 60:
                self.last_save = now
                self.save()

    def _start_game(self, now: float) -> None:
        t = self.profile.trivia
        if self.force and self.force[0] == "start":
            end = self.force[1]
        elif t.always_on:
            end = now + t.minutes * 60
        else:
            win = self.next_window(now)
            end = win[1] if win else now + t.minutes * 60
        pack = self.theme_for(now)
        used = self.used.setdefault(pack, set())
        self.game = TriviaGame(cfg=t, bank=self.bank, pack_id=pack, starts=now, ends=end, rng=self.rng,
                               used=used, grace=self.s.trivia_poll_seconds + 1)
        self.game_window = (now, end)
        self._event(f"{self.bank.title(pack)} trivia is LIVE! Type A, B, C or D to answer.", "goal", now)
        log.info("trivia: started %s pack until %s", pack, datetime.fromtimestamp(end, self.s.tz).strftime("%H:%M"))

    def _end_game(self, now: float) -> None:
        g = self.game
        self.game, self.game_window = None, None
        if g is None or g.number == 0:
            return
        summary = g.summary()
        self.history.append({**summary, "profile": self.active, "at": now})
        self.stats.trivia(self.active, now, summary["answers"])
        board = self.alltime.setdefault(self.active, {})
        for aid, pl in g.players.items():
            row = board.setdefault(aid, {"name": pl.name, "points": 0, "wins": 0})
            row["name"], row["points"] = pl.name, row["points"] + pl.points
        if summary["top"]:
            winner = summary["top"][0]
            for aid, pl in g.players.items():
                if pl.name == winner["name"] and pl.points == winner["points"]:
                    board[aid]["wins"] += 1
                    break
            self.chat.send(f"🏆 GG! Tonight's winner: {winner['name']} with {winner['points']} points. "
                           "Same time next show!")
        if self.force and self.force[0] == "start":
            self.force = None
        self.save()

    # ------------------------------------------------------------------ control (from the web page)
    def control(self, action: str, **args) -> dict:
        with self.lock:
            now = self.clock()
            if action == "switch":
                pid = args.get("profile", "")
                if pid not in self.profiles:
                    raise ControlError(f"unknown profile {pid!r}")
                if self.game:
                    self._end_game(now)
                self.force = None
                self.events = []
                self.active = pid
                self.chat.set_target(self.profile.broadcast_match)
                if isinstance(self.chat, DemoChat):
                    self.chat.profile = self.profile
                self.save()
                return {"ok": True, "active": pid}
            if action == "trivia_start":
                minutes = float(args.get("minutes") or self.profile.trivia.minutes)
                if self.game:
                    self._end_game(now)
                self.force = ("start", now + minutes * 60)
                return {"ok": True}
            if action == "trivia_stop":
                win = self.next_window(now)
                until = win[1] if win and win[0] <= now else now + 60
                self.force = ("stop", until)
                if self.game:
                    self._end_game(now)
                return {"ok": True}
            if action == "clear_tasks":
                self.study().tasks.clear()
                return {"ok": True}
            if action == "test_message":
                text = str(args.get("text", ""))[:200]
                author = str(args.get("author") or "TestViewer")[:30]
                kind = "superchat" if args.get("superchat") else "text"
                msg = ChatMessage(id=f"test{now}", author_id=f"test:{author}", author=author, text=text,
                                  published=now, kind=kind, amount="$5.00" if kind == "superchat" else "",
                                  is_mod=bool(args.get("mod")))
                inject = getattr(self.chat, "inject", None)
                if inject is None:
                    raise ControlError("this chat source cannot take test messages")
                inject(msg)
                return {"ok": True}
            raise ControlError(f"unknown action {action!r}")

    # ------------------------------------------------------------------ output
    def music(self) -> list[str]:
        folder = self.profile.music_path(self.s)
        if not folder.is_dir():
            return []
        return sorted(f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() in MUSIC_EXT)

    def backgrounds(self) -> list[str]:
        folder = self.s.backgrounds_dir
        if not folder.is_dir():
            return []
        return sorted(f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() in MEDIA_EXT)

    def _background(self, p: Profile) -> dict:
        """URLs of the profile's background files that exist (missing ones fall back to the scene)."""
        out = {}
        for key, name in (("day", p.background), ("night", p.background_night)):
            if name and (self.s.backgrounds_dir / name).is_file():
                out[key] = "/backgrounds/" + name
        return out

    def snapshot(self) -> dict:
        with self.lock:
            now = self.clock()
            p = self.profile
            mode = "trivia" if self.game else self.mode(now)
            snap = {
                "now": now, "mode": mode, "profile": p.to_public(), "events": self.events[-6:],
                "chat": self.chat.status(), "study": self.study().snapshot(now),
                "background": self._background(p),
            }
            win = self.next_window(now)
            if win and p.trivia.enabled:
                snap["next_show"] = {"starts": win[0], "theme": self.bank.title(self.theme_for(win[0]))}
            if self.game:
                snap["trivia"] = self.game.snapshot(now)
            board = self.alltime.get(p.id, {})
            snap["alltime"] = sorted(board.values(), key=lambda r: -r["points"])[:5]
            return snap

    def profiles_public(self) -> dict:
        with self.lock:
            return {"active": self.active, "profiles": [
                {"id": pid, "name": pr.name, "niche": pr.niche, "scene": pr.scene,
                 "background": pr.background or "", "has_background": bool(self._background(pr)),
                 "trivia": pr.trivia.enabled, "always_on": pr.trivia.always_on, "pomodoro": pr.pomodoro,
                 "music_tracks": len(self._tracks(pr)), "broadcast_match": pr.broadcast_match}
                for pid, pr in self.profiles.items()]}

    def _tracks(self, pr: Profile) -> list[str]:
        folder = pr.music_path(self.s)
        return [f.name for f in folder.iterdir() if f.suffix.lower() in MUSIC_EXT] if folder.is_dir() else []

    def compare(self, days: int = 7) -> list[dict]:
        with self.lock:
            today = datetime.fromtimestamp(self.clock(), self.s.tz).date()
            return self.stats.compare(days, today=today, names={k: v.name for k, v in self.profiles.items()})
