# Brain Break Live

A 24/7 YouTube live stream that runs itself: a cosy "study with me" Pomodoro stream all day, and a
live trivia game show every night where viewers play by typing **A, B, C or D** in chat.
Everything on screen (scene, timer, task board, questions, leaderboard) is a web page you add to
OBS, driven by a small Python program that reads your YouTube live chat.

It is built as **niche profiles**, so the same program can also run a rain/sleep stream, a
"code with me" stream, background music for traders with a world market-hours board, or a 24/7
trivia channel. You can switch niches live and compare which one gets the most viewers and chat.

It is separate from `trading-shorts-bot` (its own folder and process) and only borrows the YouTube
login from it.

```
                       ┌──────────── python main.py ─────────────┐
YouTube live chat ───► │ chat poller (quota-paced)               │
 !task, !done, A/B/C/D │   ├─ StudyEngine  Pomodoro, tasks, goal  │──► http://127.0.0.1:8790/          ──► OBS Browser Source ──► YouTube Live
 Super Chats           │   ├─ TriviaGame   questions, scoring     │      (1920x1080 overlay + music)
                       │   └─ Stats        per-niche comparison   │──► http://127.0.0.1:8790/control   (you, in your browser)
                       └─────────────────────────────────────────┘
```

## 1. Install (Windows)

```bat
cd C:\journal\brain-break-live
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

(macOS/Linux: `python3 -m venv .venv && source .venv/bin/activate`, `cp .env.example .env`.)

## Updates (automatic)

`start.bat` and `start-demo.bat` update the program from GitHub **every time they start**, so you
never download it again by hand. While it runs, the control page shows when a new version is out;
click **Update now** and it installs it and restarts in a few seconds (the OBS page reconnects by
itself).

Your own files are never changed: `.env`, `data\` (stats, leaderboards, tasks), and whatever you put
in `music\` and `backgrounds\`. If you edited a file that an update also changes (a profile, for
example), your version is kept and the new one is saved next to it as `<name>.new`. Offline? It
starts the version you have. To turn updates off, put `AUTO_UPDATE=false` in `.env`.

## 2. Try it without YouTube

```bat
python main.py --demo
```

Open **http://127.0.0.1:8790/control**. Fake viewers chat, set tasks and play trivia. Click
**Start trivia now** to see the game show, switch niches on the right, and type into
**Test chat** to try any command yourself.

`python main.py --demo --trivia-now 10` starts a 10-minute show straight away.

## 3. Connect YouTube

If `..\trading-shorts-bot\.env` already has `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` and a
`YOUTUBE_REFRESH_TOKEN` from its live-streaming setup (full `youtube` access), nothing to do:
they are read from there. Otherwise put the client id/secret in this folder's `.env` and run:

```bat
python main.py auth
```

Then check everything:

```bat
python main.py check
```

Set `TIMEZONE` in `.env` (e.g. `America/New_York`) so the Pomodoro and the 8 PM show use your time.

## 4. Put it on stream (OBS)

1. In OBS, make a scene (e.g. "Brain Break") and add **Sources → + → Browser**:
   URL `http://127.0.0.1:8790/`, width **1920**, height **1080**, tick **Control audio via OBS**
   (that is how the music reaches the stream) and **Refresh browser when scene becomes active**.
2. Settings → Stream: YouTube, your stream key (or "Connect account").
3. Start `python main.py` (no `--demo`), then **Start Streaming** in OBS.

The program finds your live broadcast by itself and starts reading chat. Leave both running.
YouTube doesn't keep a full replay of very long streams; that's normal for 24/7 channels.

> Your `trading-shorts-bot` live bot (`live.py` / `live_gui.py`) always starts IB Gateway and the
> scanner site, so it can't run this stream as it is. OBS on its own is all Brain Break Live needs.

## 5. What viewers can do

| In chat | What happens |
|---|---|
| `!task finish essay` | adds your task to the on-screen board |
| `!done` | ticks it off |
| `!hours` | shows your total focus hours with the stream |
| `!focus` | counts you in for this focus block |
| `!sleep` (sleep niche) | adds you to tonight's count |
| `A` `B` `C` `D` | answers the trivia question (first answer counts) |
| `!join` | joins the trivia leaderboard |
| Super Chat | thank-you on screen; during trivia the next question is worth **double** |
| `!clear` (mods/owner) | clears the task board |

Anyone who chats during a focus block gets that block's minutes added to their hours and to the
**community goal**. Links and words in `blocked_words.txt` never appear on screen.

## 6. The trivia show

- Every night at `start` (default **20:00**) for `minutes` (default 60), set per profile.
- A banner on the study stream announces the show; 15 minutes before, it counts down.
- Themed nights: Mon **Movies**, Tue **Geography**, Wed **Science**, Thu **Music**,
  Fri **Mixed**, Sat **Sports**, Sun **General Knowledge**.
- 30 seconds per question, 10 points for a correct answer, +5 for the fastest correct answer
  (timed by YouTube's message timestamps, so chat lag doesn't decide who was fastest), a leaderboard
  every 10 questions and a final podium. Winners are kept on an all-time board.
- During Pomodoro breaks the study stream shows one practice "brain teaser" question.

Question packs live in `questions/*.json` (about 380 questions in total). Add your own:

```json
{"title": "Space Night", "questions": [
  {"q": "Which planet has the most moons?", "a": "Saturn", "wrong": ["Jupiter", "Uranus", "Mars"], "cat": "Space"}
]}
```

Save as `questions/space.json` and use `"space"` in a profile's `themes`. `python main.py check`
validates every pack. Packs repeat only after every question in them has been used.

## 7. Niches (profiles) and testing which one works

| Profile | Scene | What it is |
|---|---|---|
| `study` | study room | 25/5 Pomodoro, task board, community goal, nightly trivia (the main channel) |
| `sleep` | rain on a window | no timer, `!sleep` check-in counter, sleep music |
| `trading-music` | night city | 50/10 focus timer + New York / London / Frankfurt / Tokyo / Hong Kong / Sydney market hours, music only (no trade ideas) |
| `coding` | night city | 50/10 "code with me" with a task board |
| `trivia-247` | space | non-stop trivia, rounds back to back |

**Switch live:** click a profile on the control page. Scene, music, features and text change
within a second, without restarting anything.

**Run several at once** (one process per stream, each with its own OBS and YouTube stream):

```bat
python main.py --profile study --port 8790 --data-dir data\study
python main.py --profile sleep --port 8791 --data-dir data\sleep
```

Each profile's `broadcast_match` tells the bot which live broadcast's chat to read (the one whose
title contains that text). They share your Google project's API quota, so split
`YOUTUBE_DAILY_QUOTA` between them (e.g. 4500 each).

**Compare:** the control page's **Compare niches** table shows, per niche, hours live, average and
peak viewers, chatters and messages per hour, Super Chats, new members and trivia answers. Give each
niche a few days at similar hours; the ★ marks the most chatters per live hour (shown after at least
1 hour live). YouTube Studio has the full watch-time and revenue numbers.

**Make a new niche:** copy a file in `profiles/`, change `name`, `scene`
(`study-room`, `rain-window`, `fireplace`, `ocean`, `night-city`, `space`), the features and
`music_dir`, and restart. Every setting is listed in `config.py` (`Profile` and `TriviaConfig`).

## 8. Music

Put tracks in `music/<folder>/`; see [music/README.md](music/README.md). **Use only music you have
the rights to stream**, or YouTube will mute or remove the stream.

## 9. YouTube API quota

The YouTube Data API gives a Google Cloud project 10,000 units a day (reset at midnight Pacific).
Reading chat costs units every time, so the bot paces itself: every few seconds during trivia,
and on the study stream as often as the remaining budget allows while keeping enough for tonight's
show. When the day's budget runs out, the stream keeps running and chat commands resume after the
reset. The control page shows the units left. Costs are configurable in `.env`; check Google's
quota calculator and request more quota in Google Cloud if you need faster polling.

## 10. Making money from it

- **From day one:** `affiliate_line` in a profile is shown on the ticker and posted in chat every
  4 hours (study gear, headphones, your own Etsy/Gumroad products). Put the same links in the
  stream description.
- **After joining the YouTube Partner Program:** Super Chats (they double the next trivia question,
  which encourages them), memberships, and ads. Check YouTube's current eligibility requirements.
- Don't use the stream to give financial advice. The trading-music profile shows music and
  exchange hours only.

## Files

| File | Role |
|---|---|
| `main.py` | CLI: run / `--demo` / `check` / `auth` / `profiles` |
| `launcher.py`, `update.py` | Self-update from GitHub, then run; restart on "Update now" |
| `start.bat`, `start-demo.bat` | Double-click launchers for Windows |
| `app.py` | Active niche, trivia schedule, chat routing, persistence, control actions |
| `chat.py` | YouTube live-chat poller with quota pacing, message parsing, demo chat |
| `study.py` | Pomodoro, task board, check-ins, focus hours |
| `trivia.py` | Question packs, game flow, scoring |
| `stats.py` | Per-niche numbers for the comparison table |
| `server.py` | Local web server (overlay, control page, music, JSON API) |
| `config.py` | `.env` settings and profile loading |
| `overlay/` | `index.html` overlay, `control.html`, `scenes.js` animated backgrounds |
| `profiles/` | One JSON file per niche |
| `questions/` | Trivia packs |
| `data/` | Stats, leaderboards, tasks (created on first run, not committed) |

Tests: `pytest` (48 tests, no network or YouTube needed).
