"""Trivia: question packs and the live game (question -> time's up -> reveal -> leaderboard).

Viewers answer by typing A, B, C or D in chat. Only a viewer's first answer to each question
counts. Correct answers score `points`; the fastest correct answer (by YouTube's message
timestamp, not by when the bot happened to fetch it) also gets `fastest_bonus`. A Super Chat
makes the next question worth double.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from chat import ChatMessage

LETTERS = "ABCD"
ANSWER_RE = re.compile(r"^\s*!?\s*([abcd])\s*[.!)]*\s*$", re.IGNORECASE)


class QuestionError(Exception):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    pack: str
    category: str
    text: str
    answer: str
    wrong: tuple[str, str, str]

    def shuffled(self, rng: random.Random) -> tuple[list[str], int]:
        options = [self.answer, *self.wrong]
        rng.shuffle(options)
        return options, options.index(self.answer)


@dataclass(frozen=True)
class Pack:
    id: str
    title: str
    questions: tuple[Question, ...]


class QuestionBank:
    """Loads questions/*.json. The pack id "mixed" draws from every pack."""

    def __init__(self, folder: Path):
        self.packs: dict[str, Pack] = {}
        for path in sorted(Path(folder).glob("*.json")):
            pack = load_pack(path)
            self.packs[pack.id] = pack
        if not self.packs:
            raise QuestionError(f"no question packs in {folder}")

    def title(self, pack_id: str) -> str:
        if pack_id in self.packs:
            return self.packs[pack_id].title
        return "Mixed Bag"

    def pool(self, pack_id: str) -> list[Question]:
        if pack_id in self.packs:
            return list(self.packs[pack_id].questions)
        return [q for p in self.packs.values() for q in p.questions]

    def draw(self, pack_id: str, n: int, used: set[str], rng: random.Random) -> list[Question]:
        """n questions not in `used` (which is updated). When a pack runs out, it starts over."""
        pool = self.pool(pack_id)
        fresh = [q for q in pool if q.id not in used]
        if len(fresh) < n:
            used.difference_update(q.id for q in pool)
            fresh = pool
        rng.shuffle(fresh)
        picked = fresh[:n]
        used.update(q.id for q in picked)
        return picked

    def random_question(self, rng: random.Random) -> Question:
        return rng.choice(self.pool("mixed"))


def load_pack(path: Path) -> Pack:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise QuestionError(f"{path.name}: {e}") from e
    pack_id = Path(path).stem
    questions, seen = [], set()
    for i, item in enumerate(raw.get("questions", []), 1):
        where = f"{path.name} question {i}"
        try:
            text, answer, wrong = item["q"].strip(), item["a"].strip(), [w.strip() for w in item["wrong"]]
        except (KeyError, AttributeError, TypeError) as e:
            raise QuestionError(f"{where}: needs q, a and 3 wrong answers") from e
        if len(wrong) != 3 or answer in wrong or len(set(wrong)) != 3:
            raise QuestionError(f"{where}: needs exactly 3 different wrong answers, none equal to the answer")
        if text in seen:
            raise QuestionError(f"{where}: duplicate question")
        seen.add(text)
        questions.append(Question(id=f"{pack_id}:{i}", pack=pack_id, category=item.get("cat", ""),
                                  text=text, answer=answer, wrong=tuple(wrong)))  # type: ignore[arg-type]
    if not questions:
        raise QuestionError(f"{path.name}: no questions")
    return Pack(id=pack_id, title=raw.get("title", pack_id.title()), questions=tuple(questions))


def parse_answer(text: str) -> int | None:
    m = ANSWER_RE.match(text)
    return LETTERS.index(m.group(1).upper()) if m else None


@dataclass
class Player:
    name: str
    points: int = 0
    correct: int = 0


@dataclass
class TriviaGame:
    """One show. Drive it with handle(message) and tick(now); read it with snapshot(now)."""

    cfg: object                      # config.TriviaConfig
    bank: QuestionBank
    pack_id: str
    starts: float
    ends: float                      # no new questions after this; the final screen follows
    rng: random.Random
    used: set[str]
    grace: float = 6.0               # wait for late chat batches after time's up
    intro_seconds: float = 15.0
    final_seconds: float = 60.0

    phase: str = "intro"             # intro | question | locked | reveal | leaderboard | final | done
    phase_ends: float = 0.0
    number: int = 0
    question: Question | None = None
    options: list[str] = field(default_factory=list)
    correct_index: int = -1
    opened_at: float = 0.0
    closed_at: float = 0.0
    answers: dict[str, tuple[int, float, str]] = field(default_factory=dict)  # author_id -> (choice, ts, name)
    players: dict[str, Player] = field(default_factory=dict)
    double_next: bool = False
    double_now: bool = False
    last_result: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)  # toasts for the overlay
    total_answers: int = 0

    def __post_init__(self):
        self.phase_ends = self.starts + self.intro_seconds
        self._queue: list[Question] = []

    # ------------------------------------------------------------------ input
    def handle(self, msg: ChatMessage) -> None:
        if msg.kind == "superchat":
            self.double_next = True
            self._event(f"{msg.author} sent {msg.amount}: next question is DOUBLE POINTS!", "superchat")
            return
        if msg.kind == "member":
            self._event(f"Welcome to the club, {msg.author}!", "member")
            return
        if msg.text.strip().lower() == "!join":
            self.players.setdefault(msg.author_id, Player(msg.author))
            return
        choice = parse_answer(msg.text)
        if choice is None or self.phase not in ("question", "locked"):
            return
        skew = 1.5  # this PC's clock vs YouTube's message timestamps
        if not self.opened_at - skew <= msg.published <= self.closed_at + skew:
            return  # sent before the question appeared or after time was up
        if msg.author_id in self.answers:
            return  # first answer only
        self.answers[msg.author_id] = (choice, msg.published, msg.author)
        self.players.setdefault(msg.author_id, Player(msg.author)).name = msg.author
        self.total_answers += 1

    # ------------------------------------------------------------------ clock
    def tick(self, now: float) -> None:
        while self.phase != "done" and now >= self.phase_ends:
            self._advance()

    def _advance(self) -> None:
        c = self.cfg
        t = self.phase_ends
        if self.phase in ("intro", "leaderboard"):
            self._next_question(t) if t < self.ends else self._enter("final", t, self.final_seconds)
        elif self.phase == "question":
            self.closed_at = t
            self._enter("locked", t, self.grace)
        elif self.phase == "locked":
            self._score()
            self._enter("reveal", t, max(1.0, c.reveal_seconds - self.grace))
        elif self.phase == "reveal":
            if t >= self.ends:
                self._enter("final", t, self.final_seconds)
            elif c.leaderboard_every and self.number % c.leaderboard_every == 0:
                self._enter("leaderboard", t, c.leaderboard_seconds)
            else:
                self._next_question(t)
        elif self.phase == "final":
            self.phase = "done"

    def _enter(self, phase: str, at: float, seconds: float) -> None:
        self.phase, self.phase_ends = phase, at + seconds

    def _next_question(self, at: float) -> None:
        if not self._queue:
            self._queue = self.bank.draw(self.pack_id, 25, self.used, self.rng)
        self.question = self._queue.pop(0)
        self.options, self.correct_index = self.question.shuffled(self.rng)
        self.number += 1
        self.answers = {}
        self.opened_at, self.closed_at = at, at + self.cfg.question_seconds
        self.double_now, self.double_next = self.double_next, False
        self._enter("question", at, self.cfg.question_seconds)

    def _score(self) -> None:
        mult = 2 if self.double_now else 1
        right = sorted(((ts, aid, name) for aid, (choice, ts, name) in self.answers.items()
                        if choice == self.correct_index), key=lambda r: r[0])
        for _, aid, _ in right:
            p = self.players[aid]
            p.points += self.cfg.points * mult
            p.correct += 1
        fastest = None
        if right:
            fastest = right[0][2]
            self.players[right[0][1]].points += self.cfg.fastest_bonus * mult
        counts = [0, 0, 0, 0]
        for choice, _, _ in self.answers.values():
            counts[choice] += 1
        self.last_result = {"correct_count": len(right), "answered": len(self.answers),
                            "fastest": fastest, "counts": counts}

    def _event(self, text: str, kind: str) -> None:
        self.events.append({"text": text, "kind": kind})
        del self.events[:-10]

    # ------------------------------------------------------------------ output
    def leaderboard(self, n: int = 10) -> list[dict]:
        ranked = sorted(self.players.values(), key=lambda p: (-p.points, -p.correct, p.name.lower()))
        return [{"name": p.name, "points": p.points, "correct": p.correct} for p in ranked[:n] if p.points > 0]

    def correct_letter(self) -> str | None:
        return LETTERS[self.correct_index] if self.phase == "question" and self.question else None

    def snapshot(self, now: float) -> dict:
        snap = {
            "phase": self.phase, "pack": self.bank.title(self.pack_id), "number": self.number,
            "phase_ends": self.phase_ends, "remaining": max(0.0, self.phase_ends - now),
            "ends": self.ends, "double": self.double_now, "double_next": self.double_next,
            "players": len(self.players), "leaderboard": self.leaderboard(),
            "answered": len(self.answers),
        }
        if self.question and self.phase in ("question", "locked", "reveal"):
            snap.update(question=self.question.text, category=self.question.category, options=self.options,
                        question_seconds=self.cfg.question_seconds)
            if self.phase == "reveal":
                snap.update(correct=self.correct_index, result=self.last_result)
        return snap

    def summary(self) -> dict:
        return {"pack": self.pack_id, "questions": self.number, "players": len(self.players),
                "answers": self.total_answers, "top": self.leaderboard(3)}
