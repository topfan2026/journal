"""Live chat: message model, YouTube Data API poller with a daily quota budget, and a demo chat.

YouTube Data API v3 gives each project a daily quota (10,000 units by default) that resets at
midnight Pacific time. Each liveChatMessages.list call and each message the bot posts costs
units (see the costs in .env), so a 24/7 stream cannot poll every few seconds all day. The
poller paces itself: fast polling during the trivia show, slower polling on the study stream,
with enough budget held back for tonight's show.
"""
from __future__ import annotations

import logging
import queue
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
# Full "youtube" scope: the same one trading-shorts-bot's live streaming uses, so its token works here too.
SCOPES = ["https://www.googleapis.com/auth/youtube"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class ChatMessage:
    id: str
    author_id: str
    author: str
    text: str
    published: float          # epoch seconds
    kind: str = "text"        # text | superchat | member
    amount: str = ""          # "$5.00" for super chats / stickers
    is_mod: bool = False      # moderator or channel owner


def parse_item(item: dict) -> ChatMessage | None:
    """One liveChatMessages resource -> ChatMessage (None for events the stream ignores)."""
    snip, author = item.get("snippet", {}), item.get("authorDetails", {})
    kind_map = {
        "textMessageEvent": "text", "superChatEvent": "superchat", "superStickerEvent": "superchat",
        "newSponsorEvent": "member", "memberMilestoneChatEvent": "member", "membershipGiftingEvent": "member",
    }
    kind = kind_map.get(snip.get("type", ""))
    if kind is None:
        return None
    text = snip.get("displayMessage") or ""
    amount = ""
    if snip.get("type") == "textMessageEvent":
        text = snip.get("textMessageDetails", {}).get("messageText", text)
    elif snip.get("type") == "superChatEvent":
        details = snip.get("superChatDetails", {})
        text, amount = details.get("userComment", ""), details.get("amountDisplayString", "")
    elif snip.get("type") == "superStickerEvent":
        text, amount = "", snip.get("superStickerDetails", {}).get("amountDisplayString", "")
    return ChatMessage(
        id=item.get("id", ""),
        author_id=author.get("channelId", ""),
        author=author.get("displayName", "someone"),
        text=text or "",
        published=_epoch(snip.get("publishedAt")),
        kind=kind,
        amount=amount,
        is_mod=bool(author.get("isChatModerator") or author.get("isChatOwner")),
    )


def _epoch(iso: str | None) -> float:
    if not iso:
        return time.time()
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


class QuotaBudget:
    """Tracks YouTube API units spent since the last midnight-Pacific reset."""

    def __init__(self, daily: int, reserve: int, clock: Callable[[], float] = time.time):
        self.daily, self.reserve, self.clock = daily, reserve, clock
        self.spent = 0
        self._day = self._today()
        self._lock = threading.Lock()

    def _today(self):
        return datetime.fromtimestamp(self.clock(), PACIFIC).date()

    def _roll(self) -> None:
        if self._today() != self._day:
            self._day, self.spent = self._today(), 0

    def seconds_to_reset(self) -> float:
        now = datetime.fromtimestamp(self.clock(), PACIFIC)
        midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), PACIFIC)
        return max(1.0, (midnight - now).total_seconds())

    def remaining(self) -> int:
        with self._lock:
            self._roll()
            return max(0, self.daily - self.reserve - self.spent)

    def try_spend(self, units: int) -> bool:
        with self._lock:
            self._roll()
            if self.spent + units > self.daily - self.reserve:
                return False
            self.spent += units
            return True

    def mark_exhausted(self) -> None:
        """YouTube said quotaExceeded: assume nothing is left until the reset."""
        with self._lock:
            self.spent = self.daily

    def paced_interval(self, minimum: float, cost: int, held_back: int = 0) -> float:
        """Seconds between calls so that the budget (minus held_back units) lasts until the reset."""
        usable = self.remaining() - held_back
        calls = usable // max(1, cost)
        if calls <= 0:
            return self.seconds_to_reset()
        return max(minimum, self.seconds_to_reset() / calls)


class ChatSource:
    """Interface the app talks to. mode is 'study' or 'trivia' (trivia polls faster)."""

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def drain(self) -> list[ChatMessage]: return []
    def set_mode(self, mode: str, trivia_units_needed: int = 0) -> None: ...
    def set_target(self, broadcast_match: str) -> None: ...
    def send(self, text: str) -> None: ...
    def inject(self, msg: ChatMessage) -> None: ...
    def status(self) -> dict: return {}


class YouTubeChat(ChatSource):
    """Polls the live chat of the channel's active broadcast in a background thread."""

    def __init__(self, settings, service_factory: Callable[[], object] | None = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] | None = None):
        self.s = settings
        self.budget = QuotaBudget(settings.daily_quota, settings.quota_reserve, clock)
        self._service_factory = service_factory or youtube_service
        self._clock = clock
        self._stop = threading.Event()
        self._sleep = sleep or (lambda secs: self._stop.wait(secs))
        self._inbox: queue.Queue[ChatMessage] = queue.Queue()
        self._outbox: queue.Queue[str] = queue.Queue(maxsize=5)
        self._mode, self._trivia_units = "study", 0
        self._match = ""
        self._chat_id: str | None = None
        self._broadcast_id: str | None = None
        self._page: str | None = None
        self._viewers: int | None = None
        self._last_viewers = 0.0
        self._since = clock()
        self._last_post = 0.0
        self._status = {"connected": False, "detail": "starting"}
        self._thread: threading.Thread | None = None
        self._yt = None

    # ------------------------------------------------------------------ app side
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="youtube-chat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def inject(self, msg: ChatMessage) -> None:
        """A test message from the control page, handled as if it came from chat."""
        self._inbox.put(msg)

    def drain(self) -> list[ChatMessage]:
        out = []
        while True:
            try:
                out.append(self._inbox.get_nowait())
            except queue.Empty:
                return out

    def set_mode(self, mode: str, trivia_units_needed: int = 0) -> None:
        self._mode, self._trivia_units = mode, trivia_units_needed

    def set_target(self, broadcast_match: str) -> None:
        """Follow the live broadcast whose title contains this text (empty = the first live one)."""
        if broadcast_match != self._match:
            self._match, self._chat_id, self._page = broadcast_match, None, None

    def send(self, text: str) -> None:
        if self.s.bot_chat == "off":
            return
        try:
            self._outbox.put_nowait(text[:200])
        except queue.Full:
            log.info("chat: dropped bot message (queue full): %s", text)

    def status(self) -> dict:
        return dict(self._status, quota_left=self.budget.remaining(), viewers=self._viewers)

    # ------------------------------------------------------------------ poller thread
    def _run(self) -> None:
        backoff = 5.0
        while not self._stop.is_set():
            try:
                if self._yt is None:
                    self._yt = self._service_factory()
                wait = self.poll_once()
                backoff = 5.0
            except Exception as e:  # network, auth, unexpected API errors
                reason = _http_reason(e)
                if reason == "quotaExceeded":
                    self.budget.mark_exhausted()
                    wait = self.budget.seconds_to_reset()
                    self._status = {"connected": False, "detail": "YouTube API quota used up until midnight PT"}
                elif reason in ("liveChatEnded", "liveChatNotFound", "liveChatDisabled", "forbidden"):
                    self._chat_id, self._page = None, None
                    wait = 60
                    self._status = {"connected": False, "detail": f"chat unavailable ({reason}), looking again"}
                else:
                    log.warning("chat: %s", e)
                    self._status = {"connected": False, "detail": f"error: {e}"[:200]}
                    wait, backoff = backoff, min(backoff * 2, 300)
                    self._yt = None if reason == "auth" else self._yt
            self._sleep(wait)

    def poll_once(self) -> float:
        """One step: find the broadcast, or fetch new messages and post one queued message.
        Returns seconds to wait before the next step."""
        if self._chat_id is None:
            if not self.budget.try_spend(1):
                return self.budget.seconds_to_reset()
            resp = self._yt.liveBroadcasts().list(
                part="snippet", broadcastStatus="active", broadcastType="all").execute()
            match = pick_broadcast(resp.get("items", []), self._match)
            if match is None:
                wanted = f' titled "*{self._match}*"' if self._match else ""
                self._status = {"connected": False, "detail": f"no live broadcast{wanted} with chat found, retrying"}
                return 120
            self._broadcast_id, self._chat_id, self._page = match["id"], match["snippet"]["liveChatId"], None
            self._since, self._viewers = self._clock(), None
            self._status = {"connected": True, "detail": match["snippet"].get("title", "live")}

        if not self.budget.try_spend(self.s.list_cost):
            self._status = {"connected": True, "detail": "pausing chat reads: daily API quota reached"}
            return self.budget.seconds_to_reset()
        params = dict(liveChatId=self._chat_id, part="snippet,authorDetails", maxResults=200)
        if self._page:
            params["pageToken"] = self._page
        resp = self._yt.liveChatMessages().list(**params).execute()
        self._page = resp.get("nextPageToken")
        for item in resp.get("items", []):
            msg = parse_item(item)
            if msg and msg.published >= self._since - 2:  # skip the backlog from before we joined
                self._inbox.put(msg)
        self._flush_outbox()
        self._refresh_viewers()

        hint = resp.get("pollingIntervalMillis", 5000) / 1000.0
        if self._mode == "trivia":
            return max(hint, self.s.trivia_poll_seconds)
        return max(hint, self.budget.paced_interval(
            self.s.study_poll_seconds, self.s.list_cost, held_back=self._trivia_units))

    def _refresh_viewers(self) -> None:
        """Concurrent viewers every 5 minutes (1 unit) for the niche comparison."""
        if not self._broadcast_id or self._clock() - self._last_viewers < 300 or not self.budget.try_spend(1):
            return
        self._last_viewers = self._clock()
        resp = self._yt.videos().list(part="liveStreamingDetails", id=self._broadcast_id).execute()
        details = (resp.get("items") or [{}])[0].get("liveStreamingDetails", {})
        viewers = details.get("concurrentViewers")
        self._viewers = int(viewers) if viewers is not None else None

    def _flush_outbox(self) -> None:
        if self._outbox.empty() or self._clock() - self._last_post < 60:
            return
        held = self._trivia_units if self._mode != "trivia" else 0
        if self.budget.remaining() - held < self.s.insert_cost * 4:
            return  # keep reading chat rather than posting into it
        text = self._outbox.get_nowait()
        if not self.budget.try_spend(self.s.insert_cost):
            return
        self._yt.liveChatMessages().insert(part="snippet", body={"snippet": {
            "liveChatId": self._chat_id, "type": "textMessageEvent",
            "textMessageDetails": {"messageText": text}}}).execute()
        self._last_post = self._clock()


def pick_broadcast(items: list[dict], match: str) -> dict | None:
    """The first live broadcast that has a chat and whose title contains match (case-insensitive)."""
    for item in items:
        snip = item.get("snippet", {})
        if snip.get("liveChatId") and match.lower() in snip.get("title", "").lower():
            return item
    return None


def _http_reason(e: Exception) -> str:
    """Pull the API error reason (quotaExceeded, liveChatEnded, ...) out of an HttpError."""
    from google.auth.exceptions import RefreshError
    if isinstance(e, RefreshError):
        return "auth"
    content = getattr(e, "content", b"") or b""
    text = content.decode("utf-8", "ignore") if isinstance(content, bytes) else str(content)
    for reason in ("quotaExceeded", "liveChatEnded", "liveChatNotFound", "liveChatDisabled", "forbidden"):
        if reason in text:
            return reason
    return ""


def youtube_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    from config import env, require_env

    client_id, secret = require_env("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET")
    refresh = env("YOUTUBE_CHAT_REFRESH_TOKEN") or require_env("YOUTUBE_REFRESH_TOKEN")[0]
    creds = Credentials(None, refresh_token=refresh, token_uri=TOKEN_URI,
                        client_id=client_id, client_secret=secret, scopes=SCOPES)
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# ---------------------------------------------------------------------- demo chat

DEMO_NAMES = ["StudyBuddy", "NightOwl42", "MathIsLife", "coffee_coder", "NurseNina", "lofi_leo", "QuizQueen",
              "Sam_K", "BioNerd", "PixelPanda", "EssayGrinder", "ChemChris", "HistoryHana", "RunnerRob"]
DEMO_TASKS = ["finish chem lab report", "read chapter 7", "flashcards: anatomy", "essay intro + outline",
              "leetcode x3", "calc problem set", "revise for midterm", "clean up notes", "spanish vocab"]


DEMO_CHATTER = {
    "sleep": ["goodnight all", "this rain is perfect", "listening from Brazil", "can't sleep without this"],
    "trading-music": ["London open vibes", "good luck today everyone", "perfect background for charts",
                      "NY open soon", "coffee + this music"],
    "default": ["love this stream", "hi from Germany", "this music hits", "back again"],
}


class DemoChat(ChatSource):
    """Fake viewers so the overlay can be previewed without going live."""

    def __init__(self, settings, clock: Callable[[], float] = time.time, rate: float = 1.0, seed: int | None = None):
        self.s, self.clock, self.rate = settings, clock, rate
        self.rng = random.Random(seed)
        self.mode = "study"
        self.last = clock()
        self.counter = 0
        self.correct_letter: Callable[[], str | None] = lambda: None
        self.profile = None
        self._injected: list[ChatMessage] = []

    def set_mode(self, mode: str, trivia_units_needed: int = 0) -> None:
        self.mode = mode

    def status(self) -> dict:
        return {"connected": True, "detail": "demo chat", "quota_left": None,
                "viewers": 20 + int(15 * abs((self.clock() / 600) % 2 - 1))}

    def send(self, text: str) -> None:
        log.info("bot chat (demo, not sent): %s", text)

    def inject(self, msg: ChatMessage) -> None:
        self._injected.append(msg)

    def drain(self) -> list[ChatMessage]:
        now = self.clock()
        elapsed, self.last = now - self.last, now
        injected, self._injected = self._injected, []
        expected = elapsed * self.rate * (3.0 if self.mode == "trivia" else 0.25)
        n = int(expected) + (1 if self.rng.random() < expected % 1 else 0)
        return injected + [self._message(now) for _ in range(n)]

    def _message(self, now: float) -> ChatMessage:
        self.counter += 1
        idx = self.rng.randrange(len(DEMO_NAMES))
        name = DEMO_NAMES[idx]
        text, kind, amount = "hi everyone!", "text", ""
        roll = self.rng.random()
        if self.mode == "trivia":
            right = self.correct_letter()
            if roll < 0.004:
                kind, amount, text = "superchat", self.rng.choice(["$2.00", "$5.00", "$10.00"]), "love this show!"
            elif right and roll < 0.6:
                text = right
            else:
                text = self.rng.choice("ABCD")
        elif self.profile is not None and not self.profile.tasks:
            if self.profile.checkin_command and roll < 0.3:
                text = self.profile.checkin_command
            elif roll < 0.31:
                kind, amount, text = "superchat", "$2.00", "thanks for the vibes"
            else:
                text = self.rng.choice(DEMO_CHATTER.get(self.profile.niche, DEMO_CHATTER["default"]))
        else:
            if roll < 0.35:
                text = "!task " + self.rng.choice(DEMO_TASKS)
            elif roll < 0.5:
                text = "!done"
            elif roll < 0.55:
                text = "!hours"
            elif roll < 0.51:
                kind, amount, text = "superchat", "$5.00", "keep it up everyone"
            else:
                text = self.rng.choice(["back from break", "good luck on exams!", "focus time", "hi everyone!"])
        return ChatMessage(id=f"demo{self.counter}", author_id=f"UC{idx}", author=name, text=text,
                           published=now, kind=kind, amount=amount)
