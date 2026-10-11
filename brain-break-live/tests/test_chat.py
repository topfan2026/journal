from datetime import datetime
from zoneinfo import ZoneInfo

from chat import QuotaBudget, YouTubeChat, parse_item, pick_broadcast

PT = ZoneInfo("America/Los_Angeles")


def item(kind="textMessageEvent", text="hi", ts="2026-10-12T19:00:00Z", **extra):
    snip = {"type": kind, "displayMessage": text, "publishedAt": ts}
    if kind == "textMessageEvent":
        snip["textMessageDetails"] = {"messageText": text}
    snip.update(extra)
    return {"id": "m1", "snippet": snip, "authorDetails": {"channelId": "UC1", "displayName": "Ann", "isChatModerator": True}}


def test_parse_text_superchat_and_ignored():
    m = parse_item(item(text="B"))
    assert (m.text, m.kind, m.author, m.is_mod) == ("B", "text", "Ann", True)
    assert m.published == datetime(2026, 10, 12, 19, tzinfo=ZoneInfo("UTC")).timestamp()
    sc = parse_item(item("superChatEvent", superChatDetails={"amountDisplayString": "$5.00", "userComment": "gg"}))
    assert (sc.kind, sc.amount, sc.text) == ("superchat", "$5.00", "gg")
    assert parse_item(item("pollEvent")) is None


def test_pick_broadcast_by_title():
    items = [{"id": "a", "snippet": {"title": "Rain for Sleep", "liveChatId": "c1"}},
             {"id": "b", "snippet": {"title": "Study With Me", "liveChatId": "c2"}},
             {"id": "c", "snippet": {"title": "No chat"}}]
    assert pick_broadcast(items, "study")["id"] == "b"
    assert pick_broadcast(items, "")["id"] == "a"
    assert pick_broadcast(items, "trivia") is None


def test_quota_budget_paces_and_resets():
    t = [datetime(2026, 10, 12, 12, 0, tzinfo=PT).timestamp()]
    b = QuotaBudget(10000, 500, clock=lambda: t[0])
    assert b.remaining() == 9500
    # 12h to reset, 9500 units at 5/call = 1900 calls -> ~22.7 s apart
    assert 22 < b.paced_interval(5, 5) < 23.5
    # holding back 7000 units for tonight's show slows the study stream down
    assert b.paced_interval(5, 5, held_back=7000) > 80
    assert b.try_spend(9500) and not b.try_spend(1)
    t[0] = datetime(2026, 10, 13, 0, 1, tzinfo=PT).timestamp()
    assert b.remaining() == 9500


class FakeRequest:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class FakeYouTube:
    def __init__(self):
        self.inserted = []

    def liveBroadcasts(self):
        return self

    def liveChatMessages(self):
        return self

    def videos(self):
        return self

    def list(self, **kw):
        if "broadcastStatus" in kw:
            return FakeRequest({"items": [{"id": "vid", "snippet": {"title": "Study With Me", "liveChatId": "chat"}}]})
        if kw.get("part") == "liveStreamingDetails":
            return FakeRequest({"items": [{"liveStreamingDetails": {"concurrentViewers": "42"}}]})
        return FakeRequest({"nextPageToken": "p2", "pollingIntervalMillis": 3000, "items": [
            item(text="old", ts="2026-10-12T18:00:00Z"), item(text="A", ts="2026-10-12T19:00:05Z")]})

    def insert(self, **kw):
        self.inserted.append(kw["body"]["snippet"]["textMessageDetails"]["messageText"])
        return FakeRequest({})


def test_poll_once_reads_new_messages_and_posts(settings):
    t = [datetime(2026, 10, 12, 19, 0, tzinfo=ZoneInfo("UTC")).timestamp()]
    chat = YouTubeChat(settings, clock=lambda: t[0])
    chat._yt = FakeYouTube()
    chat.set_target("study")
    chat.send("hello chat")
    wait = chat.poll_once()                                   # finds the broadcast, then reads its chat
    assert chat._chat_id == "chat"
    assert [m.text for m in chat.drain()] == ["A"]          # backlog from before we joined is skipped
    assert chat._yt.inserted == ["hello chat"]
    assert chat.status()["viewers"] == 42
    assert wait >= 3
    chat.set_mode("trivia")
    assert chat.poll_once() == 5                              # trivia polls at TRIVIA_POLL_SECONDS
