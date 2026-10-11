import random

import pytest

from chat import ChatMessage
from config import TriviaConfig
from trivia import QuestionError, TriviaGame, load_pack, parse_answer


def msg(author, text, ts, kind="text", amount=""):
    return ChatMessage(id=f"{author}{ts}", author_id=author, author=author.title(), text=text,
                       published=ts, kind=kind, amount=amount)


def new_game(bank, start=1000.0, minutes=10, **cfg):
    c = TriviaConfig(enabled=True, question_seconds=30, reveal_seconds=10, leaderboard_every=3,
                     leaderboard_seconds=20, **cfg)
    return TriviaGame(cfg=c, bank=bank, pack_id="movies", starts=start, ends=start + minutes * 60,
                      rng=random.Random(1), used=set(), grace=6, intro_seconds=15, final_seconds=60)


@pytest.mark.parametrize("text,expected", [("A", 0), ("b", 1), (" c ", 2), ("!d", 3), ("D!", 3), ("a.", 0),
                                           ("e", None), ("ab", None), ("the answer is B", None), ("", None)])
def test_parse_answer(text, expected):
    assert parse_answer(text) == expected


def test_all_packs_are_valid(bank):
    assert set(bank.packs) >= {"movies", "geography", "science", "music", "sports", "general"}
    for pack in bank.packs.values():
        for q in pack.questions:
            assert q.answer not in q.wrong and len(set(q.wrong)) == 3, q.text


def test_bad_pack_rejected(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"questions": [{"q": "x?", "a": "1", "wrong": ["1", "2", "3"]}]}')
    with pytest.raises(QuestionError):
        load_pack(p)


def test_draw_does_not_repeat_until_pack_used_up(bank):
    used, rng = set(), random.Random(3)
    first = bank.draw("music", 30, used, rng)
    second = bank.draw("music", 20, used, rng)
    assert not {q.id for q in first} & {q.id for q in second}
    third = bank.draw("music", 10, used, rng)  # pack exhausted -> starts over
    assert len(third) == 10


def test_scoring_first_answer_counts_and_fastest_bonus(bank):
    g = new_game(bank)
    g.tick(1015)  # intro over -> question 1
    assert g.phase == "question" and g.number == 1
    right = "ABCD"[g.correct_index]
    wrong = "ABCD"[(g.correct_index + 1) % 4]
    g.handle(msg("ann", right, 1020))
    g.handle(msg("bob", right, 1018))       # earlier timestamp, fetched later -> fastest
    g.handle(msg("cat", wrong, 1019))
    g.handle(msg("cat", right, 1021))       # second answer ignored
    g.tick(1045)                            # time's up -> locked (grace for late batches)
    assert g.phase == "locked"
    g.handle(msg("dan", right, 1044))       # sent in time, arrived late -> counts
    g.handle(msg("eve", right, 1050))       # sent after time's up -> ignored
    g.tick(1051)
    assert g.phase == "reveal"
    pts = {p.name: p.points for p in g.players.values()}
    assert pts == {"Ann": 10, "Bob": 15, "Cat": 0, "Dan": 10}
    assert g.last_result["fastest"] == "Bob" and g.last_result["correct_count"] == 3


def test_answers_before_question_ignored(bank):
    g = new_game(bank)
    g.tick(1015)
    g.handle(msg("ann", "A", 1005))
    assert g.answers == {}


def test_superchat_doubles_next_question(bank):
    g = new_game(bank)
    g.tick(1015)
    g.handle(msg("rich", "", 1016, kind="superchat", amount="$5.00"))
    assert g.double_next and g.events[-1]["kind"] == "superchat"
    g.tick(1015 + 30 + 10)  # q1 over -> q2
    assert g.number == 2 and g.double_now
    g.handle(msg("ann", "ABCD"[g.correct_index], g.opened_at + 1))
    g.tick(g.closed_at + 6)
    assert g.players["ann"].points == 30  # (10 + 5 fastest) x 2


def test_leaderboard_break_and_final(bank):
    g = new_game(bank, minutes=3)
    t, phases = 1000.0, []
    while g.phase != "done" and t < 2000:
        t += 1
        g.tick(t)
        if not phases or phases[-1] != g.phase:
            phases.append(g.phase)
    assert "leaderboard" in phases
    assert phases[-2:] == ["final", "done"]
    assert g.number >= 3
