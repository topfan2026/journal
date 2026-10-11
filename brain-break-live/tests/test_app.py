from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import App, ControlError
from chat import ChatMessage, DemoChat

NY = ZoneInfo("America/New_York")


def at(day, h, m=0):
    return datetime(2026, 10, day, h, m, tzinfo=NY).timestamp()


@pytest.fixture
def app(settings, profiles, bank, clock):
    chat = DemoChat(settings, clock=clock, rate=0, seed=1)
    return App(settings, profiles, chat, bank, active="study", clock=clock, seed=1)


def test_schedule_study_countdown_trivia(app, clock):
    clock.t = at(12, 12)
    assert app.mode(clock.t) == "study"
    clock.t = at(12, 19, 50)
    assert app.mode(clock.t) == "countdown"
    clock.t = at(12, 20, 5)
    assert app.mode(clock.t) == "trivia"
    assert app.theme_for(clock.t) == "movies"        # Monday = movie night
    clock.t = at(13, 20, 5)
    assert app.theme_for(clock.t) == "geography"


def test_show_runs_and_records_results(app, clock):
    clock.t = at(12, 20, 0)
    app.tick()
    assert app.game is not None and app.game.pack_id == "movies"
    app.chat.inject(ChatMessage("x", "ann", "Ann", "!task read", clock.t))
    app.tick()
    assert "ann" in app.study().tasks                  # study commands still work during the show
    for _ in range(int(62 * 60 / 5) + 30):             # play through the whole hour
        clock.advance(5)
        if app.game and app.game.phase == "question":
            app.chat.inject(ChatMessage(f"m{clock.t}", "ann", "Ann", app.game.correct_letter(), clock.t))
        app.tick()
    assert app.game is None
    assert app.history[-1]["pack"] == "movies"
    assert app.alltime["study"]["ann"]["wins"] == 1
    assert app.mode(clock.t) == "study"


def test_switch_profile_and_test_messages(app, clock):
    app.control("switch", profile="sleep")
    assert app.active == "sleep" and app.snapshot()["profile"]["scene"] == "rain-window"
    app.control("test_message", author="Ann", text="!sleep")
    app.tick()
    assert app.snapshot()["study"]["checkins"] == 1
    with pytest.raises(ControlError):
        app.control("switch", profile="nope")


def test_forced_trivia_start_and_stop(app, clock):
    clock.t = at(12, 12)
    app.control("trivia_start", minutes=10)
    app.tick()
    assert app.game is not None
    app.control("trivia_stop")
    app.tick()
    assert app.game is None and app.mode(clock.t) == "study"


def test_always_on_trivia_restarts(settings, profiles, bank, clock):
    a = App(settings, profiles, DemoChat(settings, clock=clock, rate=0), bank, active="trivia-247", clock=clock)
    a.tick()
    first = a.game
    assert first is not None
    for _ in range(40 * 12):
        clock.advance(5)
        a.tick()
    assert a.game is not None and a.game is not first


def test_state_survives_restart(app, clock, settings, profiles, bank):
    app.control("test_message", author="Ann", text="!task read")
    app.tick()
    app.control("switch", profile="coding")
    app.save()
    again = App(settings, profiles, DemoChat(settings, clock=clock, rate=0), bank, clock=clock)
    assert again.active == "coding"
    assert "test:Ann" in again.study("study").tasks


def test_stats_compare(app, clock):
    app.chat.inject(ChatMessage("1", "ann", "Ann", "hi", clock.t))
    for _ in range(4 * 3600):
        clock.advance(0.25)
        app.tick()
    rows = app.compare(1)
    assert rows[0]["profile"] == "study" and rows[0]["chatters"] == 1
    assert 0.9 < rows[0]["hours_live"] < 1.1
