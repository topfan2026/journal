# trading-shorts-bot

A local auto-publishing bot for 60-second vertical videos. You drop a video (or 6×10s clips) plus a
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
