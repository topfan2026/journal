# trading-shorts-bot

Two tools in one folder, sharing the same `.env` and YouTube login:

- **Daily live stream** (`live_gui.py` / `live.py`): every morning it logs IB Gateway into your
  paper account, opens your scanner site (aialgopro.com), starts OBS and goes live on YouTube.
  See [Daily live stream](#daily-live-stream) below.
- **Shorts auto-publisher** (`watcher.py`): a local auto-publishing bot for 60-second vertical videos. You drop a video (or 6×10s clips) plus a
subject/caption into a folder. A small team of agents edits it, writes the title, description, tags
and captions, makes a thumbnail, and publishes to **YouTube Shorts, Instagram Reels and TikTok**
using their official APIs.

It isn't limited to trading. Any subject works: the copywriter agent writes from the subject and
script you give it.

```
Meta AI / any generator            you download into             the bot (python watcher.py)
────────────────────────  ─►  ~/TradingShorts/Ready/<job>/  ─►  ┌──────────────────────────────────────┐
 6×10s clips or one 60s mp4       clip1..6.mp4 | video.mp4        │ 1 EditorAgent     stitch → 1080×1920 │
 + subject / caption              caption.txt  meta.json          │ 2 CopywriterAgent Claude → title,    │
                                                                  │   description, tags, captions        │
                                                                  │ 3 ThumbnailAgent  frame + hook text  │
                                                                  │ 4 UploadAgents (in parallel)         │
                                                                  │   YouTube │ Instagram │ TikTok       │
                                                                  └──────────────────────────────────────┘
                                                                        ▼ Done/<job>/job.json (links, ids)
                                                                        ▼ Failed/<job>/ (retry-able)
```

No agent framework (Hermes, LangChain, ...) is needed. The agents are plain Python classes in
`agents.py`, run by an orchestrator. Only the copywriter calls an LLM (Claude); editing and
uploading are deterministic code, so the same input always produces the same result.

## Files

| File | Role |
|---|---|
| `watcher.py` | Watches `Ready/` (watchdog + polling fallback), claims finished jobs, CLI |
| `agents.py` | Orchestrator + Editor / Copywriter / Thumbnail / Upload agents, checkpointing |
| `stitch.py` | ffmpeg: N clips → one 9:16 1080×1920 30fps H.264/AAC mp4, trimmed to 60s |
| `metadata.py` | Claude copywriter + platform limits (#Shorts, 100-char titles, 2200-char captions...) |
| `thumbnail.py` | Thumbnail with hook text (or your own `thumbnail.jpg`) + cover frame time |
| `upload_youtube.py` | YouTube Data API v3 resumable upload + custom thumbnail |
| `upload_instagram.py` | Instagram Graph API Reels, resumable upload of the local file |
| `upload_tiktok.py` | TikTok Content Posting API (inbox or direct post), chunked upload |
| `auth_setup.py` | One-time OAuth helpers that write tokens into `.env` |
| `job.py`, `config.py`, `common.py` | Job discovery/state, settings, shared types |
| `live_gui.py` | **Live stream app:** settings tabs, start/stop, test, autostart |
| `live.py` | Live stream orchestrator + scheduler + CLI |
| `ibkr.py` | IB Gateway via IBC (paper), paper-account guard |
| `scanner_site.py` | Opens the scanner website and starts the scanner (Playwright) |
| `obs_control.py` | OBS via WebSocket: scene, stream key, start/stop |
| `youtube_live.py` | YouTube Live broadcast, reusable stream key, go live / end |
| `autostart.py` | Task Scheduler / launchd / systemd registration |

## 1. Install

Requires Python 3.10+.

```bash
cd trading-shorts-bot
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # then fill it in (steps below)
```

ffmpeg comes bundled via `imageio-ffmpeg`. If you already have `ffmpeg` on your PATH
(`brew install ffmpeg` / `apt install ffmpeg`), that one is used instead.

## 2. Drop format

One folder per video in `~/TradingShorts/Ready/` (the folders are created on first run):

```
~/TradingShorts/Ready/2026-09-25-orb-strategy/
    clip1.mp4 ... clip6.mp4    # stitched in natural order (clip2 before clip10), or a single 60s mp4
    caption.txt                # the script / caption (optional but recommended)
    meta.json                  # optional, see below
    thumbnail.jpg              # optional custom YouTube thumbnail
```

Loose files work too: `video.mp4` + `caption.txt` and/or `meta.json` dropped straight into
`Ready/` become one job. A job starts once it has **an mp4 plus at least one of `caption.txt`,
`meta.json`, `subject.txt`**, no `.crdownload`/`.part` download is in progress, and nothing has
changed for `STABLE_SECONDS`. **Write `meta.json`/`caption.txt` last** so a half-copied set of
clips is never picked up.

`meta.json` (every field optional; see `examples/`):

```json
{
  "subject": "Opening Range Breakout strategy for the first 15 minutes",
  "title": "Only set this to override Claude",
  "description": "...",
  "tags": ["opening range breakout", "day trading"],
  "hashtags": ["daytrading", "trading"],
  "thumbnail_text": "ORB IN 60s",
  "thumbnail_time": 2.0,
  "notes": "extra guidance for the copywriter",
  "fit": "pad",
  "edit": true,
  "platforms": ["youtube", "instagram", "tiktok"],
  "disclaimer": "Not financial advice.",
  "youtube":   {"privacy": "public", "publish_at": "2026-09-26T14:00:00Z", "category_id": "27"},
  "instagram": {"share_to_feed": true, "caption": "override", "collaborators": ["someone"]},
  "tiktok":    {"mode": "inbox", "privacy_level": "PUBLIC_TO_EVERYONE", "caption": "override"}
}
```

- `fit`: `pad` letter-boxes non-9:16 clips; `crop` fills the frame.
- `edit: false` posts a single mp4 without re-encoding it.
- Values in meta.json always override what Claude writes. Claude only fills what's missing
  (`METADATA_MODE=fill`).

## 3. Platform setup

**Easiest:** run `python setup_wizard.py`. It opens each page, tells you what to click, and saves
what you paste into `.env`. The sections below are the same steps in detail.

### Claude (copywriter agent)
Create an API key at https://platform.claude.com and set `ANTHROPIC_API_KEY`. Without a key, the
bot still runs: metadata then comes from `meta.json` / `caption.txt` via a plain template.
The default model is `claude-opus-5`, with server-side refusal fallback turned on.

### YouTube (YouTube Data API v3)
1. https://console.cloud.google.com: create a project, then enable **YouTube Data API v3**.
2. **OAuth consent screen**: External, add your Google account as a test user, then **Publish app**
   (set it to *In production*). If you leave it in *Testing*, refresh tokens expire after 7 days.
3. **Credentials**: create an OAuth client ID of type **Desktop app**. Put the ID and secret into
   `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`.
4. `python auth_setup.py youtube`: sign in with the channel's account. This saves `YOUTUBE_REFRESH_TOKEN`.

Notes:
- **Unverified API projects:** videos uploaded by an API project that hasn't passed Google's
  audit are locked to *private*. Request the audit (YouTube API Services "Audit and Quota
  Extension" form) to post publicly.
- **Quota:** the default quota is 10,000 units/day. An upload costs about 1,600 and a thumbnail
  50, so 4 videos/day fits.
- **Custom thumbnails** need a phone-verified channel. Without one, the video still posts and
  `job.json` records the thumbnail error.
- **Shorts:** a vertical video of 3 minutes or less is a Short automatically. `#Shorts` is added too.

### Instagram Reels (Instagram Graph API)
Requires an **Instagram Business or Creator account linked to a Facebook Page**.
1. https://developers.facebook.com: create an app (type Business). Add the **Instagram** product
   (API setup with Facebook Login). Put the app ID and secret into `FB_APP_ID` / `FB_APP_SECRET`.
2. In **Graph API Explorer**, pick your app and generate a user token with `instagram_basic,
   instagram_content_publish, pages_show_list, pages_read_engagement, business_management`.
3. `python auth_setup.py instagram`: paste that token. The helper exchanges it for a long-lived
   token and saves a **Page token that doesn't expire** (`IG_TOKEN`) plus `IG_USER_ID`.
   Alternative: a Business Manager *System User* token also never expires.

The bot uploads the local mp4 directly via Instagram's resumable upload (`rupload.facebook.com`),
so no `video_url` hosting is needed. Google Drive share links do **not** work as `video_url`,
because Instagram needs a direct file URL. Instagram caps API publishing per rolling 24 hours,
well above 4/day. A custom cover image would need a public URL, so the Reel cover uses the
thumbnail frame time instead.

### TikTok (Content Posting API)
1. https://developers.tiktok.com: create an app, add **Login Kit** + **Content Posting API**,
   and request scopes `user.info.basic`, `video.upload` (and `video.publish` for direct post).
   Register a redirect URI and copy it into `TIKTOK_REDIRECT_URI`. Put the client key and secret into `.env`.
   App review usually takes a day or two.
2. `python auth_setup.py tiktok`: approve, then paste the URL you're redirected to. This saves
   `TIKTOK_TOKEN` + `TIKTOK_REFRESH_TOKEN`. The 24h access token is refreshed automatically and
   written back to `.env`.
3. Choose a mode:
   - `TIKTOK_MODE=inbox` (default): works **before** the app audit. The video lands in your
     TikTok inbox/drafts and you tap Post. The caption to paste is saved in `job.json`
     (`platforms.tiktok.caption_to_paste`).
   - `TIKTOK_MODE=direct`: posts fully automatically. Until TikTok audits your app, posts are
     forced to `SELF_ONLY` (private). After the audit, set `TIKTOK_PRIVACY_LEVEL=PUBLIC_TO_EVERYONE`.

## 4. Run

```bash
python watcher.py check              # verifies every platform's credentials
python watcher.py once --dry-run     # full pipeline (stitch, Claude, thumbnail), no uploads
python watcher.py                    # watch forever
```

Results:
- `~/TradingShorts/Done/<job>/job.json` holds every agent's output, the post IDs and URLs.
  `_out/` has the final mp4 and thumbnail.
- `~/TradingShorts/Failed/<job>/job.json` holds the error for each platform.
- Logs go to `~/TradingShorts/logs/bot.log`.

**Retrying.** `python watcher.py retry` moves failed jobs back to `Ready/`. Platforms that
already posted are **never posted twice**, and the same title and description are reused. Use
`retry --fresh` to redo the edit, metadata and thumbnail steps (e.g. after editing `meta.json`).
A crash mid-job parks it in `Failed/` on the next start, for you to retry.

### Keep it running

**macOS (launchd):** save as `~/Library/LaunchAgents/com.shorts.bot.plist`, fix the paths, then
`launchctl load ~/Library/LaunchAgents/com.shorts.bot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.shorts.bot</string>
  <key>ProgramArguments</key><array>
    <string>/Users/YOU/trading-shorts-bot/.venv/bin/python</string>
    <string>/Users/YOU/trading-shorts-bot/watcher.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/YOU/trading-shorts-bot</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
```

**Linux (systemd user service):** `~/.config/systemd/user/shorts-bot.service`:

```ini
[Service]
WorkingDirectory=%h/trading-shorts-bot
ExecStart=%h/trading-shorts-bot/.venv/bin/python watcher.py
Restart=always
[Install]
WantedBy=default.target
```
Then `systemctl --user enable --now shorts-bot`.

**Windows:** in Task Scheduler, create a task "At log on" that runs `.venv\Scripts\python.exe watcher.py`
with "Start in" set to the bot folder.

## Settings (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `SHORTS_ROOT` | `~/TradingShorts` | Contains `Ready/ Processing/ Done/ Failed/ logs/` |
| `PLATFORMS` | all three | Comma list of enabled platforms |
| `STABLE_SECONDS` / `POLL_SECONDS` | 10 / 5 | Settle time before a job starts / poll interval |
| `MAX_DURATION` | 60 | Longer input is trimmed |
| `VIDEO_WIDTH` × `VIDEO_HEIGHT` | 1080×1920 | Output size |
| `DRY_RUN` | false | Skip real uploads |
| `AI_GENERATED` | true | YouTube *altered/synthetic content* + TikTok *AI-generated* labels (both platforms require disclosure for realistic AI presenters/voices) |
| `DISCLAIMER` | empty | Appended to every description/caption |
| `METADATA_MODE` | fill | `fill` / `always` / `off` (Claude usage) |
| `CLAUDE_MODEL` | claude-opus-5 | Copywriter model |
| `CHANNEL_STYLE` | empty | Voice/brand notes for the copywriter |
| `YOUTUBE_PRIVACY`, `YOUTUBE_CATEGORY_ID` | public, 27 | Defaults for YouTube |
| `TIKTOK_MODE`, `TIKTOK_PRIVACY_LEVEL` | inbox, SELF_ONLY | See TikTok above |

## Tests

```bash
python -m pytest -q
```

The suite builds real clips with ffmpeg. It stitches 6 clips (one without audio) end to end in
dry-run mode, and checks the platform limits, retry without double-posting, and the Claude
request shape (mocked).

## Daily live stream

```
 06:00 every weekday (LIVE_START / LIVE_DAYS)             python live_gui.py  (or live.py daemon)
 ┌──────────────────────────────────────────────────────────────────────────────────────────┐
 │ 1 GatewayAgent  IBC logs IB Gateway into your PAPER account, waits for the API port     │
 │ 2 BrowserAgent  opens aialgopro.com in its own Chrome window, clicks the start button   │
 │ 3 YouTubeAgent  creates today's broadcast (title/description/thumbnail), reusable key   │
 │ 4 OBSAgent      launches OBS, switches to your scene, sets the key, starts streaming    │
 │ 5 Watchdog      every 30s: Gateway up? scanner window open? OBS streaming? fixes drops  │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
   setup starts LIVE_PREP_MIN early, the stream starts exactly at LIVE_START, ends at LIVE_END
```

No agent framework (Hermes etc.) is needed. The steps are the same every day, so they run as plain
code: no AI tokens, and the same thing happens every morning.

### One-time setup

1. **Install:** `pip install -r requirements.txt`. On Linux you also need `sudo apt install python3-tk`
   for the GUI.
2. **IBC** (automates the Gateway login): download from https://github.com/IbcAlpha/IBC/releases and
   unzip it, e.g. to `C:\IBC` or `/opt/ibc`. IB Gateway itself must be installed (stable or latest).
3. **OBS:** Tools > WebSocket Server Settings > *Enable*, then copy the password. Make a scene
   (e.g. `Scanner`) with a **Window Capture** of the scanner browser window (run *Test* once so the
   window exists), plus your webcam/mic if you like.
4. **YouTube:** enable live streaming on your channel (youtube.com/features; the first time takes up
   to 24 h). Then click *Connect YouTube account* in the GUI (or `python auth_setup.py youtube`).
   If you connected before for Shorts, do it again: going live needs one extra permission.
5. Run **`python live_gui.py`** and fill in the tabs:

| Tab | What to enter |
|---|---|
| Schedule | time (06:00), days, end time, time zone (empty = this PC's) |
| IB Gateway | **paper** username + password, IBC folder, Gateway version (e.g. `1030`), API port your scanner uses |
| Scanner site | *Sign in to scanner site (once)*, then the **steps** (see below) and *Test scanner steps* |
| OBS | path to OBS, WebSocket password, scene name |
| YouTube | title template (`{weekday}`, `{date}`), description, tags, privacy, thumbnail |

   **Scanner steps** are what the bot does on the site every morning, one per line (kept in
   `scanner_steps.txt`, which updates never overwrite). For aialgopro:
   ```
   goto https://aialgopro.com
   click Scanner
   click Scan Market
   if Gateway Paper        # only when the connect popup shows (not when already connected)
     click Gateway Paper
     type Local connector secret = {SCANNER_SECRET}
     click Test Connection
     wait Connected        # waits for this text; "Not connected" / "Disconnected" don't count
   end                     # (the scan then starts by itself; buttons in an open popup are tried first)
   wait 10                 # seconds
   click Full screen       # exactly as the site writes it
   ```
   `{SCANNER_SECRET}` is filled in from the **Local connector secret** setting, so the secret never
   appears in the steps or the logs. Also: `key F11` (press a key), `click css=<selector>`.

   **Website or desktop app.** *Scanner to stream* switches between the website (Chrome) and a
   desktop scanner app such as **Farhad AI Scanner** (an Electron app). In app mode the bot starts
   the app with a remote-control port and drives its window with the same kind of steps
   (`click Connect`, `wait Connected`, `click Scan`); each mode keeps its own step list.

6. Click **Check setup**, then **Test (no stream)**. That runs everything except going live.
7. Tick **Start the scheduler automatically when I log in**. On Windows this puts a small launcher in
   your Startup folder (no admin rights needed) and starts the scheduler right away in a minimised
   window; on macOS/Linux it registers a launchd agent / systemd user service. Or click **Start scheduler** to run it
   while the app is open.

If the PC was off and you log in after the start time but before the end time, the scheduler
starts that day's stream straight away (once per day; `LIVE_CATCH_UP=false` turns this off).

The PC must be on and logged in at stream time (a locked screen is fine), because OBS and the
browser need your desktop. While the scheduler runs it pauses idle sleep. If the PC still sleeps
at night, tick **Schedule > Wake the PC from sleep for the stream** (`LIVE_WAKE=true`, Windows): on
Save the app creates a task "LiveStreamBot Wake" that wakes the PC 10 minutes before setup on
stream days, and turns on *Allow wake timers*. It works from Sleep/Hibernate, not from Shut down.
Laptops: keep it plugged in, and set *Lid close action* to *Do nothing* if the lid may be closed.

### Status tab

The app opens on **Status**: a coloured banner (blue waiting with a countdown, orange getting
ready, red LIVE with the time on air, grey scheduler off), Start/Stop scheduler, Go live now,
End today's stream, a checklist (scheduler, wake-up, Gateway, scanner, YouTube, OBS, streaming)
with what each did, live stats (viewers, privacy, auto-fixes, last health check) and the last
7 days. The bot writes this to `Live/status.json`.

**End today's stream** is final for the day: the scheduler doesn't retry or restart it (ending
the broadcast in YouTube Studio counts too). Closing OBS or the scanner by hand is treated as a
crash and fixed, so use the button to end a stream.

### Signing in to the scanner site

If the site shows its sign-in form (signed out, session expired), the bot signs in by itself and
presses the button: with **Scanner site > Site email / Site password** when set, otherwise with the
browser's saved (autofill) login. A wrong login stops with the site's own message.

### Website data only (IB Gateway for the scanner site)

**▶ Website data only** (Status tab) starts IB Gateway (paper), the scanner site's connector and
tunnel when they're set, then opens the website in the bot's browser and runs your Scanner site steps
up to the IBKR connection (everything before Stream Mode / full screen). It keeps all of that up
(checked every 30 s) until **■ Stop website data**. No OBS or YouTube; while a stream runs, the
stream has the browser. IB Gateway stays logged in when you stop it. Untick "Website data: open the
website and connect to IBKR" to run only Gateway + connector.

It uses the same IB Gateway **paper** login as the stream (no phone approval). The paper account
gets the same real-time data as your live account once market-data sharing is on (IBKR Client Portal >
Settings > Paper Trading Account > Share real-time market data subscriptions with paper account).

To run it on a schedule instead, tick **IB Gateway > Website data on a schedule** and pick the days,
start and stop times. The scheduler (▶ Start scheduler) then starts IB Gateway at the start time,
keeps it up, and at the stop time closes it (unless a stream is on; untick "Close IB Gateway at the
stop time" to leave it running). Gateway is closed through IBC's command server on 127.0.0.1:7462.

### Autopilot: the simulated traders every market day

The site's **Autopilot & Results** page runs Bot Trader, scanner trading and Opportunities auto-trade by
themselves from 9:30 to 16:00 New York while it is open, and shows every result. The bot opens it in a second
window titled "LIVE BOT - Trading" whenever it opens the site (Website data and streams), keeps the scanner
window in front so the stream never shows it, reopens it if it is closed, and stops Chrome from slowing it
down in the background. Untick **Also open Autopilot** (IB Gateway tab) to turn this off.

To run it every day: in the IB Gateway tab, tick **Website data on a schedule**, set the days, start
**09:00** and stop **16:15** (your time zone; the stop must be after 16:00 New York), and Save (it also sets
the PC to wake for it). Then, once, open the Autopilot page and tick **Run every market day**; that setting is
saved with your account, so the bot's browser uses it too. Simulated trades only: no real orders.

### Changing settings while it runs

Save in the app while a stream is running and it picks up, within one check (about 30 s): the **end time**
(End at / Duration; an end time already passed ends the stream at that check), the live-data and check
settings, and the Autopilot window. The scheduler takes a new **start time** or days for the next stream,
and Website data a new schedule, the same way. The destination (YouTube/TikTok), title, description and
privacy are set when the broadcast is created, so they apply from the next stream.

### Live data guard (internet outages)

A running IB Gateway can keep its port open after the internet drops while it no longer gets anything from
IBKR, which used to leave the stream live on an empty scanner and Autopilot running without prices.
With **Only go live with live market data** (Schedule tab, on by default; `LIVE_REQUIRE_DATA`):

- Before going live the bot checks the internet and asks IB Gateway for recent SPY 1-minute bars (from 4:05 to
  19:55 New York on weekdays the newest must be at most `DATA_STALE_MIN`, 30, minutes old). Until that
  passes, YouTube and OBS are not started; the status says "Waiting for live market data".
- While live, and during the Website data / Autopilot window, it checks every `DATA_CHECK_SECONDS` (60). With
  no data it reconnects the website, then starts the connector/tunnel if they stopped, then restarts IB
  Gateway (at most every `DATA_GATEWAY_RESTART_MIN`, 5, minutes). With no internet it waits.
- When prices come back it reconnects the scanner and reloads the Autopilot window (its simulated books carry on).
- **Check setup** and **Check Autopilot setup** include a "live data" step.

### TikTok LIVE (on its own, or with YouTube)

Pick where the **scheduled** stream goes in the TikTok tab (**Scheduled stream goes to**):
`youtube` (the default), `tiktok` on its own (no YouTube broadcast is created), or `both`.
**♪ TikTok live now** (Status tab) starts a TikTok-only LIVE straight away, whatever the schedule
is set to; **● Go live now** follows the setting.

Two ways to reach TikTok (**Reach TikTok with**):

- `studio` (default, works for any account that can go LIVE): the bot opens **TikTok LIVE Studio**
  and pops up a reminder; you click **Go LIVE** in it (LIVE Studio has no remote control). Point its
  source at the "LIVE BOT - Scanner" window once. Closing LIVE Studio at the end time ends the LIVE.
  With `tiktok` alone, OBS isn't used at all.
- `rtmp`: OBS streams straight to TikTok with the **Server URL** and **Stream key** from TikTok LIVE
  Center, fully automatic. TikTok only gives stream keys to some accounts and may give a new key for
  each LIVE, so paste the current one before you go live. OBS sends to one place at a time, so `rtmp`
  works with `tiktok` and not with `both` (the app refuses that combination). OBS's own (YouTube)
  stream settings are put back when the TikTok stream ends.

### Commands (same as the buttons)

```bash
python live.py daemon        # wait and go live on schedule (what autostart runs)
python live.py run           # go live now (to STREAM_TO)
python live.py run --to tiktok  # TikTok on its own now (or --to youtube / --to both)
python live.py stop          # end today's stream
python live.py run --dry-run # everything except streaming
python live.py check         # Gateway login, OBS, YouTube, scanner site
python live.py site-login    # sign in to the scanner site once
python live.py site-test     # run only the scanner steps, window stays open 60s
python live.py data          # website data only: IB Gateway (+ connector), kept running
```

### Notes

- **Paper only:** the bot refuses to continue if the logged-in account isn't a paper (`DU…`) account
  (`IB_REQUIRE_PAPER=true`). The password lives only in `.env` and in IBC's `config.ini` under
  `~/TradingShorts/Live/.ibc/`, which is readable by you only.
- **2FA:** paper logins normally don't ask for 2FA. If yours does, IBC waits for you to approve it
  on IBKR Mobile.
- **Duplicates:** today's broadcast id is saved in `~/TradingShorts/Live/<date>/session.json`, so
  re-running after a crash reuses it. Only one scheduler can run at a time.
- **Unlisted first, public once it works** (needs the YouTube API): each broadcast starts as
  `LIVE_START_PRIVACY` (unlisted) and switches to `LIVE_PRIVACY` (public) after
  `LIVE_PUBLIC_AFTER_MIN` minutes (3) of OBS streaming, a non-black picture and YouTube reporting a
  healthy stream. Any glitch restarts the clock; a broken stream never goes public.
- **Without the YouTube API:** set `YOUTUBE_LIVE_API=false` and paste your YouTube stream key into
  OBS (Settings > Stream). The bot then just presses *Start Streaming*.
- **Market data:** showing real-time exchange data on a public stream counts as redistribution
  under most exchange agreements. Check what your scanner site and data subscriptions allow.
- Logs: `~/TradingShorts/logs/bot.log` (bot) and `ibgateway.log` (IBC/Gateway).
