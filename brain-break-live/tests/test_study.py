import random
from datetime import datetime
from zoneinfo import ZoneInfo

from chat import ChatMessage
from study import StudyEngine, clean_text, pomodoro

NY = ZoneInfo("America/New_York")


def at(h, m, s=0):
    return datetime(2026, 10, 12, h, m, s, tzinfo=NY).timestamp()


def msg(author, text, ts=0.0, mod=False):
    return ChatMessage(id=text, author_id=author, author=author.title(), text=text, published=ts, is_mod=mod)


def test_pomodoro_follows_wall_clock():
    p = pomodoro(at(10, 10), NY, 25, 5)
    assert p["phase"] == "focus" and round(p["remaining"]) == 15 * 60
    p = pomodoro(at(10, 27), NY, 25, 5)
    assert p["phase"] == "break" and round(p["remaining"]) == 3 * 60
    assert pomodoro(at(0, 0, 1), NY, 25, 5)["session"] == 1
    assert pomodoro(at(10, 31), NY, 25, 5)["session"] == 22


def test_clean_text_strips_links_and_blocks_words():
    assert clean_text("read ch 4 https://spam.example/x", ()) == "read ch 4"
    assert clean_text("visit spam.com now", ()) == "visit now"
    assert clean_text("a badword here", ("badword",)) is None
    assert clean_text("   ", ()) is None
    assert len(clean_text("x" * 100, ())) == 48


def test_tasks_done_and_focus_credit(profiles, bank):
    eng = StudyEngine(profiles["study"], NY, (), bank, random.Random(0))
    eng.tick(at(10, 0))
    eng.handle(msg("ann", "!task finish essay"), at(10, 1))
    eng.handle(msg("bob", "hello"), at(10, 2))
    eng.handle(msg("ann", "!done"), at(10, 3))
    snap = eng.snapshot(at(10, 4))
    assert snap["tasks"][0] == {"name": "Ann", "text": "finish essay", "done": True}
    assert snap["pomodoro"]["active"] == 2
    eng.tick(at(10, 25, 1))  # focus -> break: both credited 25 min
    assert eng.minutes == {"ann": 25, "bob": 25}
    assert eng.community_minutes == 50
    assert eng.snapshot(at(10, 26))["break_question"]["correct"] is None   # hidden until the last minute
    assert eng.snapshot(at(10, 29, 30))["break_question"]["correct"] in range(4)


def test_mod_can_clear_but_viewer_cannot(profiles):
    eng = StudyEngine(profiles["study"], NY)
    eng.handle(msg("ann", "!task read"), at(10, 1))
    eng.handle(msg("bob", "!clear"), at(10, 2))
    assert eng.tasks
    eng.handle(msg("mo", "!clear", mod=True), at(10, 3))
    assert not eng.tasks


def test_checkins_count_once_per_day(profiles):
    eng = StudyEngine(profiles["sleep"], NY)
    for _ in range(3):
        eng.handle(msg("ann", "!sleep"), at(22, 0))
    eng.handle(msg("bob", "!SLEEP"), at(22, 1))
    assert eng.snapshot(at(22, 2))["checkins"] == 2
    eng.tick(datetime(2026, 10, 13, 1, 0, tzinfo=NY).timestamp())
    assert eng.snapshot(datetime(2026, 10, 13, 1, 0, tzinfo=NY).timestamp())["checkins"] == 0


def test_persistence_roundtrip(profiles):
    eng = StudyEngine(profiles["study"], NY)
    eng.handle(msg("ann", "!task read"), at(10, 1))
    eng.minutes["ann"] = 50
    copy = StudyEngine(profiles["study"], NY)
    copy.load(eng.to_dict())
    assert copy.minutes == {"ann": 50} and "ann" in copy.tasks
