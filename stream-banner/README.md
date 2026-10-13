# Stream banner

Top and bottom bars for your YouTube live stream (promo text, logo, promo images or a QR code,
LIVE badge, New York clock, US market open/closed), **pop-up messages with effects** (confetti, rockets,
money rain, fireworks, sparkles, screen glow) and **frosted covers** to hide parts of the screen. The
middle is transparent, so the trading chart you stream stays visible.

| File | What it is |
|---|---|
| `banner.html` | The overlay you add to OBS |
| `banner-config.js` | Your text, images, colours, pop-ups and covers (the banner checks it every second) |
| `editor.html` | Change everything with a live preview over a sample chart |

No install and no program to run: OBS opens `banner.html` straight from this folder.

## Add it to OBS (once)

1. Open the scene that shows your chart (the `OBS_SCENE` your live bot uses).
2. **Sources → + → Browser**, name it "Banner".
3. Tick **Local file**, **Browse…** and pick `banner.html` in this folder.
4. Width and Height = your OBS canvas size (**Settings → Video → Base (Canvas) Resolution**, e.g.
   1920×1080, or 2560×1080 / 3440×1440 on an ultrawide). Leave the rest as it is.
5. In the Sources list, drag **Banner** to the **top** so it sits above the chart.
6. Right-click **Banner → Transform → Fit to screen** (Ctrl+F) so it fills the whole canvas.

The bars always stretch edge to edge, whatever the screen shape; their height follows the
canvas height (the sizes in the editor are for a 1080-pixel-tall stream).

If the bars cover the chart's price or time labels, fit the chart between them: right-click the chart
source → **Transform → Edit Transform**, set *Position* Y to the top bar height (96 by default) and the
*Bounding box* height to 1080 minus both bars (1080 − 96 − 78 = **906**), with *Bounding box type*
"Scale to inner bounds".

## Change things (live)

1. Double-click `editor.html` (Chrome or Edge).
2. Click **Save & go live** once and choose `banner-config.js` in this folder (replace it).
3. That's it: with **Live** ticked, every change goes on stream about a second after you stop typing.
   No more saving. The editor remembers the file; next time you open it, your first click allows it again.

Everything you can change: messages (one per line), one-at-a-time or scrolling ticker, bar size,
colours, how see-through the bars are, the red badge, a logo, promo images or a QR code, clock,
market status, the light shimmer, pop-ups and covers.

**Images:** copy the picture into this folder first, then type its file name (e.g. `logo.png`).

## Pop-up messages

Big animated text on the stream, for example "🚀 BREAKOUT!" or "🔔 Subscribe".

- **+ Add a pop-up…** gives ready-made ones (subscribe reminder, breakout, new high of day, watch this
  level, like the stream, market opens soon) or your own text.
- For each: where on screen (9 spots, never under the bars), animation (pop, slide, drop, bounce,
  shake, glow pulse, typewriter), look (box, big text, neon, ribbon), effect (confetti, rockets,
  money, your own emoji, fireworks, sparkles, screen glow), size, colour and how long it stays.
- **▶ Show now** (on each card, and as quick buttons at the top) puts it on stream within a second,
  like a soundboard. **Repeat every** shows it by itself every so many minutes (0 = only when you click).
- Several at once wait their turn. A click from before OBS started is not replayed.

## Hide areas (covers)

**+ Add a cover** puts a frosted box over part of the screen (account balance, order panel…).
Set its position and size in % of the screen while watching the preview; give it a label like
"🔒 Private" or leave it empty. **Turn off** hides the cover without deleting it.

**Why a cover and not a blur:** the banner is a separate layer *on top of* your chart in OBS, so it
can't see or blur what's underneath, only cover it. For a real blur of part of the chart, use an OBS
filter instead: install a blur plugin (for example the free "Composite Blur" plugin from the OBS
website's plugin list), then duplicate your chart source, crop the copy to the area to blur and add the
blur filter to that copy.

You can also edit `banner-config.js` in Notepad; keep the quotes and commas as they are.

The market status follows regular New York hours (pre-market 4:00–9:30, open 9:30–16:00,
after-hours 16:00–20:00, Monday to Friday). It doesn't know exchange holidays.
